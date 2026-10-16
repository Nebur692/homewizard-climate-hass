"""Problem and status flags: a purifier's filter, a dehumidifier's tank and defrosting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomeWizardClimateConfigEntry
from .connection import HomeWizardClimateConnection
from .const import TYPE_DEHUMIDIFIER, TYPE_PURIFIER
from .entity import HomeWizardClimateEntity, async_setup_device_entities


def _flag(key: str) -> Callable[[dict[str, Any]], bool | None]:
    def read(state: dict[str, Any]) -> bool | None:
        value = state.get(key)
        return value if isinstance(value, bool) else None

    return read


def _tank_full(state: dict[str, Any]) -> bool | None:
    faults = state.get("fault")
    return "water_full" in faults if isinstance(faults, list) else None


@dataclass(frozen=True, kw_only=True)
class HomeWizardBinarySensorDescription(BinarySensorEntityDescription):
    types: frozenset[str]
    value: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[HomeWizardBinarySensorDescription, ...] = (
    HomeWizardBinarySensorDescription(
        key="filter_check",
        translation_key="filter_check",
        device_class=BinarySensorDeviceClass.PROBLEM,
        types=frozenset({TYPE_PURIFIER}),
        value=_flag("filter_check"),
    ),
    HomeWizardBinarySensorDescription(
        key="tank_full",
        translation_key="tank_full",
        device_class=BinarySensorDeviceClass.PROBLEM,
        types=frozenset({TYPE_DEHUMIDIFIER}),
        value=_tank_full,
    ),
    HomeWizardBinarySensorDescription(
        key="defrosting",
        translation_key="defrosting",
        types=frozenset({TYPE_DEHUMIDIFIER}),
        value=_flag("defrosting"),
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
        return [HomeWizardBinarySensor(connection, ident, d) for d in BINARY_SENSORS if kind in d.types]

    async_setup_device_entities(hass, entry, async_add_entities, build)


class HomeWizardBinarySensor(HomeWizardClimateEntity, BinarySensorEntity):
    entity_description: HomeWizardBinarySensorDescription

    def __init__(
        self, connection: HomeWizardClimateConnection, identifier: str, description: HomeWizardBinarySensorDescription
    ) -> None:
        super().__init__(connection, identifier)
        self.entity_description = description
        self._attr_unique_id = f"{identifier}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self._state)
