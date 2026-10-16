"""REST side of the HomeWizard Climate cloud: sign in and list the devices.

The protocol comes from homewizard-climate-websocket by mepla (MIT); this is an
async rewrite on Home Assistant's shared aiohttp session, with a timeout on
every request so a cloud that does not answer can never hold up startup.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import API_DEVICES_URL, API_LOGIN_URL, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class HomeWizardError(Exception):
    """Base error for the HomeWizard Climate cloud."""


class HomeWizardAuthError(HomeWizardError):
    """The cloud rejected the username or password."""


class HomeWizardConnectionError(HomeWizardError):
    """The cloud could not be reached, timed out or answered with a server error."""


class HomeWizardResponseError(HomeWizardError):
    """The cloud answered, but not with what the protocol says it should."""


@dataclass(frozen=True, slots=True)
class CloudDevice:
    """One device of the account, as the devices endpoint lists it."""

    identifier: str
    name: str
    type: str


def _basic_auth(username: str, password: str) -> str:
    raw = f"{username}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


class HomeWizardClimateApi:
    """Signs in and lists devices. Holds the token the websocket needs."""

    def __init__(self, session: aiohttp.ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._headers = {"Authorization": _basic_auth(username, password)}
        self.token: str | None = None

    @property
    def username(self) -> str:
        return self._username

    async def _get_json(self, url: str) -> dict[str, Any]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(url, headers=self._headers) as resp:
                    if resp.status in (401, 403):
                        raise HomeWizardAuthError(f"HTTP {resp.status}")
                    if resp.status >= 500:
                        raise HomeWizardConnectionError(f"HTTP {resp.status}")
                    if resp.status != 200:
                        raise HomeWizardResponseError(f"HTTP {resp.status}")
                    try:
                        data = await resp.json(content_type=None)
                    except ValueError as err:
                        raise HomeWizardResponseError("the answer is not JSON") from err
        except TimeoutError as err:
            raise HomeWizardConnectionError(f"no answer in {REQUEST_TIMEOUT} s") from err
        except aiohttp.ClientError as err:
            raise HomeWizardConnectionError(str(err) or type(err).__name__) from err
        if not isinstance(data, dict):
            raise HomeWizardResponseError("the answer is not a JSON object")
        return data

    async def async_login(self) -> str:
        """Sign in and keep the token for the websocket."""
        data = await self._get_json(API_LOGIN_URL)
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise HomeWizardAuthError("the cloud did not return a token")
        self.token = token
        return token

    async def async_get_devices(self) -> list[CloudDevice]:
        """Every device of the account, whatever its type."""
        data = await self._get_json(API_DEVICES_URL)
        raw = data.get("devices")
        if not isinstance(raw, list):
            raise HomeWizardResponseError("the answer has no device list")
        devices = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("identifier") or not item.get("type"):
                _LOGGER.debug("Skipping a device entry without identifier or type: %s", item)
                continue
            devices.append(
                CloudDevice(
                    identifier=str(item["identifier"]),
                    name=str(item.get("name") or item["identifier"]),
                    type=str(item["type"]),
                )
            )
        return devices
