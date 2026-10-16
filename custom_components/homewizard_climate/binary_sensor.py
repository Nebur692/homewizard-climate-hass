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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeWizardClimateConfigEntry
from .const import TYPE_DEHUMIDIFIER, TYPE_PURIFIER
from .entity import HomeWizardClimateEntity


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


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeWizardClimateConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    connection = entry.runtime_data.connection
    async_add_entities(
        HomeWizardBinarySensor(connection, ident, description)
        for ident, dev in connection.devices.items()
        for description in BINARY_SENSORS
        if dev.device.type in description.types
    )


class HomeWizardBinarySensor(HomeWizardClimateEntity, BinarySensorEntity):
    entity_description: HomeWizardBinarySensorDescription

    def __init__(self, connection, identifier: str, description: HomeWizardBinarySensorDescription) -> None:
        super().__init__(connection, identifier)
        self.entity_description = description
        self._attr_unique_id = f"{identifier}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self._state)
