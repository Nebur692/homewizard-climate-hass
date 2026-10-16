"""The HomeWizard Climate integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import burburito
from .api import HomeWizardAuthError, HomeWizardClimateApi, HomeWizardConnectionError, HomeWizardResponseError
from .connection import HomeWizardClimateConnection
from .const import DOMAIN, SUPPORTED_TYPES
from .migration import async_migrate_fans, async_track_old_references

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.FAN, Platform.SENSOR, Platform.SWITCH]
UNSUPPORTED_ISSUE_PREFIX = "unsupported_type_"


@dataclass(slots=True)
class HomeWizardClimateData:
    api: HomeWizardClimateApi
    connection: HomeWizardClimateConnection


type HomeWizardClimateConfigEntry = ConfigEntry[HomeWizardClimateData]


async def async_setup_entry(hass: HomeAssistant, entry: HomeWizardClimateConfigEntry) -> bool:
    """Sign in, list the devices and start the websocket."""

    session = async_get_clientsession(hass)
    api = HomeWizardClimateApi(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    try:
        await api.async_login()
        devices = await api.async_get_devices()
    except HomeWizardAuthError as err:
        raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="invalid_auth") from err
    except (HomeWizardConnectionError, HomeWizardResponseError) as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={
                "error": str(err),
                **burburito.footer("conexion/arrancar-servicio/sin-conexion", hass.config.language),
            },
        ) from err

    # Entries made by the original integration have no unique id: give them the account.
    if entry.unique_id is None:
        unique_id = entry.data[CONF_USERNAME].strip().lower()
        if not any(e.unique_id == unique_id for e in hass.config_entries.async_entries(DOMAIN)):
            hass.config_entries.async_update_entry(entry, unique_id=unique_id)

    _async_report_unsupported(hass, [d.type for d in devices if d.type not in SUPPORTED_TYPES])
    supported = [d for d in devices if d.type in SUPPORTED_TYPES]

    @callback
    def update_device_info(identifier: str) -> None:
        """Show the hardware model and firmware version on the device page once the cloud sends them."""
        dev = entry.runtime_data.connection.devices[identifier]
        dev_reg = dr.async_get(hass)
        if device := dev_reg.async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id):
            dev_reg.async_update_device(device.id, model_id=dev.model, sw_version=dev.version)

    connection = HomeWizardClimateConnection(
        session,
        api,
        supported,
        on_auth_failed=lambda: entry.async_start_reauth(hass),
        on_device_info=update_device_info,
    )
    entry.runtime_data = HomeWizardClimateData(api, connection)

    async_migrate_fans(hass, entry)
    async_track_old_references(hass, entry)

    entry.async_create_background_task(hass, connection.run(), f"{DOMAIN} websocket {entry.title}")
    entry.async_on_unload(connection.stop)

    async def _close_on_stop(_event: Event) -> None:
        await connection.stop()

    # Close the socket cleanly when Home Assistant stops, not only on unload.
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _close_on_stop))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeWizardClimateConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _async_report_unsupported(hass: HomeAssistant, types: list[str]) -> None:
    """One Repairs issue per unknown device type, so nobody wonders where a device went."""
    present = set(types)
    for issue in list(ir.async_get(hass).issues.values()):
        if (
            issue.domain == DOMAIN
            and issue.issue_id.startswith(UNSUPPORTED_ISSUE_PREFIX)
            and issue.issue_id.removeprefix(UNSUPPORTED_ISSUE_PREFIX) not in present
        ):
            ir.async_delete_issue(hass, DOMAIN, issue.issue_id)
    for device_type in sorted(present):
        _LOGGER.warning("Device type %r is not supported yet; it is left out", device_type)
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{UNSUPPORTED_ISSUE_PREFIX}{device_type}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="unsupported_type",
            translation_placeholders={
                "type": device_type,
                "url": "https://github.com/Nebur692/homewizard-climate-hass/issues",
                **burburito.footer("conexion/arrancar-servicio/no-implementado", hass.config.language),
            },
        )
