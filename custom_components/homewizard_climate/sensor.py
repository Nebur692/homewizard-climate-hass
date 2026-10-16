"""Air purifier readings: air quality, PM2.5, temperature, humidity and filter life."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfDensity, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomeWizardClimateConfigEntry
from .connection import HomeWizardClimateConnection
from .const import PURIFIER_AIR_QUALITY, TYPE_PURIFIER
from .entity import HomeWizardClimateEntity, async_setup_device_entities


def _number(key: str) -> Callable[[dict[str, Any]], float | None]:
    def read(state: dict[str, Any]) -> float | None:
        value = state.get(key)
        return None if isinstance(value, bool) or not isinstance(value, int | float) else value

    return read


def _air_quality(state: dict[str, Any]) -> str | None:
    value = state.get("air_quality")
    return value if value in PURIFIER_AIR_QUALITY else None


@dataclass(frozen=True, kw_only=True)
class HomeWizardSensorDescription(SensorEntityDescription):
    types: frozenset[str]
    value: Callable[[dict[str, Any]], Any]


SENSORS: tuple[HomeWizardSensorDescription, ...] = (
    HomeWizardSensorDescription(
        key="air_quality",
        translation_key="air_quality",
        device_class=SensorDeviceClass.ENUM,
        options=PURIFIER_AIR_QUALITY,
        types=frozenset({TYPE_PURIFIER}),
        value=_air_quality,
    ),
    HomeWizardSensorDescription(
        key="pm2_5_level",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UnitOfDensity.MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        types=frozenset({TYPE_PURIFIER}),
        value=_number("pm2_5_level"),
    ),
    HomeWizardSensorDescription(
        key="current_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        types=frozenset({TYPE_PURIFIER}),
        value=_number("current_temperature"),
    ),
    HomeWizardSensorDescription(
        key="current_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        types=frozenset({TYPE_PURIFIER}),
        value=_number("current_humidity"),
    ),
    HomeWizardSensorDescription(
        key="filter_life_remaining",
        translation_key="filter_life_remaining",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        types=frozenset({TYPE_PURIFIER}),
        value=_number("filter_life_remaining"),
    ),
)

# Push entities: Home Assistant does not need to throttle their commands.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeWizardClimateConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    connection = entry.runtime_data.connection

    def build(ident: str) -> list[Entity]:
        kind = connection.devices[ident].device.type
        return [HomeWizardSensor(connection, ident, d) for d in SENSORS if kind in d.types]

    async_setup_device_entities(hass, entry, async_add_entities, build)


class HomeWizardSensor(HomeWizardClimateEntity, SensorEntity):
    entity_description: HomeWizardSensorDescription

    def __init__(
        self, connection: HomeWizardClimateConnection, identifier: str, description: HomeWizardSensorDescription
    ) -> None:
        super().__init__(connection, identifier)
        self.entity_description = description
        self._attr_unique_id = f"{identifier}_{description.key}"

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self._state)
