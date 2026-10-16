"""Fans: a native fan entity (speed, preset, oscillation), not a climate one."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import percentage_to_ranged_value, ranged_value_to_percentage

from . import HomeWizardClimateConfigEntry
from .const import FAN_PRESETS, FAN_SPEED_RANGE, FAN_TYPES
from .entity import HomeWizardClimateEntity
from .migration import fan_unique_id


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeWizardClimateConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    connection = entry.runtime_data.connection
    async_add_entities(
        HomeWizardFan(connection, ident) for ident, dev in connection.devices.items() if dev.device.type in FAN_TYPES
    )


class HomeWizardFan(HomeWizardClimateEntity, FanEntity):
    """A HomeWizard Climate fan."""

    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.OSCILLATE
    )
    _attr_preset_modes = FAN_PRESETS
    _attr_speed_count = FAN_SPEED_RANGE[1] - FAN_SPEED_RANGE[0] + 1
    _attr_translation_key = "fan"

    def __init__(self, connection, identifier: str) -> None:
        super().__init__(connection, identifier)
        self._attr_unique_id = fan_unique_id(identifier)

    @property
    def is_on(self) -> bool | None:
        value = self._state.get("power_on")
        return None if value is None else bool(value)

    @property
    def percentage(self) -> int | None:
        if not self.is_on:
            return 0
        speed = self._state.get("speed")
        if not isinstance(speed, int) or isinstance(speed, bool):
            return None
        speed = min(max(speed, FAN_SPEED_RANGE[0]), FAN_SPEED_RANGE[1])
        return ranged_value_to_percentage(FAN_SPEED_RANGE, speed)

    @property
    def preset_mode(self) -> str | None:
        mode = self._state.get("mode")
        return mode if mode in FAN_PRESETS else None

    @property
    def oscillating(self) -> bool | None:
        value = self._state.get("oscillation")
        return None if value is None else bool(value)

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any) -> None:
        if not self.is_on:
            await self._async_set("power_on", True)
        if percentage:
            await self._async_set_speed(percentage)
        if preset_mode:
            await self._async_set("mode", preset_mode)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set("power_on", False)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        if not self.is_on:
            await self._async_set("power_on", True)
        await self._async_set_speed(percentage)

    async def _async_set_speed(self, percentage: int) -> None:
        speed = math.ceil(percentage_to_ranged_value(FAN_SPEED_RANGE, percentage))
        await self._async_set("speed", speed)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._async_set("mode", preset_mode)

    async def async_oscillate(self, oscillating: bool) -> None:
        await self._async_set("oscillation", oscillating)
