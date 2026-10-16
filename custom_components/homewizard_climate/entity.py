"""Base entity: one per device, fed by the shared websocket."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import burburito
from .connection import HomeWizardClimateConnection, NotConnectedError
from .const import DOMAIN

if TYPE_CHECKING:
    from . import HomeWizardClimateConfigEntry


class HomeWizardClimateEntity(Entity):
    """Pushed by the cloud; unavailable whenever the cloud or the device is not reachable."""

    _attr_has_entity_name = True
    # Sensors and switches take their name from their description; the main entity sets None.
    _attr_should_poll = False

    def __init__(self, connection: HomeWizardClimateConnection, identifier: str) -> None:
        self._connection = connection
        self._identifier = identifier
        dev = connection.devices[identifier]
        device = dev.device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=device.name,
            manufacturer="HomeWizard",
            model=device.type.capitalize(),
            model_id=dev.model,
            sw_version=dev.version,
        )

    @property
    def _state(self) -> dict[str, Any]:
        return self._connection.devices[self._identifier].state

    @property
    def available(self) -> bool:
        return self._connection.is_available(self._identifier)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._connection.add_listener(self._identifier, self.async_write_ha_state))

    async def _async_set(self, key: str, value: Any) -> None:
        try:
            await self._connection.async_set(self._identifier, key, value)
        except NotConnectedError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_connected",
                translation_placeholders={
                    "name": self._connection.devices[self._identifier].device.name,
                    **burburito.footer("mando/accionar-dispositivo/conexion-cortada", self.hass.config.language),
                },
            ) from err


def signal_new_devices(entry_id: str) -> str:
    """Dispatcher signal sent with the identifiers of devices added to the account."""
    return f"{DOMAIN}_new_devices_{entry_id}"


@callback
def async_setup_device_entities(
    hass: HomeAssistant,
    entry: HomeWizardClimateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[[str], list[Entity]],
) -> None:
    """Add a platform's entities for every device now, and for devices added to the account later."""
    connection = entry.runtime_data.connection
    async_add_entities([entity for ident in list(connection.devices) for entity in build(ident)])

    @callback
    def add_new(identifiers: list[str]) -> None:
        async_add_entities([entity for ident in identifiers for entity in build(ident)])

    entry.async_on_unload(async_dispatcher_connect(hass, signal_new_devices(entry.entry_id), add_new))
