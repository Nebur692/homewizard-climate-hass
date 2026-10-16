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

# Device types the cloud reports, as strings. Fans and air purifiers get a fan
# entity; the rest keep (or get) a climate entity.
TYPE_FAN: Final = "fan"
TYPE_HEATERFAN: Final = "heaterfan"
TYPE_INFRAREDHEATER: Final = "infraredheater"
TYPE_HEATER: Final = "heater"
TYPE_DEHUMIDIFIER: Final = "dehumidifier"
TYPE_AIRCONDITIONER: Final = "airconditioner"
TYPE_AIRCOOLER: Final = "aircooler"
TYPE_PURIFIER: Final = "airpurifier"

FAN_TYPES: Final = frozenset({TYPE_FAN, TYPE_PURIFIER})
CLIMATE_TYPES: Final = frozenset(
    {TYPE_HEATERFAN, TYPE_INFRAREDHEATER, TYPE_HEATER, TYPE_DEHUMIDIFIER, TYPE_AIRCONDITIONER, TYPE_AIRCOOLER}
)
SUPPORTED_TYPES: Final = FAN_TYPES | CLIMATE_TYPES

# Field names, values and ranges below come from the official HomeWizard Climate
# app (nl.homewizard.android.climate), which is what the devices are built to talk to.

# Fan presets, as the cloud names them.
FAN_PRESETS: Final = ["normal", "sleep", "natural"]
FAN_SPEED_RANGE: Final = (1, 3)

# Air purifiers: speed 1-3, 1-4 on the large model.
PURIFIER_PRESETS: Final = ["manual", "auto", "sleep"]
PURIFIER_LARGE_MODEL: Final = "HWC-6089"
PURIFIER_SPEED_MAX: Final = 3
PURIFIER_SPEED_MAX_LARGE: Final = 4
PURIFIER_AIR_QUALITY: Final = ["excellent", "good", "bad", "polluted"]

# Portable air conditioners. The PS-A007 (Tristar) has two fan speeds, the PS-A018 (Princess) three.
AIRCO_TWO_SPEED_MODEL: Final = "PS-A007"
AIRCO_MIN_TEMP: Final = 16
AIRCO_MAX_TEMP: Final = 31

# Air coolers.
AIRCOOLER_PRESETS: Final = ["manual", "sleep", "natural"]

# Heater fans: fan speed 1-4 while heating, 1-10 while cooling.
HEATERFAN_HEAT_SPEED_MAX: Final = 4
HEATERFAN_COOL_SPEED_MAX: Final = 10


def legacy_unique_id(device_type: str, identifier: str) -> str:
    """Unique id used by the original integration (str() of its enum member).

    Climate entities keep it, so nobody's entity ids change. Fans used it too
    and are migrated from it.
    """
    return f"HomeWizardClimateDeviceType.{device_type.upper()}_{identifier}"
