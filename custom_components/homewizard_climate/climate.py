"""Heaters, IR panels, dehumidifiers and air conditioners: climate entities.

Same behaviour and unique ids as the original integration, so existing entity
ids do not change, minus its crashes: no property raises NotImplementedError,
values the device does not report come out as unknown, and each command sends
one valid patch.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.climate import (
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_BOOST,
    PRESET_ECO,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeWizardClimateConfigEntry
from .const import (
    CLIMATE_TYPES,
    TYPE_DEHUMIDIFIER,
    TYPE_HEATER,
    TYPE_INFRAREDHEATER,
    legacy_unique_id,
)
from .entity import HomeWizardClimateEntity

# Seconds between power on and a mode change: the device ignores one sent straight after.
MODE_CHANGE_DELAY = 1
DEHUMIDIFIER_PRESETS = ["dehumidify", "fan", "laundry", "continuous", "automatic"]
# Dehumidifiers report their fan speed as text.
_TEXT_TO_FAN = {"low": FAN_LOW, "med": FAN_MEDIUM, "high": FAN_HIGH}
_FAN_TO_TEXT = {FAN_LOW: "low", FAN_MEDIUM: "med", FAN_HIGH: "high"}
# Heater fans use numbers, and the numbers depend on heating or cooling.
_FAN_TO_SPEED = {
    HVACMode.HEAT: {FAN_LOW: 1, FAN_MEDIUM: 2, FAN_HIGH: 4},
    HVACMode.COOL: {FAN_LOW: 1, FAN_MEDIUM: 4, FAN_HIGH: 8},
}


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeWizardClimateConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    connection = entry.runtime_data.connection
    async_add_entities(
        HomeWizardClimate(connection, ident)
        for ident, dev in connection.devices.items()
        if dev.device.type in CLIMATE_TYPES
    )


class HomeWizardClimate(HomeWizardClimateEntity, ClimateEntity):
    """A HomeWizard Climate heater, IR panel, dehumidifier or air conditioner."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp = 14
    _attr_max_temp = 30

    def __init__(self, connection, identifier: str) -> None:
        super().__init__(connection, identifier)
        self._type = connection.devices[identifier].device.type
        self._attr_unique_id = legacy_unique_id(self._type, identifier)
        if self._type == TYPE_DEHUMIDIFIER:
            self._attr_supported_features = (
                ClimateEntityFeature.TARGET_HUMIDITY
                | ClimateEntityFeature.PRESET_MODE
                | ClimateEntityFeature.FAN_MODE
                | ClimateEntityFeature.SWING_MODE
                | ClimateEntityFeature.TURN_OFF
                | ClimateEntityFeature.TURN_ON
            )
            self._attr_hvac_modes = [HVACMode.FAN_ONLY, HVACMode.OFF]
            self._attr_preset_modes = DEHUMIDIFIER_PRESETS
            self._attr_fan_modes = [FAN_LOW, FAN_HIGH]
            self._attr_swing_modes = [SWING_ON, SWING_OFF]
        elif self._type == TYPE_INFRAREDHEATER:
            self._attr_supported_features = (
                ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
            )
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        elif self._type == TYPE_HEATER:
            self._attr_supported_features = (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
                | ClimateEntityFeature.TURN_OFF
                | ClimateEntityFeature.TURN_ON
            )
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
            self._attr_preset_modes = [PRESET_ECO, PRESET_BOOST]
        else:  # heater fan, air conditioner
            self._attr_supported_features = (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.FAN_MODE
                | ClimateEntityFeature.SWING_MODE
                | ClimateEntityFeature.TURN_OFF
                | ClimateEntityFeature.TURN_ON
            )
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
            self._attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
            self._attr_swing_modes = [SWING_HORIZONTAL, SWING_OFF]

    # ---- state -----------------------------------------------------------

    def _number(self, key: str) -> float | None:
        value = self._state.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value

    @property
    def current_temperature(self) -> float | None:
        return self._number("current_temperature")

    @property
    def current_humidity(self) -> float | None:
        return self._number("current_humidity")

    @property
    def target_temperature(self) -> float | None:
        if self._type == TYPE_DEHUMIDIFIER:
            return None
        return self._number("target_temperature")

    @property
    def target_humidity(self) -> float | None:
        if self._type != TYPE_DEHUMIDIFIER:
            return None
        return self._number("target_humidity")

    @property
    def hvac_mode(self) -> HVACMode | None:
        power = self._state.get("power_on")
        if power is None:
            return None
        if not power:
            return HVACMode.OFF
        if self._type in (TYPE_INFRAREDHEATER, TYPE_HEATER):
            return HVACMode.HEAT
        if self._type == TYPE_DEHUMIDIFIER:
            return HVACMode.FAN_ONLY
        return HVACMode.HEAT if self._state.get("heater") else HVACMode.COOL

    @property
    def fan_mode(self) -> str | None:
        speed = self._state.get("fan_speed")
        if isinstance(speed, str):
            return _TEXT_TO_FAN.get(speed)
        mode = self.hvac_mode
        if mode in _FAN_TO_SPEED:
            for name, value in _FAN_TO_SPEED[mode].items():
                if speed == value:
                    return name
        return None

    @property
    def preset_mode(self) -> str | None:
        mode = self._state.get("mode")
        if self._type == TYPE_DEHUMIDIFIER:
            return mode if mode in DEHUMIDIFIER_PRESETS else None
        if self._type == TYPE_HEATER:
            return {"low": PRESET_ECO, "high": PRESET_BOOST}.get(mode)
        return None

    @property
    def swing_mode(self) -> str | None:
        if self._type == TYPE_DEHUMIDIFIER:
            value = self._state.get("swing")
            return None if value is None else (SWING_ON if value else SWING_OFF)
        value = self._state.get("oscillate")
        return None if value is None else (SWING_HORIZONTAL if value else SWING_OFF)

    # ---- commands --------------------------------------------------------

    async def async_turn_on(self) -> None:
        await self._async_set("power_on", True)

    async def async_turn_off(self) -> None:
        await self._async_set("power_on", False)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_set("power_on", False)
            return
        if not self._state.get("power_on"):
            await self._async_set("power_on", True)
            # The device ignores a mode change that arrives right on the heels of power on.
            await asyncio.sleep(MODE_CHANGE_DELAY)
        if self._type in (TYPE_INFRAREDHEATER, TYPE_HEATER, TYPE_DEHUMIDIFIER):
            return
        want_heater = hvac_mode == HVACMode.HEAT
        if bool(self._state.get("heater")) != want_heater:
            await self._async_set("heater", want_heater)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self._async_set("target_temperature", int(temperature))

    async def async_set_humidity(self, humidity: int) -> None:
        await self._async_set("target_humidity", int(humidity))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if self._type == TYPE_DEHUMIDIFIER:
            await self._async_set("fan_speed", _FAN_TO_TEXT[fan_mode])
            return
        mode = HVACMode.COOL if self.hvac_mode == HVACMode.COOL else HVACMode.HEAT
        await self._async_set("fan_speed", _FAN_TO_SPEED[mode][fan_mode])

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if self._type == TYPE_DEHUMIDIFIER:
            await self._async_set("swing", swing_mode == SWING_ON)
        else:
            await self._async_set("oscillate", swing_mode == SWING_HORIZONTAL)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if self._type == TYPE_HEATER:
            await self._async_set("mode", {PRESET_ECO: "low", PRESET_BOOST: "high"}[preset_mode])
        else:
            await self._async_set("mode", preset_mode)
