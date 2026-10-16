"""A strict stand-in for the HomeWizard Climate cloud: REST sign-in, device list and the websocket.

Its messages copy the real ones (captured from a live account with two fans,
identifiers replaced): hello and subscribe answers, a full device update with
"online", and JSON patches both ways. It is strict where the real cloud is:
basic auth on REST, the token on hello, subscribe before any update, and a
patch only touches a field the device has.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
from dataclasses import dataclass, field
from typing import Any

from aiohttp import WSMsgType, web

USERNAME = "jo@example.com"
PASSWORD = "correct horse"
TOKEN = "tok-0123456789abcdef0123456789abcdef"

FAN_STATE = {"power_on": False, "oscillation": False, "timer": 0, "mode": "normal", "speed": 1}
HEATERFAN_STATE = {
    "power_on": True,
    "heater": True,
    "current_temperature": 19,
    "target_temperature": 22,
    "current_humidity": 45,
    "fan_speed": 2,
    "oscillate": False,
    "mode": "normal",
    "timer": 0,
}
HEATER_STATE = {
    "power_on": False,
    "current_temperature": 18,
    "target_temperature": 21,
    "mode": "low",
    "lock": False,
    "timer": 0,
}
DEHUMIDIFIER_STATE = {
    "power_on": True,
    "mode": "laundry",
    "current_humidity": 61,
    "target_humidity": 50,
    "fan_speed": "high",
    "swing": False,
    "lock": False,
    "defrosting": False,
    "fault": [],
    "timer": 0,
}


# The states below use the fields and values of the official HomeWizard Climate
# app's models (airconditioner, aircooler, airpurifier); not captured from a device.
AIRCONDITIONER_STATE = {
    "power_on": False,
    "mode": "cool",
    "current_temperature": 27,
    "target_temperature": 22,
    "fan_speed": "low",
    "oscillate": False,
    "sleep": False,
    "silent": False,
    "error": [],
    "timer": 0,
}
AIRCOOLER_STATE = {
    "power_on": True,
    "cool": False,
    "fan_speed": "med",
    "mode": "manual",
    "oscillate": True,
    "mute": False,
    "warning": [],
    "timer": 0,
}
PURIFIER_STATE = {
    "power_on": True,
    "mode": "auto",
    "fan_speed": 2,
    "air_quality": "good",
    "pm2_5_level": 12,
    "current_temperature": 21.5,
    "current_humidity": 48.0,
    "filter_life_remaining": 73,
    "filter_check": False,
    "lock": False,
    "mute": False,
    "aq_light": "full_on",
    "night_light": "off",
    "error": [],
    "timer": 0,
}


@dataclass
class FakeDevice:
    identifier: str
    name: str
    type: str
    state: dict[str, Any]
    online: bool = True
    # Some devices send these in full updates; the fans of the captured account did not.
    model: str | None = None
    version: str | None = None


@dataclass
class FakeCloud:
    devices: list[FakeDevice] = field(default_factory=list)
    rest_status: int | None = None  # force every REST answer to this status
    rest_delay: float = 0  # seconds before answering REST
    ws_reject_token: bool = False
    answer_pings: bool = True  # False: a half-dead link that never answers a ping
    received: list[dict[str, Any]] = field(default_factory=list)
    hellos: int = 0
    logins: int = 0
    _sockets: list[web.WebSocketResponse] = field(default_factory=list)
    _subs: dict[int, set[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._runner: web.AppRunner | None = None
        self.base = ""

    @staticmethod
    def two_fans() -> FakeCloud:
        return FakeCloud(
            devices=[
                FakeDevice("FAN000000000001", "Bedroom fan", "fan", copy.deepcopy(FAN_STATE)),
                FakeDevice("FAN000000000002", "Living room fan", "fan", copy.deepcopy(FAN_STATE)),
            ]
        )

    def device(self, identifier: str) -> FakeDevice:
        return next(d for d in self.devices if d.identifier == identifier)

    # ---- server ----------------------------------------------------------

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/v1/auth/login", self._login)
        app.router.add_get("/v1/auth/devices", self._devices)
        app.router.add_get("/ws", self._ws)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
        self.base = f"http://127.0.0.1:{port}"

    async def stop(self) -> None:
        for ws in list(self._sockets):
            await ws.close()
        if self._runner:
            await self._runner.cleanup()

    def _authorized(self, request: web.Request) -> bool:
        expected = "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
        return request.headers.get("Authorization") == expected

    async def _rest_guard(self, request: web.Request) -> web.Response | None:
        if self.rest_delay:
            await asyncio.sleep(self.rest_delay)
        if self.rest_status is not None:
            return web.Response(status=self.rest_status, text="forced")
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return None

    async def _login(self, request: web.Request) -> web.Response:
        if (forced := await self._rest_guard(request)) is not None:
            return forced
        self.logins += 1
        return web.json_response({"token": TOKEN})

    async def _devices(self, request: web.Request) -> web.Response:
        if (forced := await self._rest_guard(request)) is not None:
            return forced
        return web.json_response(
            {
                "devices": [
                    {"grants": None, "identifier": d.identifier, "name": d.name, "type": d.type, "endpoint": None}
                    for d in self.devices
                ]
            }
        )

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(autoping=self.answer_pings)
        await ws.prepare(request)
        self._sockets.append(ws)
        subs = self._subs.setdefault(id(ws), set())
        authed = False
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:  # pings land here when answer_pings is False: ignored
                continue
            data = json.loads(msg.data)
            self.received.append(data)
            kind = data.get("type")
            if kind == "hello":
                self.hellos += 1
                ok = data.get("token") == TOKEN and not self.ws_reject_token
                await ws.send_json({"type": "response", "message_id": "hello", "status": 200 if ok else 401})
                authed = ok
            elif not authed:
                await ws.send_json({"type": "response", "message_id": data.get("message_id"), "status": 401})
            elif kind == "subscribe_device":
                dev = next((d for d in self.devices if d.identifier == data.get("device")), None)
                if dev is None:
                    await ws.send_json({"type": "response", "message_id": "subscribe", "status": 404})
                    continue
                subs.add(dev.identifier)
                await ws.send_json(
                    {"type": "response", "message_id": "subscribe", "status": 200, "details": "Tracking ID: 1"}
                )
                await ws.send_json(self._full(dev))
            elif kind == "json_patch":
                await self._apply(data)
        self._sockets.remove(ws)
        self._subs.pop(id(ws), None)
        return ws

    def _full(self, dev: FakeDevice) -> dict[str, Any]:
        return {
            "type": dev.type,
            "device": dev.identifier,
            "state": dict(dev.state),
            "name": dev.name,
            "online": dev.online,
            **({"model": dev.model} if dev.model else {}),
            **({"version": dev.version} if dev.version else {}),
        }

    async def _apply(self, data: dict[str, Any]) -> None:
        dev = next((d for d in self.devices if d.identifier == data.get("device")), None)
        if dev is None:
            return
        applied = []
        for patch in data.get("patch") or []:
            parts = str(patch.get("path", "")).strip("/").split("/")
            # Strict: only replace, only /state/<field>, only fields this device has.
            if patch.get("op") == "replace" and len(parts) == 2 and parts[0] == "state" and parts[1] in dev.state:
                dev.state[parts[1]] = patch.get("value")
                applied.append(patch)
        if applied:
            await self.broadcast({"type": "json_patch", "device": dev.identifier, "patch": applied})

    # ---- what a test can make the cloud do -------------------------------

    async def broadcast(self, message: dict[str, Any]) -> None:
        for ws in list(self._sockets):
            if message.get("device") in self._subs.get(id(ws), set()) and not ws.closed:
                await ws.send_json(message)

    async def push_full(self, identifier: str) -> None:
        await self.broadcast(self._full(self.device(identifier)))

    async def set_online(self, identifier: str, online: bool) -> None:
        self.device(identifier).online = online
        await self.push_full(identifier)

    async def drop_connections(self) -> None:
        for ws in list(self._sockets):
            await ws.close()

    def patches_sent(self) -> list[tuple[str, str, Any]]:
        out = []
        for msg in self.received:
            if msg.get("type") == "json_patch":
                for patch in msg["patch"]:
                    out.append((msg["device"], patch["path"], patch["value"]))
        return out
