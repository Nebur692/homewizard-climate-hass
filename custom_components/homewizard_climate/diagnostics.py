"""Diagnostics download: connection and device states, with no credentials."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import HomeWizardClimateConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "token", "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HomeWizardClimateConfigEntry
) -> dict[str, Any]:
    connection = entry.runtime_data.connection
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "connected": connection.connected,
        "reconnects": connection.reconnects,
        "next_reconnect_delay": connection.next_delay,
        "devices": [
            {
                "type": dev.device.type,
                "model": dev.model,
                "version": dev.version,
                "online": dev.online,
                "received": dev.received,
                "state": dev.state,
            }
            for dev in connection.devices.values()
        ],
    }
