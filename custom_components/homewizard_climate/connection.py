"""The websocket to the HomeWizard Climate cloud: one per account, not per device.

The cloud pushes the full state of every subscribed device and then JSON
patches; commands go back as JSON patches. The connection runs as a background
task of the config entry and reconnects on its own with a growing delay, so a
lost connection is never silent: while it is down every device is reported as
unavailable instead of showing its last state as if it were current.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .api import CloudDevice, HomeWizardAuthError, HomeWizardClimateApi, HomeWizardError
from .const import RECONNECT_MAX, RECONNECT_MIN, REQUEST_TIMEOUT, WS_COMPATIBILITY, WS_HEARTBEAT, WS_SOURCE, WS_URL

_LOGGER = logging.getLogger(__name__)

# What a dropped or closing socket raises when written to.
_SEND_ERRORS = (aiohttp.ClientError, ConnectionError)


class NotConnectedError(Exception):
    """A command was sent while the websocket is down."""


@dataclass(slots=True)
class DeviceState:
    """What the cloud last told us about one device."""

    device: CloudDevice
    state: dict[str, Any] = field(default_factory=dict)
    online: bool = False
    # Whether the cloud has said anything about "online" yet: the first report is not a change.
    online_reported: bool = False
    received: bool = False
    # Some devices send their hardware model (e.g. PS-A007) and firmware version in full updates.
    model: str | None = None
    version: str | None = None


class HomeWizardClimateConnection:
    """Keeps the websocket up and the device states current."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api: HomeWizardClimateApi,
        devices: list[CloudDevice],
        on_auth_failed: Callable[[], None] | None = None,
        on_device_info: Callable[[str], None] | None = None,
    ) -> None:
        self._session = session
        self._api = api
        self._on_auth_failed = on_auth_failed
        self._on_device_info = on_device_info
        self.devices: dict[str, DeviceState] = {d.identifier: DeviceState(d) for d in devices}
        self._listeners: dict[str, list[Callable[[], None]]] = {}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._stopped = False
        self.connected = False
        # Set once this connection has worked at least once: then a drop is worth one log line.
        self._was_connected = False
        # The token from setup is fresh; after a drop we sign in again before reconnecting.
        self._token_fresh = api.token is not None
        self._token_rejected = False
        self._session_ok = False
        self._last_pong = 0.0
        self.reconnects = 0
        self.next_delay: float = 0  # the wait before the coming reconnect, for diagnostics

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

    # ---- devices added or removed in the app -----------------------------

    async def async_update_devices(self, devices: list[CloudDevice]) -> tuple[list[str], list[str]]:
        """Follow the account's device list: returns (added, removed) identifiers."""
        current = {d.identifier: d for d in devices}
        added = [ident for ident in current if ident not in self.devices]
        removed = [ident for ident in self.devices if ident not in current]
        for ident in removed:
            del self.devices[ident]
        for ident in added:
            self.devices[ident] = DeviceState(current[ident])
            if self.connected:
                with contextlib.suppress(NotConnectedError):
                    await self._send({"type": "subscribe_device", "device": ident, "message_id": "subscribe"})
        return added, removed

    # ---- lifecycle -------------------------------------------------------

    async def run(self) -> None:
        """Connect, listen and reconnect until stopped."""
        delay = RECONNECT_MIN
        while not self._stopped:
            self._session_ok = False
            try:
                if not self._token_fresh:
                    await self._api.async_login()
                self._token_fresh = False
                await self._listen()
            except HomeWizardAuthError:
                _LOGGER.warning("HomeWizard rejected the credentials; asking to sign in again")
                self._set_connected(False)
                if self._on_auth_failed:
                    self._on_auth_failed()
                return
            except (HomeWizardError, aiohttp.ClientError, ConnectionError, TimeoutError, ValueError) as err:
                _LOGGER.debug("HomeWizard websocket error: %s", err)
            except Exception:  # noqa: BLE001 - the loop must survive anything, or entities freeze
                _LOGGER.exception("Unexpected error in the HomeWizard websocket; reconnecting")
            self._set_connected(False)
            if self._stopped:
                return
            # Back to the short delay only after a session that really worked; a cloud that
            # accepts and drops straight away must not be asked again every 5 s forever.
            delay = RECONNECT_MIN if self._session_ok else min(delay * 2, RECONNECT_MAX)
            self.reconnects += 1
            self.next_delay = delay
            _LOGGER.debug("Reconnecting to HomeWizard in %s s", delay)
            await asyncio.sleep(delay)

    async def stop(self) -> None:
        self._stopped = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._set_connected(False)

    def _set_connected(self, value: bool) -> None:
        if self.connected == value:
            return
        self.connected = value
        if value:
            self._session_ok = True
            if self._was_connected:
                _LOGGER.info("Connection with the HomeWizard cloud is back")
            self._was_connected = True
        else:
            # Until the next full update, the last state is history, not the current one.
            for dev in self.devices.values():
                dev.received = False
            if self._was_connected and not self._stopped:
                _LOGGER.info("Connection with the HomeWizard cloud lost; reconnecting")
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
                        try:
                            await self._handle(message)
                        except HomeWizardError:
                            raise
                        except Exception:  # noqa: BLE001 - one odd message must not end the session
                            _LOGGER.exception("Could not process a HomeWizard message: %.300s", msg.data)
                        if self._token_rejected:
                            break
                    else:
                        break
            finally:
                keepalive.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await keepalive
        self._ws = None
        if self._token_rejected:
            # Token expired: sign in again and reconnect.
            raise HomeWizardError("token rejected by the websocket")

    async def _keepalive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Ping every WS_HEARTBEAT seconds; no pong by the next ping means the link is dead."""
        loop = asyncio.get_running_loop()
        self._last_pong = loop.time()
        try:
            while not ws.closed:
                sent = loop.time()
                await ws.ping()
                await asyncio.sleep(WS_HEARTBEAT)
                if self._last_pong < sent:
                    _LOGGER.debug("No pong from HomeWizard in %s s; reconnecting", WS_HEARTBEAT)
                    # Shielded: the reader's cleanup cancels this task, and that must not abort the close.
                    await asyncio.shield(ws.close())
                    return
        except _SEND_ERRORS:
            # The socket is already going down; the reader loop sees it and reconnects.
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
            elif message.get("message_id") == "hello":
                if status != 200:
                    raise HomeWizardError(f"the cloud refused the session (status {status})")
                self._set_connected(True)
                for identifier in list(self.devices):
                    await self._send({"type": "subscribe_device", "device": identifier, "message_id": "subscribe"})
            return

        identifier = message.get("device")
        dev = self.devices.get(identifier) if isinstance(identifier, str) else None
        if dev is None:
            return
        if kind == "json_patch":
            patches = message.get("patch")
            changed = False
            for patch in patches if isinstance(patches, list) else []:
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
            info = (dev.model, dev.version)
            if isinstance(message.get("model"), str):
                dev.model = message["model"]
            if isinstance(message.get("version"), str):
                dev.version = message["version"]
            if (dev.model, dev.version) != info and self._on_device_info:
                self._on_device_info(identifier)
            if "online" in message:
                online = bool(message["online"])
                if dev.online_reported and online != dev.online:
                    _LOGGER.info("HomeWizard device %s is %s", dev.device.name, "online again" if online else "offline")
                dev.online = online
                dev.online_reported = True
            self._notify(identifier)

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None or self._ws.closed or not self.connected:
            raise NotConnectedError
        try:
            await self._ws.send_json(payload)
        except _SEND_ERRORS as err:
            # The socket dropped between the check and the write.
            raise NotConnectedError from err

    async def async_set(self, identifier: str, key: str, value: Any) -> None:
        """Change one field of a device's state. The cloud answers with a patch."""
        await self._send(
            {
                "device": identifier,
                "type": "json_patch",
                "patch": [{"op": "replace", "path": f"/state/{key}", "value": value}],
            }
        )
