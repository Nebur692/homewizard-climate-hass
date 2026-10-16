"""Shared fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homewizard_climate import api as api_module
from custom_components.homewizard_climate import connection as connection_module
from custom_components.homewizard_climate.const import DOMAIN

from .fake_cloud import PASSWORD, USERNAME, FakeCloud


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture
async def cloud(socket_enabled: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeCloud]:
    """Two fans on a fake cloud, and the integration pointed at it. Fast reconnects."""
    fake = FakeCloud.two_fans()
    await fake.start()
    monkeypatch.setattr(api_module, "API_LOGIN_URL", f"{fake.base}/v1/auth/login")
    monkeypatch.setattr(api_module, "API_DEVICES_URL", f"{fake.base}/v1/auth/devices")
    monkeypatch.setattr(connection_module, "WS_URL", f"{fake.base}/ws")
    monkeypatch.setattr(connection_module, "RECONNECT_MIN", 0.05)
    monkeypatch.setattr(connection_module, "RECONNECT_MAX", 0.2)
    yield fake
    await fake.stop()


def make_entry(hass: HomeAssistant, password: str = PASSWORD, unique_id: str | None = USERNAME) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=USERNAME,
        unique_id=unique_id,
        data={CONF_USERNAME: USERNAME, CONF_PASSWORD: password},
        version=1,
    )
    entry.add_to_hass(hass)
    return entry


async def wait_for(condition: Callable[[], bool], hass: HomeAssistant, timeout: float = 3) -> None:
    """Wait for a condition, not a clock: the websocket is a real one on loopback."""
    import asyncio

    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not condition():
        if loop.time() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)
        await hass.async_block_till_done()
