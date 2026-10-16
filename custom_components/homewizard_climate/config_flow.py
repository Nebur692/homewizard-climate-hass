"""Config flow: add a HomeWizard Climate account, or type its password again."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from . import burburito
from .api import HomeWizardAuthError, HomeWizardClimateApi, HomeWizardConnectionError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_ERROR_KEYS = {
    "invalid_auth": "configuracion/iniciar-sesion/credencial-invalida",
    "cannot_connect": "configuracion/iniciar-sesion/sin-conexion",
    "unknown": "configuracion/iniciar-sesion/respuesta-ilegible",
}
_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password"))


class HomeWizardClimateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HomeWizard Climate."""

    VERSION = 1

    async def _async_try_login(self, username: str, password: str) -> str | None:
        """None when the cloud accepts the account; otherwise the error key."""
        api = HomeWizardClimateApi(async_get_clientsession(self.hass), username, password)
        try:
            await api.async_login()
        except HomeWizardAuthError:
            return "invalid_auth"
        except HomeWizardConnectionError:
            return "cannot_connect"
        except Exception:  # noqa: BLE001 - shown to the person as "unknown", detail in the log
            _LOGGER.exception("Unexpected error signing in to HomeWizard")
            return "unknown"
        return None

    def _placeholders(self, error: str | None) -> dict[str, str]:
        if error is None:
            return {"code": "", "joke": ""}
        return burburito.footer(_ERROR_KEYS[error], self.hass.config.language)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        error = None
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()
            error = await self._async_try_login(username, user_input[CONF_PASSWORD])
            if error is None:
                return self.async_create_entry(
                    title=username, data={CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD): _PASSWORD,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors={"base": error} if error else {},
            description_placeholders=self._placeholders(error),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        error = None
        if user_input is not None:
            error = await self._async_try_login(entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD}),
            errors={"base": error} if error else {},
            description_placeholders={"username": entry.data[CONF_USERNAME], **self._placeholders(error)},
        )
