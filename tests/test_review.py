"""2.2: what the Home Assistant quality-scale review found, one test per finding."""

from __future__ import annotations

import copy
import logging
from datetime import timedelta

import aiohttp
import pytest
from homeassistant.components.climate import ATTR_FAN_MODE, ATTR_HVAC_MODE, HVACMode
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.fan import ATTR_PERCENTAGE
from homeassistant.components.fan import DOMAIN as FAN_DOMAIN
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, CONF_PASSWORD, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.homewizard_climate import api as api_module
from custom_components.homewizard_climate import async_remove_config_entry_device
from custom_components.homewizard_climate import climate as climate_module
from custom_components.homewizard_climate.api import HomeWizardResponseError
from custom_components.homewizard_climate.const import DOMAIN

from .conftest import make_entry, wait_for
from .fake_cloud import FAN_STATE, HEATER_STATE, HEATERFAN_STATE, PASSWORD, USERNAME, FakeCloud, FakeDevice

BEDROOM = "fan.bedroom_fan"
BEDROOM_ID = "FAN000000000001"


@pytest.fixture(autouse=True)
def no_mode_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(climate_module, "MODE_CHANGE_DELAY", 0)


async def _setup(hass: HomeAssistant, entity_id: str = BEDROOM) -> MockConfigEntry:
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(lambda: hass.states.get(entity_id) and hass.states.get(entity_id).state != STATE_UNAVAILABLE, hass)
    return entry


def _heaters(cloud: FakeCloud, heaterfan: dict | None = None) -> None:
    cloud.devices = [
        FakeDevice("HF0000000000001", "Heater fan", "heaterfan", heaterfan or copy.deepcopy(HEATERFAN_STATE)),
        FakeDevice("HT0000000000001", "Glass panel", "heater", copy.deepcopy(HEATER_STATE)),
        FakeDevice("IR0000000000001", "IR panel", "infraredheater", {"power_on": True, "target_temperature": 20}),
    ]


# ---- B1, B8: set_temperature ---------------------------------------------


async def test_set_temperature_with_hvac_mode_switches_on_then_sets_it(hass: HomeAssistant, cloud: FakeCloud) -> None:
    _heaters(cloud)
    await _setup(hass, "climate.glass_panel")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: "climate.glass_panel", ATTR_TEMPERATURE: 23, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    await wait_for(lambda: cloud.device("HT0000000000001").state["target_temperature"] == 23, hass)
    sent = [p for p in cloud.patches_sent() if p[0] == "HT0000000000001"]
    assert sent == [("HT0000000000001", "/state/power_on", True), ("HT0000000000001", "/state/target_temperature", 23)]


async def test_set_temperature_with_off_only_switches_off(hass: HomeAssistant, cloud: FakeCloud) -> None:
    _heaters(cloud)
    await _setup(hass, "climate.ir_panel")
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_temperature",
        {ATTR_ENTITY_ID: "climate.ir_panel", ATTR_TEMPERATURE: 25, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    await wait_for(lambda: hass.states.get("climate.ir_panel").state == HVACMode.OFF, hass)
    assert [p for p in cloud.patches_sent() if p[0] == "IR0000000000001"] == [
        ("IR0000000000001", "/state/power_on", False)
    ]


async def test_temperature_is_rounded_not_truncated(hass: HomeAssistant, cloud: FakeCloud) -> None:
    _heaters(cloud)
    await _setup(hass, "climate.ir_panel")
    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_temperature", {ATTR_ENTITY_ID: "climate.ir_panel", ATTR_TEMPERATURE: 21.99}, blocking=True
    )
    await wait_for(lambda: cloud.device("IR0000000000001").state["target_temperature"] == 22, hass)


async def test_infrared_heater_entity(hass: HomeAssistant, cloud: FakeCloud) -> None:
    _heaters(cloud)
    await _setup(hass, "climate.ir_panel")
    state = hass.states.get("climate.ir_panel")
    assert state.state == HVACMode.HEAT
    assert state.attributes["hvac_modes"] == ["heat", "off"]
    assert state.attributes[ATTR_TEMPERATURE] == 20


# ---- B7: heater fan scale while off --------------------------------------


@pytest.mark.parametrize(("heater", "expected"), [(True, "high"), (False, "medium")])
async def test_heater_fan_scale_follows_the_heater_flag_even_when_off(
    hass: HomeAssistant, cloud: FakeCloud, heater: bool, expected: str
) -> None:
    _heaters(cloud, {**copy.deepcopy(HEATERFAN_STATE), "power_on": False, "heater": heater, "fan_speed": 4})
    await _setup(hass, "climate.heater_fan")
    assert hass.states.get("climate.heater_fan").state == HVACMode.OFF
    assert hass.states.get("climate.heater_fan").attributes[ATTR_FAN_MODE] == expected


# ---- B2, B3, B4, B10: the connection loop --------------------------------


async def test_a_cloud_that_drops_every_session_backs_off(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = await _setup(hass)
    cloud.close_on_connect = True
    await cloud.drop_connections()
    await wait_for(lambda: cloud.connections >= 5, hass)
    # Never a working session again, so the wait keeps growing instead of going back to the minimum.
    assert entry.runtime_data.connection.next_delay > 0.05


async def test_a_refused_hello_retries_instead_of_waiting_forever(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass)
    cloud.hello_status = 503
    await cloud.drop_connections()
    await wait_for(lambda: cloud.hellos >= 3, hass)
    assert hass.states.get(BEDROOM).state == STATE_UNAVAILABLE
    cloud.hello_status = 200
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_OFF, hass)


async def test_a_malformed_message_does_not_kill_the_connection(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass)
    await cloud.broadcast({"type": "json_patch", "device": BEDROOM_ID, "patch": 5})
    cloud.device(BEDROOM_ID).state["power_on"] = True
    await cloud.push_full(BEDROOM_ID)
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_ON, hass)
    assert cloud.hellos == 1


async def test_after_a_drop_the_old_state_is_not_shown_as_current(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = await _setup(hass)
    connection = entry.runtime_data.connection
    await cloud.drop_connections()
    await wait_for(lambda: not connection.connected, hass)
    assert connection.devices[BEDROOM_ID].received is False


async def test_lost_and_back_are_logged_once_at_info(
    hass: HomeAssistant, cloud: FakeCloud, caplog: pytest.LogCaptureFixture
) -> None:
    await _setup(hass)
    caplog.set_level(logging.INFO, logger="custom_components.homewizard_climate.connection")
    await cloud.drop_connections()
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_UNAVAILABLE, hass)
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_OFF, hass)
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert messages.count("Connection with the HomeWizard cloud lost; reconnecting") == 1
    assert messages.count("Connection with the HomeWizard cloud is back") == 1


# ---- B5, B6: transport errors --------------------------------------------


async def test_a_write_on_a_closing_socket_becomes_the_translated_error(
    hass: HomeAssistant, cloud: FakeCloud, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = await _setup(hass)
    ws = entry.runtime_data.connection._ws  # noqa: SLF001

    async def closing(_payload: object) -> None:
        raise aiohttp.ClientConnectionResetError("Cannot write to closing transport")

    monkeypatch.setattr(ws, "send_json", closing)
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(FAN_DOMAIN, "turn_on", {ATTR_ENTITY_ID: BEDROOM}, blocking=True)
    assert raised.value.translation_key == "not_connected"


async def test_keepalive_ends_quietly_when_the_socket_is_going_down(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = await _setup(hass)

    class Dying:
        closed = False

        async def ping(self) -> None:
            raise aiohttp.ClientConnectionResetError("Cannot write to closing transport")

    assert await entry.runtime_data.connection._keepalive(Dying()) is None  # noqa: SLF001


# ---- B9, I3: Repairs issues per account ----------------------------------


async def test_unsupported_issues_belong_to_their_account(hass: HomeAssistant, cloud: FakeCloud) -> None:
    other = MockConfigEntry(domain=DOMAIN, entry_id="otheraccount01")
    ir.async_create_issue(
        hass,
        DOMAIN,
        "unsupported_type_otheraccount01_kettle",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="unsupported_type",
    )
    # What 2.0/2.1 left: one issue per type for the whole domain.
    ir.async_create_issue(
        hass,
        DOMAIN,
        "unsupported_type_aerofryer",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="unsupported_type",
    )
    entry = await _setup(hass)
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, "unsupported_type_otheraccount01_kettle") is not None
    assert issues.async_get_issue(DOMAIN, "unsupported_type_aerofryer") is None
    del other, entry


async def test_removing_the_entry_removes_its_issues(hass: HomeAssistant, cloud: FakeCloud) -> None:
    cloud.devices.append(FakeDevice("AF0000000000001", "Air fryer", "aerofryer", {"power_on": False}))
    entry = await _setup(hass)
    issue_id = f"unsupported_type_{entry.entry_id}_aerofryer"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


# ---- Q6, Q7: devices added to or removed from the account ----------------


async def test_new_device_in_the_app_appears_without_a_reload(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass)
    cloud.devices.append(FakeDevice("FAN000000000003", "Study fan", "fan", copy.deepcopy(FAN_STATE)))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await wait_for(
        lambda: hass.states.get("fan.study_fan") and hass.states.get("fan.study_fan").state == STATE_OFF, hass
    )


async def test_device_removed_in_the_app_leaves_home_assistant(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = await _setup(hass)
    dev_reg = dr.async_get(hass)
    assert dev_reg.async_get_device_by_identifier((DOMAIN, "FAN000000000002"), entry.entry_id) is not None
    cloud.devices = [d for d in cloud.devices if d.identifier != "FAN000000000002"]
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await wait_for(
        lambda: dev_reg.async_get_device_by_identifier((DOMAIN, "FAN000000000002"), entry.entry_id) is None, hass
    )
    assert hass.states.get(BEDROOM).state == STATE_OFF


async def test_stale_device_from_before_is_removed_at_setup(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass)
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, "GONE00000000001")}, name="Old")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert dev_reg.async_get_device_by_identifier((DOMAIN, "GONE00000000001"), entry.entry_id) is None


async def test_only_devices_gone_from_the_account_can_be_deleted_by_hand(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = await _setup(hass)
    dev_reg = dr.async_get(hass)
    live = dev_reg.async_get_device_by_identifier((DOMAIN, BEDROOM_ID), entry.entry_id)
    assert await async_remove_config_entry_device(hass, entry, live) is False
    gone = dev_reg.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, "GONE00000000002")})
    assert await async_remove_config_entry_device(hass, entry, gone) is True


# ---- Q8: reconfigure -----------------------------------------------------


async def test_reconfigure_changes_the_password(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass, password="old password")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"]["username"] == USERNAME
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PASSWORD] == PASSWORD


# ---- I4, api ---------------------------------------------------------------


async def test_turn_on_at_zero_percent_turns_it_off(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass)
    await hass.services.async_call(FAN_DOMAIN, "turn_on", {ATTR_ENTITY_ID: BEDROOM}, blocking=True)
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_ON, hass)
    await hass.services.async_call(FAN_DOMAIN, "turn_on", {ATTR_ENTITY_ID: BEDROOM, ATTR_PERCENTAGE: 0}, blocking=True)
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_OFF, hass)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [("not json", "text/plain"), ("[1, 2]", "application/json"), ('{"something": "else"}', "application/json")],
)
async def test_unexpected_answers_from_the_cloud_are_response_errors(
    hass: HomeAssistant, socket_enabled: None, aiohttp_server, body: str, content_type: str
) -> None:
    from aiohttp import web

    async def handler(_request: web.Request) -> web.Response:
        return web.Response(text=body, content_type=content_type)

    app = web.Application()
    app.router.add_get("/devices", handler)
    server = await aiohttp_server(app)
    async with aiohttp.ClientSession() as session:
        api = api_module.HomeWizardClimateApi(session, USERNAME, PASSWORD)
        with pytest.raises(HomeWizardResponseError):
            api_module.API_DEVICES_URL = str(server.make_url("/devices"))
            try:
                await api.async_get_devices()
            finally:
                api_module.API_DEVICES_URL = "https://api.homewizardeasyonline.com/v1/auth/devices"
