"""Fans are native fan entities, driven through the cloud websocket."""

from __future__ import annotations

import pytest
from homeassistant.components.fan import (
    ATTR_OSCILLATING,
    ATTR_PERCENTAGE,
    ATTR_PRESET_MODE,
)
from homeassistant.components.fan import (
    DOMAIN as FAN_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from .conftest import make_entry, wait_for
from .fake_cloud import FakeCloud

BEDROOM = "fan.bedroom_fan"
LIVING = "fan.living_room_fan"
BEDROOM_ID = "FAN000000000001"


async def _setup(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(lambda: hass.states.get(BEDROOM) and hass.states.get(BEDROOM).state != STATE_UNAVAILABLE, hass)


async def _call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(FAN_DOMAIN, service, {ATTR_ENTITY_ID: BEDROOM, **data}, blocking=True)


async def test_both_fans_appear_as_fans_with_the_cloud_state(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass, cloud)
    for entity_id in (BEDROOM, LIVING):
        state = hass.states.get(entity_id)
        assert state.state == STATE_OFF
        assert state.attributes[ATTR_PRESET_MODE] == "normal"
        assert state.attributes[ATTR_OSCILLATING] is False
        assert state.attributes["preset_modes"] == ["normal", "sleep", "natural"]
    assert hass.states.async_entity_ids("climate") == []


async def test_turn_on_at_full_speed_sends_power_then_speed(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass, cloud)
    await _call(hass, "turn_on", **{ATTR_PERCENTAGE: 100})
    await wait_for(lambda: hass.states.get(BEDROOM).attributes.get(ATTR_PERCENTAGE) == 100, hass)
    assert cloud.patches_sent() == [(BEDROOM_ID, "/state/power_on", True), (BEDROOM_ID, "/state/speed", 3)]
    assert hass.states.get(BEDROOM).state == STATE_ON


@pytest.mark.parametrize(("percentage", "speed"), [(1, 1), (33, 1), (34, 2), (66, 2), (67, 3), (100, 3)])
async def test_percentage_maps_to_the_three_speeds(
    hass: HomeAssistant, cloud: FakeCloud, percentage: int, speed: int
) -> None:
    await _setup(hass, cloud)
    await _call(hass, "set_percentage", **{ATTR_PERCENTAGE: percentage})
    await wait_for(
        lambda: (
            cloud.device(BEDROOM_ID).state["power_on"] is True
            and cloud.device(BEDROOM_ID).state["speed"] == speed
            and (BEDROOM_ID, "/state/speed", speed) in cloud.patches_sent()
        ),
        hass,
    )
    assert cloud.device(BEDROOM_ID).state["power_on"] is True


async def test_speed_reported_by_the_cloud_shows_as_percentage(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass, cloud)
    cloud.device(BEDROOM_ID).state.update(power_on=True, speed=2)
    await cloud.push_full(BEDROOM_ID)
    await wait_for(lambda: hass.states.get(BEDROOM).attributes.get(ATTR_PERCENTAGE) == 66, hass)


async def test_percentage_zero_turns_it_off(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass, cloud)
    await _call(hass, "turn_on")
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_ON, hass)
    await _call(hass, "set_percentage", **{ATTR_PERCENTAGE: 0})
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_OFF, hass)
    assert cloud.patches_sent()[-1] == (BEDROOM_ID, "/state/power_on", False)


async def test_preset_and_oscillation(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass, cloud)
    await _call(hass, "set_preset_mode", **{ATTR_PRESET_MODE: "natural"})
    await _call(hass, "oscillate", **{ATTR_OSCILLATING: True})
    await wait_for(lambda: hass.states.get(BEDROOM).attributes[ATTR_OSCILLATING] is True, hass)
    assert hass.states.get(BEDROOM).attributes[ATTR_PRESET_MODE] == "natural"
    assert (BEDROOM_ID, "/state/oscillation", True) in cloud.patches_sent()


async def test_turn_on_when_already_on_does_not_resend_power(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass, cloud)
    cloud.device(BEDROOM_ID).state["power_on"] = True
    await cloud.push_full(BEDROOM_ID)
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_ON, hass)
    await _call(hass, "turn_on", **{ATTR_PRESET_MODE: "sleep"})
    await wait_for(lambda: cloud.device(BEDROOM_ID).state["mode"] == "sleep", hass)
    assert cloud.patches_sent() == [(BEDROOM_ID, "/state/mode", "sleep")]


async def test_unknown_preset_from_the_cloud_is_unknown_not_an_error(hass: HomeAssistant, cloud: FakeCloud) -> None:
    await _setup(hass, cloud)
    cloud.device(BEDROOM_ID).state["mode"] = "turbo"
    await cloud.push_full(BEDROOM_ID)
    await wait_for(lambda: hass.states.get(BEDROOM).attributes.get(ATTR_PRESET_MODE) is None, hass)
