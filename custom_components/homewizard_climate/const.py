"""Constants for the HomeWizard Climate integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "homewizard_climate"

API_LOGIN_URL: Final = "https://api.homewizardeasyonline.com/v1/auth/login"
API_DEVICES_URL: Final = "https://api.homewizardeasyonline.com/v1/auth/devices"
WS_URL: Final = "wss://app-ws.homewizard.com/ws"
# The hello message names the client; the cloud only checks the token.
WS_SOURCE: Final = "https://github.com/Nebur692/homewizard-climate-hass"
WS_COMPATIBILITY: Final = 4

# Seconds. Every REST request and the websocket handshake give up after this.
REQUEST_TIMEOUT: Final = 15
# Ping the cloud so a dead connection is noticed within a minute.
WS_HEARTBEAT: Final = 30
# Reconnect backoff: 5 s, doubling, never more than 5 minutes.
RECONNECT_MIN: Final = 5
RECONNECT_MAX: Final = 300

# Device types the cloud reports, as strings. Fans get a fan entity; the rest
# keep the climate entity they always had.
TYPE_FAN: Final = "fan"
TYPE_HEATERFAN: Final = "heaterfan"
TYPE_INFRAREDHEATER: Final = "infraredheater"
TYPE_HEATER: Final = "heater"
TYPE_DEHUMIDIFIER: Final = "dehumidifier"
TYPE_AIRCONDITIONER: Final = "airconditioner"

FAN_TYPES: Final = frozenset({TYPE_FAN})
CLIMATE_TYPES: Final = frozenset(
    {TYPE_HEATERFAN, TYPE_INFRAREDHEATER, TYPE_HEATER, TYPE_DEHUMIDIFIER, TYPE_AIRCONDITIONER}
)
SUPPORTED_TYPES: Final = FAN_TYPES | CLIMATE_TYPES

# Fan presets, as the cloud names them.
FAN_PRESETS: Final = ["normal", "sleep", "natural"]
FAN_SPEED_RANGE: Final = (1, 3)


def legacy_unique_id(device_type: str, identifier: str) -> str:
    """Unique id used by the original integration (str() of its enum member).

    Climate entities keep it, so nobody's entity ids change. Fans used it too
    and are migrated from it.
    """
    return f"HomeWizardClimateDeviceType.{device_type.upper()}_{identifier}"
