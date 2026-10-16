"""Child lock, on the devices whose state has one (heaters, dehumidifiers, air purifiers)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HomeWizardClimateConfigEntry
from .connection import HomeWizardClimateConnection
from .const import TYPE_DEHUMIDIFIER, TYPE_HEATER, TYPE_PURIFIER
from .entity import HomeWizardClimateEntity, async_setup_device_entities

CHILD_LOCK_TYPES = frozenset({TYPE_HEATER, TYPE_DEHUMIDIFIER, TYPE_PURIFIER})
CHILD_LOCK = SwitchEntityDescription(key="lock", translation_key="child_lock", entity_category=EntityCategory.CONFIG)

# Push entities: Home Assistant does not need to throttle their commands.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HomeWizardClimateConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    connection = entry.runtime_data.connection

    def build(ident: str) -> list[Entity]:
        if connection.devices[ident].device.type in CHILD_LOCK_TYPES:
            return [HomeWizardChildLock(connection, ident)]
        return []

    async_setup_device_entities(hass, entry, async_add_entities, build)


class HomeWizardChildLock(HomeWizardClimateEntity, SwitchEntity):
    entity_description = CHILD_LOCK

    def __init__(self, connection: HomeWizardClimateConnection, identifier: str) -> None:
        super().__init__(connection, identifier)
        self._attr_unique_id = f"{identifier}_lock"

    @property
    def is_on(self) -> bool | None:
        value = self._state.get("lock")
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set("lock", True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set("lock", False)
