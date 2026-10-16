"""Fans and air purifiers: native fan entities (speed, preset, oscillation), not climate ones."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import percentage_to_ranged_value, ranged_value_to_percentage

from . import HomeWizardClimateConfigEntry
from .connection import HomeWizardClimateConnection
from .const import (
    FAN_PRESETS,
    FAN_SPEED_RANGE,
    PURIFIER_LARGE_MODEL,
    PURIFIER_PRESETS,
    PURIFIER_SPEED_MAX,
    PURIFIER_SPEED_MAX_LARGE,
    TYPE_FAN,
    TYPE_PURIFIER,
)
from .entity import HomeWizardClimateEntity, async_setup_device_entities
from .migration import fan_unique_id

# Push entities: Home Assistant does not need to throttle their commands.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeWizardClimateConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    connection = entry.runtime_data.connection

    def build(ident: str) -> list[Entity]:
        kind = connection.devices[ident].device.type
        if kind == TYPE_FAN:
            return [HomeWizardFan(connection, ident)]
        if kind == TYPE_PURIFIER:
            return [HomeWizardPurifier(connection, ident)]
        return []

    async_setup_device_entities(hass, entry, async_add_entities, build)


class _SpeedFan(HomeWizardClimateEntity, FanEntity):
    """Power, a numeric speed from 1 up and a preset; subclasses say which fields."""

    _attr_name = None  # the device itself
    _speed_key = "speed"
    _presets: list[str] = []

    def __init__(self, connection: HomeWizardClimateConnection, identifier: str) -> None:
        super().__init__(connection, identifier)
        self._attr_unique_id = fan_unique_id(identifier)
        self._attr_preset_modes = self._presets

    @property
    def _speed_range(self) -> tuple[int, int]:
        return FAN_SPEED_RANGE

    @property
    def speed_count(self) -> int:
        low, high = self._speed_range
        return high - low + 1

    @property
    def is_on(self) -> bool | None:
        value = self._state.get("power_on")
        return None if value is None else bool(value)

    @property
    def percentage(self) -> int | None:
        if not self.is_on:
            return 0
        speed = self._state.get(self._speed_key)
        if not isinstance(speed, int) or isinstance(speed, bool):
            return None
        low, high = self._speed_range
        return ranged_value_to_percentage(self._speed_range, min(max(speed, low), high))

    @property
    def preset_mode(self) -> str | None:
        mode = self._state.get("mode")
        return mode if mode in self._presets else None

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any) -> None:
        if percentage == 0:
            # Turning on at 0 % means off, as fan.set_percentage does.
            await self.async_turn_off()
            return
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
        speed = math.ceil(percentage_to_ranged_value(self._speed_range, percentage))
        await self._async_set(self._speed_key, speed)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._async_set("mode", preset_mode)


class HomeWizardFan(_SpeedFan):
    """A HomeWizard Climate fan: speeds 1-3, presets and oscillation."""

    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.OSCILLATE
    )
    _attr_translation_key = "fan"
    _presets = FAN_PRESETS

    @property
    def oscillating(self) -> bool | None:
        value = self._state.get("oscillation")
        return None if value is None else bool(value)

    async def async_oscillate(self, oscillating: bool) -> None:
        await self._async_set("oscillation", oscillating)


class HomeWizardPurifier(_SpeedFan):
    """An air purifier: speeds 1-3 (1-4 on the large model) and manual, auto or sleep."""

    _attr_supported_features = (
        FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF | FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
    )
    _attr_translation_key = "purifier"
    _speed_key = "fan_speed"
    _presets = PURIFIER_PRESETS

    @property
    def _speed_range(self) -> tuple[int, int]:
        model = self._connection.devices[self._identifier].model or ""
        return (1, PURIFIER_SPEED_MAX_LARGE if PURIFIER_LARGE_MODEL in model else PURIFIER_SPEED_MAX)
