"""The websocket to the HomeWizard Climate cloud: one per account, not per device.

The cloud pushes the full state of every subscribed device and then JSON
patches; commands go back as JSON patches. The connection runs as a background
task of the config entry and reconnects on its own with a growing delay, so a
lost connection is never silent: while it is down every device is reported as
unavailable instead of showing its last state as if it were current.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .api import CloudDevice, HomeWizardAuthError, HomeWizardClimateApi, HomeWizardError
from .const import RECONNECT_MAX, RECONNECT_MIN, REQUEST_TIMEOUT, WS_COMPATIBILITY, WS_HEARTBEAT, WS_SOURCE, WS_URL

_LOGGER = logging.getLogger(__name__)


class NotConnectedError(Exception):
    """A command was sent while the websocket is down."""


@dataclass(slots=True)
class DeviceState:
    """What the cloud last told us about one device."""

    device: CloudDevice
    state: dict[str, Any] = field(default_factory=dict)
    online: bool = False
    received: bool = False


class HomeWizardClimateConnection:
    """Keeps the websocket up and the device states current."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api: HomeWizardClimateApi,
        devices: list[CloudDevice],
        on_auth_failed: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._api = api
        self._on_auth_failed = on_auth_failed
        self.devices: dict[str, DeviceState] = {d.identifier: DeviceState(d) for d in devices}
        self._listeners: dict[str, list[Callable[[], None]]] = {}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._stopped = False
        self.connected = False
        # The token from setup is fresh; after a drop we sign in again before reconnecting.
        self._token_fresh = api.token is not None
        self._token_rejected = False
        self._last_pong = 0.0
        self.reconnects = 0

    # ---- listeners -------------------------------------------------------

    def add_listener(self, identifier: str, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.setdefault(identifier, []).append(callback)

        def remove() -> None:
            self._listeners[identifier].remove(callback)

        return remove

    def _notify(self, identifier: str | None = None) -> None:
        targets = [identifier] if identifier else list(self._listeners)
        for ident in targets:
            for callback in list(self._listeners.get(ident, [])):
                callback()

    def is_available(self, identifier: str) -> bool:
        dev = self.devices.get(identifier)
        return bool(self.connected and dev and dev.received and dev.online)

    # ---- lifecycle -------------------------------------------------------

    async def run(self) -> None:
        """Connect, listen and reconnect until stopped."""
        delay = RECONNECT_MIN
        while not self._stopped:
            try:
                if not self._token_fresh:
                    await self._api.async_login()
                self._token_fresh = False
                await self._listen()
                delay = RECONNECT_MIN
            except HomeWizardAuthError:
                _LOGGER.warning("HomeWizard rejected the credentials; asking to sign in again")
                self._set_connected(False)
                if self._on_auth_failed:
                    self._on_auth_failed()
                return
            except (HomeWizardError, aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.debug("HomeWizard websocket error: %s", err)
            self._set_connected(False)
            if self._stopped:
                return
            self.reconnects += 1
            _LOGGER.debug("Reconnecting to HomeWizard in %s s", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)

    async def stop(self) -> None:
        self._stopped = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._set_connected(False)

    def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            self._notify()

    async def _listen(self) -> None:
        self._token_rejected = False
        # Our own keepalive instead of aiohttp's heartbeat=: aiohttp 3.14 leaves the
        # heartbeat timer armed on every socket the client closes, so it would fire on
        # a dead socket 30 s later. autoping=False lets us see the pongs ourselves.
        async with self._session.ws_connect(
            WS_URL,
            autoping=False,
            timeout=aiohttp.ClientWSTimeout(ws_receive=None, ws_close=REQUEST_TIMEOUT),
        ) as ws:
            self._ws = ws
            if self._stopped:
                # stop() ran while this socket was still opening.
                return
            keepalive = asyncio.get_running_loop().create_task(self._keepalive(ws))
            try:
                await ws.send_json(
                    {
                        "message_id": "hello",
                        "token": self._api.token,
                        "type": "hello",
                        "source": WS_SOURCE,
                        "compatibility": WS_COMPATIBILITY,
                    }
                )
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.PING:
                        await ws.pong(msg.data)
                    elif msg.type == aiohttp.WSMsgType.PONG:
                        self._last_pong = asyncio.get_running_loop().time()
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            message = json.loads(msg.data)
                        except ValueError:
                            _LOGGER.debug("Ignoring a websocket message that is not JSON: %.200s", msg.data)
                            continue
                        await self._handle(message)
                        if self._token_rejected:
                            break
                    else:
                        break
            finally:
                keepalive.cancel()
        self._ws = None
        if self._token_rejected:
            # Token expired: sign in again and reconnect.
            raise HomeWizardError("token rejected by the websocket")

    async def _keepalive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Ping every WS_HEARTBEAT seconds; no pong by the next ping means the link is dead."""
        loop = asyncio.get_running_loop()
        self._last_pong = loop.time()
        while not ws.closed:
            sent = loop.time()
            await ws.ping()
            await asyncio.sleep(WS_HEARTBEAT)
            if self._last_pong < sent:
                _LOGGER.debug("No pong from HomeWizard in %s s; reconnecting", WS_HEARTBEAT)
                await ws.close()
                return

    async def _handle(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        kind = message.get("type")
        if kind == "response":
            status = message.get("status")
            if status == 401:
                # Token expired: _listen closes the socket and we sign in again.
                self._token_rejected = True
                self._set_connected(False)
            elif message.get("message_id") == "hello" and status == 200:
                self._set_connected(True)
                for identifier in self.devices:
                    await self._send({"type": "subscribe_device", "device": identifier, "message_id": "subscribe"})
            return

        identifier = message.get("device")
        dev = self.devices.get(identifier) if isinstance(identifier, str) else None
        if dev is None:
            return
        if kind == "json_patch":
            changed = False
            for patch in message.get("patch") or []:
                if not isinstance(patch, dict) or patch.get("op") != "replace":
                    continue
                parts = str(patch.get("path", "")).strip("/").split("/")
                if len(parts) == 2 and parts[0] == "state":
                    dev.state[parts[1]] = patch.get("value")
                    changed = True
            if changed:
                self._notify(identifier)
        elif kind == dev.device.type:
            # Full update of this device; "online" says whether the device itself is reachable.
            state = message.get("state")
            if isinstance(state, dict):
                dev.state = dict(state)
                dev.received = True
            if "online" in message:
                dev.online = bool(message["online"])
            self._notify(identifier)

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None or self._ws.closed or not self.connected:
            raise NotConnectedError
        await self._ws.send_json(payload)

    async def async_set(self, identifier: str, key: str, value: Any) -> None:
        """Change one field of a device's state. The cloud answers with a patch."""
        await self._send(
            {
                "device": identifier,
                "type": "json_patch",
                "patch": [{"op": "replace", "path": f"/state/{key}", "value": value}],
            }
        )
