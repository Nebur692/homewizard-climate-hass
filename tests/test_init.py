"""Setup: retries when the cloud is down, asks for the password when it is wrong, never hangs."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.homewizard_climate import api as api_module
from custom_components.homewizard_climate.const import DOMAIN

from .conftest import make_entry, wait_for
from .fake_cloud import USERNAME, FakeCloud, FakeDevice

BEDROOM = "fan.bedroom_fan"


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_cloud_server_error_retries_later(hass: HomeAssistant, cloud: FakeCloud, status: int) -> None:
    cloud.rest_status = status
    entry = make_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert "028-001-140-001" in entry.reason


async def test_a_cloud_that_does_not_answer_times_out_and_retries(
    hass: HomeAssistant, cloud: FakeCloud, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "REQUEST_TIMEOUT", 0.2)
    cloud.rest_delay = 2
    entry = make_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unreachable_cloud_retries(
    hass: HomeAssistant, cloud: FakeCloud, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing listens on this port: a connection error, not an HTTP answer.
    monkeypatch.setattr(api_module, "API_LOGIN_URL", "http://127.0.0.1:9/v1/auth/login")
    entry = make_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_wrong_password_starts_reauth_instead_of_retrying(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass, password="old password")
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == SOURCE_REAUTH]
    assert len(flows) == 1


async def test_unknown_device_type_is_left_out_with_a_repair_and_the_rest_work(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    cloud.devices.append(FakeDevice("AF0000000000001", "Air fryer", "aerofryer", {"power_on": False}))
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(lambda: hass.states.get(BEDROOM) and hass.states.get(BEDROOM).state == STATE_OFF, hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "unsupported_type_aerofryer")
    assert issue is not None
    assert issue.translation_placeholders["code"] == "028-001-140-103"
    # Gone once the device is gone.
    cloud.devices.pop()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, "unsupported_type_aerofryer") is None


async def test_entry_from_the_original_integration_gets_a_unique_id(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass, unique_id=None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.unique_id == USERNAME


async def test_unload_closes_the_websocket_and_entities_go_unavailable(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(lambda: hass.states.get(BEDROOM).state == STATE_OFF, hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await wait_for(lambda: not cloud._sockets, hass)  # noqa: SLF001
    assert hass.states.get(BEDROOM).state == STATE_UNAVAILABLE
