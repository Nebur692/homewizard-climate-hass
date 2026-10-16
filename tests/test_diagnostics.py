"""The diagnostics download carries the states, never the credentials."""

from __future__ import annotations

import json

from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant

from custom_components.homewizard_climate.diagnostics import async_get_config_entry_diagnostics

from .conftest import make_entry, wait_for
from .fake_cloud import PASSWORD, TOKEN, USERNAME, FakeCloud


async def test_no_credentials_in_diagnostics(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(lambda: hass.states.get("fan.bedroom_fan").state == STATE_OFF, hass)
    data = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(data, default=str)
    for secret in (PASSWORD, TOKEN, USERNAME):
        assert secret not in dumped
    assert data["connected"] is True
    assert [d["type"] for d in data["devices"]] == ["fan", "fan"]
    assert data["devices"][0]["state"]["speed"] == 1
