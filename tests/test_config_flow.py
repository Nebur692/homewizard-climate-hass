"""Adding the account and typing the password again."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.homewizard_climate.const import DOMAIN

from .conftest import make_entry
from .fake_cloud import PASSWORD, USERNAME, FakeCloud


async def _start(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})


async def test_adds_the_account(hass: HomeAssistant, cloud: FakeCloud) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == USERNAME
    assert result["data"] == {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}


async def test_wrong_password_shows_the_error_with_its_code(hass: HomeAssistant, cloud: FakeCloud) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: "nope"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert result["description_placeholders"]["code"] == "028-002-001-041"
    assert result["description_placeholders"]["joke"]


async def test_cloud_down_shows_cannot_connect(hass: HomeAssistant, cloud: FakeCloud) -> None:
    cloud.rest_status = 503
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert result["description_placeholders"]["code"] == "028-002-001-001"


async def test_unexpected_answer_shows_unknown(hass: HomeAssistant, cloud: FakeCloud) -> None:
    cloud.rest_status = 404
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
    )
    assert result["errors"] == {"base": "unknown"}
    assert result["description_placeholders"]["code"] == "028-002-001-022"


async def test_same_account_twice_is_refused(hass: HomeAssistant, cloud: FakeCloud) -> None:
    make_entry(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: USERNAME.upper(), CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_the_password_and_reloads(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass, password="old password")
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["username"] == USERNAME
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: "still wrong"})
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PASSWORD: PASSWORD})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == PASSWORD
    # Still only one entry: reauth updates, it does not add another.
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
