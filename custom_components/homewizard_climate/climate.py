"""Climate entities: heaters, IR panels, heater fans, dehumidifiers, air conditioners and air coolers.

Heaters, IR panels, heater fans and dehumidifiers keep the behaviour and unique
ids of the original integration, so existing entity ids do not change, minus its
crashes. Air conditioners and air coolers follow the fields and values of the
official HomeWizard Climate app: the original treated air conditioners as heater
fans, which sent the wrong values.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    PRESET_BOOST,
    PRESET_ECO,
    PRESET_NONE,
    PRESET_SLEEP,
    SWING_HORIZONTAL,
    SWING_OFF,
    SWING_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomeWizardClimateConfigEntry
from .connection import HomeWizardClimateConnection
from .const import (
    AIRCO_MAX_TEMP,
    AIRCO_MIN_TEMP,
    AIRCO_TWO_SPEED_MODEL,
    AIRCOOLER_PRESETS,
    HEATERFAN_COOL_SPEED_MAX,
    HEATERFAN_HEAT_SPEED_MAX,
    TYPE_AIRCONDITIONER,
    TYPE_AIRCOOLER,
    TYPE_DEHUMIDIFIER,
    TYPE_HEATER,
    TYPE_HEATERFAN,
    TYPE_INFRAREDHEATER,
    legacy_unique_id,
)
from .entity import HomeWizardClimateEntity, async_setup_device_entities

# Seconds between power on and a mode change: the device ignores one sent straight after.
MODE_CHANGE_DELAY = 1
DEHUMIDIFIER_PRESETS = ["dehumidify", "fan", "laundry", "continuous", "automatic"]
# Dehumidifiers, air conditioners and air coolers report their fan speed as text.
_TEXT_TO_FAN = {"low": FAN_LOW, "med": FAN_MEDIUM, "high": FAN_HIGH}
_FAN_TO_TEXT = {FAN_LOW: "low", FAN_MEDIUM: "med", FAN_HIGH: "high"}
# Heater fans use numbers: 1-4 while heating, 1-10 while cooling. These are the
# values the original integration sent; reading accepts the whole range.
_FAN_TO_SPEED = {
    HVACMode.HEAT: {FAN_LOW: 1, FAN_MEDIUM: 2, FAN_HIGH: 4},
    HVACMode.COOL: {FAN_LOW: 1, FAN_MEDIUM: 4, FAN_HIGH: 8},
}
_AIRCO_MODES = {"cool": HVACMode.COOL, "dehumidify": HVACMode.DRY, "fan": HVACMode.FAN_ONLY, "heat": HVACMode.HEAT}
_AIRCO_PRESET_SILENT = "silent"

# Push entities: Home Assistant does not need to throttle their commands.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeWizardClimateConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    connection = entry.runtime_data.connection

    def build(ident: str) -> list[Entity]:
        kind = connection.devices[ident].device.type
        if kind == TYPE_AIRCONDITIONER:
            return [HomeWizardAirConditioner(connection, ident)]
        if kind == TYPE_AIRCOOLER:
            return [HomeWizardAirCooler(connection, ident)]
        if kind in (TYPE_HEATERFAN, TYPE_INFRAREDHEATER, TYPE_HEATER, TYPE_DEHUMIDIFIER):
            return [HomeWizardClimate(connection, ident)]
        return []

    async_setup_device_entities(hass, entry, async_add_entities, build)


class _Base(HomeWizardClimateEntity, ClimateEntity):
    """What every climate device here shares."""

    _attr_name = None  # the device itself
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1

    def __init__(self, connection: HomeWizardClimateConnection, identifier: str) -> None:
        super().__init__(connection, identifier)
        self._type = connection.devices[identifier].device.type
        self._attr_unique_id = legacy_unique_id(self._type, identifier)

    def _number(self, key: str) -> float | None:
        value = self._state.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value

    async def _async_power_on_first(self) -> None:
        if not self._state.get("power_on"):
            await self._async_set("power_on", True)
            await asyncio.sleep(MODE_CHANGE_DELAY)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        # HA may send the HVAC mode in the same call: apply it first, and skip the
        # temperature when the call switches the device off.
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        if hvac_mode is not None:
            await self.async_set_hvac_mode(hvac_mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None and hvac_mode != HVACMode.OFF:
            # HA has already converted °F to °C; round, do not truncate (21.99 is 22, not 21).
            await self._async_set("target_temperature", round(temperature))

    async def async_turn_on(self) -> None:
        await self._async_set("power_on", True)

    async def async_turn_off(self) -> None:
        await self._async_set("power_on", False)


class HomeWizardClimate(_Base):
    """A heater fan, glass panel heater, IR panel or dehumidifier."""

    _attr_min_temp = 14
    _attr_max_temp = 30

    def __init__(self, connection: HomeWizardClimateConnection, identifier: str) -> None:
        super().__init__(connection, identifier)
        if self._type == TYPE_DEHUMIDIFIER:
            self._attr_translation_key = "dehumidifier"
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
        else:  # heater fan
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
        if isinstance(speed, bool) or not isinstance(speed, int) or speed < 1:
            return None
        # Heater fans: split the device's whole range in three.
        # The scale follows the heater flag, not the HVAC mode: it still applies while off.
        top = HEATERFAN_HEAT_SPEED_MAX if self._state.get("heater") else HEATERFAN_COOL_SPEED_MAX
        if speed > top:
            return None
        third = top / 3
        return FAN_LOW if speed <= third else FAN_MEDIUM if speed <= 2 * third else FAN_HIGH

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

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_set("power_on", False)
            return
        await self._async_power_on_first()
        if self._type in (TYPE_INFRAREDHEATER, TYPE_HEATER, TYPE_DEHUMIDIFIER):
            return
        want_heater = hvac_mode == HVACMode.HEAT
        if bool(self._state.get("heater")) != want_heater:
            await self._async_set("heater", want_heater)

    async def async_set_humidity(self, humidity: int) -> None:
        await self._async_set("target_humidity", int(humidity))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if self._type == TYPE_DEHUMIDIFIER:
            await self._async_set("fan_speed", _FAN_TO_TEXT[fan_mode])
            return
        mode = HVACMode.HEAT if self._state.get("heater") else HVACMode.COOL
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


class HomeWizardAirConditioner(_Base):
    """A portable air conditioner (PS-A007, PS-A018): cool, dry, fan only or heat."""

    _attr_translation_key = "airconditioner"
    _attr_min_temp = AIRCO_MIN_TEMP
    _attr_max_temp = AIRCO_MAX_TEMP
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_NONE, PRESET_SLEEP, _AIRCO_PRESET_SILENT]
    _attr_swing_modes = [SWING_ON, SWING_OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    @property
    def fan_modes(self) -> list[str]:
        model = self._connection.devices[self._identifier].model or ""
        if AIRCO_TWO_SPEED_MODEL in model:
            return [FAN_LOW, FAN_HIGH]
        return [FAN_LOW, FAN_MEDIUM, FAN_HIGH]

    @property
    def current_temperature(self) -> float | None:
        return self._number("current_temperature")

    @property
    def target_temperature(self) -> float | None:
        return self._number("target_temperature")

    @property
    def hvac_mode(self) -> HVACMode | None:
        power = self._state.get("power_on")
        if power is None:
            return None
        if not power:
            return HVACMode.OFF
        return _AIRCO_MODES.get(self._state.get("mode"))

    @property
    def fan_mode(self) -> str | None:
        speed = self._state.get("fan_speed")
        return _TEXT_TO_FAN.get(speed) if isinstance(speed, str) else None

    @property
    def swing_mode(self) -> str | None:
        value = self._state.get("oscillate")
        return None if value is None else (SWING_ON if value else SWING_OFF)

    @property
    def preset_mode(self) -> str | None:
        if self._state.get("sleep"):
            return PRESET_SLEEP
        if self._state.get("silent"):
            return _AIRCO_PRESET_SILENT
        if "sleep" in self._state or "silent" in self._state:
            return PRESET_NONE
        return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_set("power_on", False)
            return
        await self._async_power_on_first()
        wanted = next(key for key, value in _AIRCO_MODES.items() if value == hvac_mode)
        if self._state.get("mode") != wanted:
            await self._async_set("mode", wanted)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._async_set("fan_speed", _FAN_TO_TEXT[fan_mode])

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._async_set("oscillate", swing_mode == SWING_ON)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        sleep = preset_mode == PRESET_SLEEP
        silent = preset_mode == _AIRCO_PRESET_SILENT
        if bool(self._state.get("sleep")) != sleep:
            await self._async_set("sleep", sleep)
        if bool(self._state.get("silent")) != silent:
            await self._async_set("silent", silent)


class HomeWizardAirCooler(_Base):
    """An evaporative air cooler: fan only, or fan with cooling."""

    _attr_translation_key = "aircooler"
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY, HVACMode.COOL]
    _attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
    _attr_preset_modes = AIRCOOLER_PRESETS
    _attr_swing_modes = [SWING_ON, SWING_OFF]
    _attr_supported_features = (
        ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    @property
    def hvac_mode(self) -> HVACMode | None:
        power = self._state.get("power_on")
        if power is None:
            return None
        if not power:
            return HVACMode.OFF
        return HVACMode.COOL if self._state.get("cool") else HVACMode.FAN_ONLY

    @property
    def fan_mode(self) -> str | None:
        speed = self._state.get("fan_speed")
        return _TEXT_TO_FAN.get(speed) if isinstance(speed, str) else None

    @property
    def preset_mode(self) -> str | None:
        mode = self._state.get("mode")
        return mode if mode in AIRCOOLER_PRESETS else None

    @property
    def swing_mode(self) -> str | None:
        value = self._state.get("oscillate")
        return None if value is None else (SWING_ON if value else SWING_OFF)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._async_set("power_on", False)
            return
        await self._async_power_on_first()
        cool = hvac_mode == HVACMode.COOL
        if bool(self._state.get("cool")) != cool:
            await self._async_set("cool", cool)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._async_set("fan_speed", _FAN_TO_TEXT[fan_mode])

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._async_set("oscillate", swing_mode == SWING_ON)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._async_set("mode", preset_mode)
