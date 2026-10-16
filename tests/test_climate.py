"""Heaters and dehumidifiers keep their climate entity, now without crashes."""

from __future__ import annotations

import copy

import pytest
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HUMIDITY,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.homewizard_climate.const import DOMAIN, legacy_unique_id

from .conftest import make_entry, wait_for
from .fake_cloud import DEHUMIDIFIER_STATE, HEATER_STATE, HEATERFAN_STATE, FakeCloud, FakeDevice

HEATERFAN = "climate.study_heater"
HEATER = "climate.glass_panel"
DEHUM = "climate.laundry_dehumidifier"


@pytest.fixture
async def climates(hass: HomeAssistant, cloud: FakeCloud, monkeypatch: pytest.MonkeyPatch) -> FakeCloud:
    cloud.devices = [
        FakeDevice("HF0000000000001", "Study heater", "heaterfan", copy.deepcopy(HEATERFAN_STATE)),
        FakeDevice("HT0000000000001", "Glass panel", "heater", copy.deepcopy(HEATER_STATE)),
        FakeDevice("DH0000000000001", "Laundry dehumidifier", "dehumidifier", copy.deepcopy(DEHUMIDIFIER_STATE)),
    ]
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(
        lambda: all(
            hass.states.get(e) and hass.states.get(e).state != STATE_UNAVAILABLE for e in (HEATERFAN, HEATER, DEHUM)
        ),
        hass,
    )
    return cloud


async def _call(hass: HomeAssistant, service: str, entity_id: str, **data) -> None:
    await hass.services.async_call(CLIMATE_DOMAIN, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True)


async def test_states_read_from_the_cloud(hass: HomeAssistant, climates: FakeCloud) -> None:
    heaterfan = hass.states.get(HEATERFAN)
    assert heaterfan.state == HVACMode.HEAT
    assert heaterfan.attributes["current_temperature"] == 19
    assert heaterfan.attributes[ATTR_TEMPERATURE] == 22
    assert heaterfan.attributes[ATTR_FAN_MODE] == "medium"  # 2 while heating
    heater = hass.states.get(HEATER)
    assert heater.state == HVACMode.OFF
    assert heater.attributes[ATTR_PRESET_MODE] == "eco"
    dehum = hass.states.get(DEHUM)
    assert dehum.state == HVACMode.FAN_ONLY
    assert dehum.attributes[ATTR_PRESET_MODE] == "laundry"
    assert dehum.attributes[ATTR_FAN_MODE] == "high"
    assert dehum.attributes[ATTR_HUMIDITY] == 50


async def test_unique_ids_stay_the_ones_of_the_original_integration(hass: HomeAssistant, climates: FakeCloud) -> None:
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(HEATERFAN).unique_id == legacy_unique_id("heaterfan", "HF0000000000001")
    assert ent_reg.async_get(HEATERFAN).unique_id == "HomeWizardClimateDeviceType.HEATERFAN_HF0000000000001"
    assert ent_reg.async_get_entity_id(CLIMATE_DOMAIN, DOMAIN, "HomeWizardClimateDeviceType.HEATER_HT0000000000001")


async def test_heater_fan_switches_to_cooling_and_maps_fan_speeds(hass: HomeAssistant, climates: FakeCloud) -> None:
    await _call(hass, "set_hvac_mode", HEATERFAN, **{ATTR_HVAC_MODE: HVACMode.COOL})
    await wait_for(lambda: hass.states.get(HEATERFAN).state == HVACMode.COOL, hass)
    await _call(hass, "set_fan_mode", HEATERFAN, **{ATTR_FAN_MODE: "high"})
    await wait_for(lambda: climates.device("HF0000000000001").state["fan_speed"] == 8, hass)
    assert hass.states.get(HEATERFAN).attributes[ATTR_FAN_MODE] == "high"


async def test_heater_preset_and_temperature(hass: HomeAssistant, climates: FakeCloud) -> None:
    await _call(hass, "set_preset_mode", HEATER, **{ATTR_PRESET_MODE: "boost"})
    await _call(hass, "set_temperature", HEATER, **{ATTR_TEMPERATURE: 24})
    await wait_for(lambda: hass.states.get(HEATER).attributes[ATTR_TEMPERATURE] == 24, hass)
    assert climates.device("HT0000000000001").state["mode"] == "high"


async def test_heater_turned_on_does_not_send_a_heater_flag_it_does_not_have(
    hass: HomeAssistant, climates: FakeCloud, monkeypatch: pytest.MonkeyPatch
) -> None:
    from custom_components.homewizard_climate import climate as climate_module

    monkeypatch.setattr(climate_module, "MODE_CHANGE_DELAY", 0)
    await _call(hass, "set_hvac_mode", HEATER, **{ATTR_HVAC_MODE: HVACMode.HEAT})
    await wait_for(lambda: hass.states.get(HEATER).state == HVACMode.HEAT, hass)
    assert [p for p in climates.patches_sent() if p[0] == "HT0000000000001"] == [
        ("HT0000000000001", "/state/power_on", True)
    ]


async def test_dehumidifier_fan_speed_is_sent_once_as_text(hass: HomeAssistant, climates: FakeCloud) -> None:
    await _call(hass, "set_fan_mode", DEHUM, **{ATTR_FAN_MODE: "low"})
    await _call(hass, "set_swing_mode", DEHUM, **{ATTR_SWING_MODE: "on"})
    await _call(hass, "set_humidity", DEHUM, **{ATTR_HUMIDITY: 45})
    await wait_for(lambda: climates.device("DH0000000000001").state["target_humidity"] == 45, hass)
    sent = [p for p in climates.patches_sent() if p[0] == "DH0000000000001"]
    assert sent == [
        ("DH0000000000001", "/state/fan_speed", "low"),
        ("DH0000000000001", "/state/swing", True),
        ("DH0000000000001", "/state/target_humidity", 45),
    ]


async def test_a_device_reporting_almost_nothing_does_not_crash(
    hass: HomeAssistant, cloud: FakeCloud, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The original raised NotImplementedError from preset_mode and int() on "high" (upstream #30, #33, #34).
    cloud.devices = [FakeDevice("HF0000000000009", "Odd heater", "heaterfan", {"power_on": True, "fan_speed": "high"})]
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(
        lambda: (
            hass.states.get("climate.odd_heater") and hass.states.get("climate.odd_heater").state != STATE_UNAVAILABLE
        ),
        hass,
    )
    state = hass.states.get("climate.odd_heater")
    assert state.state == HVACMode.COOL
    assert state.attributes[ATTR_FAN_MODE] == "high"
    assert state.attributes["current_temperature"] is None
