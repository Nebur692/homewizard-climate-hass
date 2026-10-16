"""2.1: air conditioners, air coolers and air purifiers, with the fields of the official app."""

from __future__ import annotations

import copy

import pytest
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.fan import ATTR_PERCENTAGE
from homeassistant.components.fan import DOMAIN as FAN_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.homewizard_climate import climate as climate_module
from custom_components.homewizard_climate.const import DOMAIN

from .conftest import make_entry, wait_for
from .fake_cloud import (
    AIRCONDITIONER_STATE,
    AIRCOOLER_STATE,
    DEHUMIDIFIER_STATE,
    HEATER_STATE,
    HEATERFAN_STATE,
    PURIFIER_STATE,
    FakeCloud,
    FakeDevice,
)

AC = "climate.princess_ac"
AC_ID = "AC0000000000001"
TRISTAR = "climate.tristar_ac"
COOLER = "climate.air_cooler"
COOLER_ID = "AK0000000000001"
PURIFIER = "fan.big_purifier"
PURIFIER_ID = "PU0000000000001"
SMALL = "fan.small_purifier"


@pytest.fixture(autouse=True)
def no_mode_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(climate_module, "MODE_CHANGE_DELAY", 0)


@pytest.fixture
async def devices(hass: HomeAssistant, cloud: FakeCloud) -> FakeCloud:
    cloud.devices = [
        FakeDevice(AC_ID, "Princess AC", "airconditioner", copy.deepcopy(AIRCONDITIONER_STATE), model="PS-A018"),
        FakeDevice(
            "AC0000000000002", "Tristar AC", "airconditioner", copy.deepcopy(AIRCONDITIONER_STATE), model="PS-A007"
        ),
        FakeDevice(COOLER_ID, "Air cooler", "aircooler", copy.deepcopy(AIRCOOLER_STATE)),
        FakeDevice(
            PURIFIER_ID, "Big purifier", "airpurifier", copy.deepcopy(PURIFIER_STATE), model="HWC-6089", version="1.2.3"
        ),
        FakeDevice("PU0000000000002", "Small purifier", "airpurifier", copy.deepcopy(PURIFIER_STATE), model="HWC-6090"),
        FakeDevice("DH0000000000001", "Dehumidifier", "dehumidifier", copy.deepcopy(DEHUMIDIFIER_STATE)),
        FakeDevice("HT0000000000001", "Glass panel", "heater", copy.deepcopy(HEATER_STATE)),
    ]
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(
        lambda: all(
            hass.states.get(e) and hass.states.get(e).state != STATE_UNAVAILABLE
            for e in (AC, TRISTAR, COOLER, PURIFIER, SMALL)
        ),
        hass,
    )
    return cloud


async def _climate(hass: HomeAssistant, service: str, entity_id: str, **data) -> None:
    await hass.services.async_call(CLIMATE_DOMAIN, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True)


def _sent(cloud: FakeCloud, identifier: str) -> list[tuple[str, object]]:
    return [(path, value) for dev, path, value in cloud.patches_sent() if dev == identifier]


# ---- air conditioner -----------------------------------------------------


async def test_air_conditioner_reads_its_own_fields(hass: HomeAssistant, devices: FakeCloud) -> None:
    state = hass.states.get(AC)
    assert state.state == HVACMode.OFF
    assert state.attributes["hvac_modes"] == ["off", "cool", "dry", "fan_only", "heat"]
    assert state.attributes["current_temperature"] == 27
    assert state.attributes[ATTR_TEMPERATURE] == 22
    assert state.attributes["min_temp"] == 16
    assert state.attributes["max_temp"] == 31
    assert state.attributes[ATTR_FAN_MODE] == "low"
    assert state.attributes[ATTR_PRESET_MODE] == "none"


async def test_two_speed_model_only_offers_low_and_high(hass: HomeAssistant, devices: FakeCloud) -> None:
    assert hass.states.get(TRISTAR).attributes[ATTR_FAN_MODES] == ["low", "high"]
    assert hass.states.get(AC).attributes[ATTR_FAN_MODES] == ["low", "medium", "high"]


@pytest.mark.parametrize(
    ("hvac_mode", "mode"),
    [(HVACMode.COOL, "cool"), (HVACMode.DRY, "dehumidify"), (HVACMode.FAN_ONLY, "fan"), (HVACMode.HEAT, "heat")],
)
async def test_air_conditioner_modes_map_to_the_cloud(
    hass: HomeAssistant, devices: FakeCloud, hvac_mode: HVACMode, mode: str
) -> None:
    await _climate(hass, "set_hvac_mode", AC, **{ATTR_HVAC_MODE: hvac_mode})
    await wait_for(lambda: hass.states.get(AC).state == hvac_mode, hass)
    assert devices.device(AC_ID).state["power_on"] is True
    assert devices.device(AC_ID).state["mode"] == mode


async def test_air_conditioner_fan_swing_temperature_and_presets(hass: HomeAssistant, devices: FakeCloud) -> None:
    await _climate(hass, "set_fan_mode", AC, **{ATTR_FAN_MODE: "medium"})
    await _climate(hass, "set_swing_mode", AC, **{ATTR_SWING_MODE: "on"})
    await _climate(hass, "set_temperature", AC, **{ATTR_TEMPERATURE: 19})
    await _climate(hass, "set_preset_mode", AC, **{ATTR_PRESET_MODE: "sleep"})
    await wait_for(lambda: hass.states.get(AC).attributes[ATTR_PRESET_MODE] == "sleep", hass)
    await _climate(hass, "set_preset_mode", AC, **{ATTR_PRESET_MODE: "silent"})
    await wait_for(lambda: hass.states.get(AC).attributes[ATTR_PRESET_MODE] == "silent", hass)
    assert _sent(devices, AC_ID) == [
        ("/state/fan_speed", "med"),
        ("/state/oscillate", True),
        ("/state/target_temperature", 19),
        ("/state/sleep", True),
        ("/state/sleep", False),
        ("/state/silent", True),
    ]


async def test_air_conditioner_off(hass: HomeAssistant, devices: FakeCloud) -> None:
    await _climate(hass, "set_hvac_mode", AC, **{ATTR_HVAC_MODE: HVACMode.COOL})
    await wait_for(lambda: hass.states.get(AC).state == HVACMode.COOL, hass)
    await _climate(hass, "set_hvac_mode", AC, **{ATTR_HVAC_MODE: HVACMode.OFF})
    await wait_for(lambda: hass.states.get(AC).state == HVACMode.OFF, hass)
    assert _sent(devices, AC_ID)[-1] == ("/state/power_on", False)


# ---- air cooler ----------------------------------------------------------


async def test_air_cooler(hass: HomeAssistant, devices: FakeCloud) -> None:
    state = hass.states.get(COOLER)
    assert state.state == HVACMode.FAN_ONLY
    assert state.attributes[ATTR_FAN_MODE] == "medium"
    assert state.attributes[ATTR_PRESET_MODE] == "manual"
    assert state.attributes[ATTR_SWING_MODE] == "on"
    await _climate(hass, "set_hvac_mode", COOLER, **{ATTR_HVAC_MODE: HVACMode.COOL})
    await _climate(hass, "set_preset_mode", COOLER, **{ATTR_PRESET_MODE: "natural"})
    await _climate(hass, "set_fan_mode", COOLER, **{ATTR_FAN_MODE: "high"})
    await wait_for(lambda: hass.states.get(COOLER).attributes[ATTR_FAN_MODE] == "high", hass)
    assert hass.states.get(COOLER).state == HVACMode.COOL
    assert _sent(devices, COOLER_ID) == [
        ("/state/cool", True),
        ("/state/mode", "natural"),
        ("/state/fan_speed", "high"),
    ]


# ---- air purifier --------------------------------------------------------


async def test_purifier_is_a_fan_with_four_speeds_on_the_large_model(hass: HomeAssistant, devices: FakeCloud) -> None:
    big = hass.states.get(PURIFIER)
    assert big.state == STATE_ON
    assert big.attributes["percentage_step"] == 25
    assert big.attributes[ATTR_PERCENTAGE] == 50  # speed 2 of 4
    assert big.attributes["preset_modes"] == ["manual", "auto", "sleep"]
    assert big.attributes[ATTR_PRESET_MODE] == "auto"
    small = hass.states.get(SMALL)
    assert small.attributes[ATTR_PERCENTAGE] == 66  # speed 2 of 3
    await hass.services.async_call(
        FAN_DOMAIN, "set_percentage", {ATTR_ENTITY_ID: PURIFIER, ATTR_PERCENTAGE: 100}, blocking=True
    )
    await wait_for(lambda: devices.device(PURIFIER_ID).state["fan_speed"] == 4, hass)
    await hass.services.async_call(FAN_DOMAIN, "turn_off", {ATTR_ENTITY_ID: PURIFIER}, blocking=True)
    await wait_for(lambda: hass.states.get(PURIFIER).state == STATE_OFF, hass)


async def test_purifier_sensors(hass: HomeAssistant, devices: FakeCloud) -> None:
    assert hass.states.get("sensor.big_purifier_air_quality").state == "good"
    assert hass.states.get("sensor.big_purifier_pm2_5").state == "12"
    assert hass.states.get("sensor.big_purifier_temperature").state == "21.5"
    assert hass.states.get("sensor.big_purifier_humidity").state == "48.0"
    assert hass.states.get("sensor.big_purifier_filter_life").state == "73"
    assert hass.states.get("binary_sensor.big_purifier_filter").state == STATE_OFF
    devices.device(PURIFIER_ID).state.update(filter_check=True, air_quality="polluted")
    await devices.push_full(PURIFIER_ID)
    await wait_for(lambda: hass.states.get("binary_sensor.big_purifier_filter").state == STATE_ON, hass)
    assert hass.states.get("sensor.big_purifier_air_quality").state == "polluted"


async def test_model_and_firmware_on_the_device_page(hass: HomeAssistant, devices: FakeCloud) -> None:
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, PURIFIER_ID), entry.entry_id)
    assert device.model_id == "HWC-6089"
    assert device.sw_version == "1.2.3"
    assert device.manufacturer == "HomeWizard"


# ---- dehumidifier, heater: what 2.1 adds ---------------------------------


async def test_dehumidifier_tank_full_and_defrosting(hass: HomeAssistant, devices: FakeCloud) -> None:
    assert hass.states.get("binary_sensor.dehumidifier_water_tank_full").state == STATE_OFF
    assert hass.states.get("binary_sensor.dehumidifier_defrosting").state == STATE_OFF
    devices.device("DH0000000000001").state.update(fault=["water_full"], defrosting=True)
    await devices.push_full("DH0000000000001")
    await wait_for(lambda: hass.states.get("binary_sensor.dehumidifier_water_tank_full").state == STATE_ON, hass)
    assert hass.states.get("binary_sensor.dehumidifier_defrosting").state == STATE_ON


async def test_child_lock_where_the_device_has_one(hass: HomeAssistant, devices: FakeCloud) -> None:
    ent_reg = er.async_get(hass)
    locks = sorted(e.entity_id for e in ent_reg.entities.values() if e.unique_id.endswith("_lock"))
    assert locks == [
        "switch.big_purifier_child_lock",
        "switch.dehumidifier_child_lock",
        "switch.glass_panel_child_lock",
        "switch.small_purifier_child_lock",
    ]
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.glass_panel_child_lock"}, blocking=True
    )
    await wait_for(lambda: hass.states.get("switch.glass_panel_child_lock").state == STATE_ON, hass)
    assert devices.device("HT0000000000001").state["lock"] is True


# ---- heater fan: the whole speed range is read ---------------------------


@pytest.mark.parametrize(
    ("heater", "speed", "expected"),
    [
        (True, 1, "low"),
        (True, 2, "medium"),
        (True, 3, "high"),
        (True, 4, "high"),
        (True, 5, None),
        (False, 3, "low"),
        (False, 4, "medium"),
        (False, 7, "high"),
        (False, 10, "high"),
    ],
)
async def test_heater_fan_reads_every_speed(
    hass: HomeAssistant, cloud: FakeCloud, heater: bool, speed: int, expected: str | None
) -> None:
    state = {**copy.deepcopy(HEATERFAN_STATE), "heater": heater, "fan_speed": speed}
    cloud.devices = [FakeDevice("HF0000000000001", "Heater fan", "heaterfan", state)]
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(
        lambda: hass.states.get("climate.heater_fan") and hass.states.get("climate.heater_fan").state != "unavailable",
        hass,
    )
    assert hass.states.get("climate.heater_fan").attributes[ATTR_FAN_MODE] == expected


async def test_no_deprecated_home_assistant_api_is_used(
    hass: HomeAssistant, cloud: FakeCloud, caplog: pytest.LogCaptureFixture
) -> None:
    # HA logs a warning when an integration touches a deprecated constant or helper;
    # with every platform loaded there must be none (CONCENTRATION_* slipped into 2.1).
    cloud.devices = [
        FakeDevice(PURIFIER_ID, "Big purifier", "airpurifier", copy.deepcopy(PURIFIER_STATE), model="HWC-6089"),
        FakeDevice("DH0000000000001", "Dehumidifier", "dehumidifier", copy.deepcopy(DEHUMIDIFIER_STATE)),
        FakeDevice(AC_ID, "Princess AC", "airconditioner", copy.deepcopy(AIRCONDITIONER_STATE)),
    ]
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(lambda: hass.states.get(PURIFIER) and hass.states.get(PURIFIER).state != STATE_UNAVAILABLE, hass)
    deprecated = [r.getMessage() for r in caplog.records if "deprecated" in r.getMessage().lower()]
    assert deprecated == []
