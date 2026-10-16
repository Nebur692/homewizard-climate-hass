"""The websocket: availability follows it, it reconnects alone, and a dead token asks to sign in."""

from __future__ import annotations

import pytest
from homeassistant.components.fan import DOMAIN as FAN_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.homewizard_climate import connection as connection_module
from custom_components.homewizard_climate.const import DOMAIN

from .conftest import make_entry, wait_for
from .fake_cloud import FakeCloud

BEDROOM = "fan.bedroom_fan"
BEDROOM_ID = "FAN000000000001"


def _state(hass: HomeAssistant) -> str | None:
    state = hass.states.get(BEDROOM)
    return state.state if state else None


async def _setup(hass: HomeAssistant):
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(lambda: _state(hass) == STATE_OFF, hass)
    return entry


async def test_one_websocket_for_the_whole_account(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass)
    assert cloud.hellos == 1
    subscribed = [m["device"] for m in cloud.received if m.get("type") == "subscribe_device"]
    assert sorted(subscribed) == ["FAN000000000001", "FAN000000000002"]


async def test_a_dropped_connection_makes_them_unavailable_and_then_comes_back(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    await _setup(hass)
    logins_before = cloud.logins
    await cloud.drop_connections()
    await wait_for(lambda: _state(hass) == STATE_UNAVAILABLE, hass)
    await wait_for(lambda: _state(hass) == STATE_OFF, hass)
    # It signs in again before reconnecting, so an expired token does not loop.
    assert cloud.logins == logins_before + 1
    assert cloud.hellos == 2


async def test_device_offline_in_the_cloud_is_unavailable(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass)
    await cloud.set_online(BEDROOM_ID, False)
    await wait_for(lambda: _state(hass) == STATE_UNAVAILABLE, hass)
    assert hass.states.get("fan.living_room_fan").state == STATE_OFF
    await cloud.set_online(BEDROOM_ID, True)
    await wait_for(lambda: _state(hass) == STATE_OFF, hass)


async def test_a_command_while_disconnected_says_so_with_its_code(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = await _setup(hass)
    # Down for good: every reconnect fails at sign-in with a server error.
    cloud.rest_status = 503
    await cloud.drop_connections()
    await wait_for(lambda: not entry.runtime_data.connection.connected, hass)
    # HA does not call services on unavailable entities; the race left is a command
    # that reaches the entity just as the socket drops. Call it as that command would.
    entity = hass.data["entity_components"][FAN_DOMAIN].get_entity(BEDROOM)
    with pytest.raises(HomeAssistantError) as raised:
        await entity.async_turn_on()
    assert raised.value.translation_key == "not_connected"
    assert raised.value.translation_placeholders["code"] == "028-003-080-005"
    assert raised.value.translation_placeholders["name"] == "Bedroom fan"
    # And the service call itself is skipped quietly, not sent into a dead socket.
    await hass.services.async_call(FAN_DOMAIN, "turn_on", {ATTR_ENTITY_ID: BEDROOM}, blocking=True)
    assert cloud.patches_sent() == []


async def test_token_rejected_by_the_websocket_signs_in_again(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass)
    cloud.ws_reject_token = True
    await cloud.drop_connections()
    await wait_for(lambda: cloud.hellos >= 2, hass)
    cloud.ws_reject_token = False
    await wait_for(lambda: _state(hass) == STATE_OFF, hass)
    assert cloud.logins >= 3


async def test_password_changed_while_running_asks_to_sign_in_again(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = await _setup(hass)
    cloud.rest_status = 401
    await cloud.drop_connections()
    await wait_for(
        lambda: any(f["context"]["source"] == SOURCE_REAUTH for f in hass.config_entries.flow.async_progress()), hass
    )
    flow = next(f for f in hass.config_entries.flow.async_progress() if f["handler"] == DOMAIN)
    assert flow["context"]["entry_id"] == entry.entry_id
    assert _state(hass) == STATE_UNAVAILABLE


async def test_a_link_that_stops_answering_pings_is_dropped_and_reconnected(
    hass: HomeAssistant, cloud: FakeCloud, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(connection_module, "WS_HEARTBEAT", 0.1)
    cloud.answer_pings = False
    await _setup(hass)
    # No pong: dropped, then a new hello (the new socket also ignores pings, so it keeps cycling).
    await wait_for(lambda: cloud.hellos >= 3, hass)
    cloud.answer_pings = True
    await cloud.drop_connections()
    await wait_for(lambda: _state(hass) == STATE_OFF, hass)
