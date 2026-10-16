"""Fans move from climate to fan entities, keeping everything the user set.

The original integration showed fans as climate entities. On the first start
of this version each fan's climate registry entry is replaced by a fan entry
with the same object id (climate.bedroom_fan -> fan.bedroom_fan) and the same
area, name, icon, aliases, visibility and voice-assistant exposure. What cannot
be moved by hand is the automations and scripts that still name the old
entity: a Repairs issue lists them until they are changed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.start import async_at_started

from . import burburito
from .const import DOMAIN, FAN_TYPES, legacy_unique_id

if TYPE_CHECKING:
    from . import HomeWizardClimateConfigEntry

_LOGGER = logging.getLogger(__name__)

MIGRATED_KEY = "migrated_fans"
ISSUE_PREFIX = "fan_migrated_"
EVENT_AUTOMATION_RELOADED = "automation_reloaded"
SCRIPT_RELOAD_DELAY = 5
STARTUP_RECHECK_DELAY = 60


def fan_unique_id(identifier: str) -> str:
    return f"fan_{identifier}"


@callback
def async_migrate_fans(hass: HomeAssistant, entry: HomeWizardClimateConfigEntry) -> None:
    """Replace each fan's climate entry with a fan entry, once."""
    ent_reg = er.async_get(hass)
    migrated: dict[str, str] = dict(entry.data.get(MIGRATED_KEY, {}))
    for ident, dev in entry.runtime_data.connection.devices.items():
        if dev.device.type not in FAN_TYPES:
            continue
        old_id = ent_reg.async_get_entity_id("climate", DOMAIN, legacy_unique_id(dev.device.type, ident))
        if old_id is None or ent_reg.async_get_entity_id("fan", DOMAIN, fan_unique_id(ident)):
            continue
        old = ent_reg.async_get(old_id)
        if old is None:
            continue
        object_id = old_id.split(".", 1)[1]
        ent_reg.async_remove(old_id)
        new = ent_reg.async_get_or_create(
            "fan",
            DOMAIN,
            fan_unique_id(ident),
            config_entry=entry,
            device_id=old.device_id,
            suggested_object_id=object_id,
        )
        ent_reg.async_update_entity(
            new.entity_id,
            area_id=old.area_id,
            name=old.name,
            icon=old.icon,
            aliases=old.aliases,
            hidden_by=old.hidden_by,
            disabled_by=old.disabled_by,
            labels=old.labels,
        )
        for domain, options in old.options.items():
            ent_reg.async_update_entity_options(new.entity_id, domain, dict(options))
        migrated[old_id] = new.entity_id
        _LOGGER.info("Fan %s is now %s", old_id, new.entity_id)
    if migrated != entry.data.get(MIGRATED_KEY, {}):
        hass.config_entries.async_update_entry(entry, data={**entry.data, MIGRATED_KEY: migrated})


@callback
def async_track_old_references(hass: HomeAssistant, entry: HomeWizardClimateConfigEntry) -> None:
    """Raise or clear the Repairs issue now, and again when automations or scripts reload."""
    # One pending delayed check at a time, so a burst of reloads does not pile up timers.
    pending: list[CALLBACK_TYPE] = []

    @callback
    def check(_event: Event | None = None) -> None:
        async_check_old_references(hass, entry)

    @callback
    def check_later(delay: float) -> None:
        while pending:
            pending.pop()()

        @callback
        def run(_now: datetime) -> None:
            pending.clear()
            check()

        pending.append(async_call_later(hass, delay, run))

    @callback
    def is_script_reload(event_data: Mapping[str, Any]) -> bool:
        return event_data.get("domain") == "script" and event_data.get("service") == "reload"

    @callback
    def check_after_script_reload(_event: Event) -> None:
        # Scripts fire no event when they finish reloading: look a few seconds after the call.
        check_later(SCRIPT_RELOAD_DELAY)

    @callback
    def check_at_start(_hass: HomeAssistant) -> None:
        check()
        # On a real restart the automations are not always ready to be asked when
        # Home Assistant says it has started (seen on 2026.10.1): look again later.
        check_later(STARTUP_RECHECK_DELAY)

    @callback
    def cancel_pending() -> None:
        while pending:
            pending.pop()()

    entry.async_on_unload(cancel_pending)
    entry.async_on_unload(async_at_started(hass, check_at_start))
    entry.async_on_unload(hass.bus.async_listen(EVENT_AUTOMATION_RELOADED, check))
    entry.async_on_unload(
        hass.bus.async_listen(EVENT_CALL_SERVICE, check_after_script_reload, event_filter=is_script_reload)
    )


@callback
def async_check_old_references(hass: HomeAssistant, entry: HomeWizardClimateConfigEntry) -> None:
    from homeassistant.components.automation import automations_with_entity
    from homeassistant.components.script import scripts_with_entity

    for old_id, new_id in entry.data.get(MIGRATED_KEY, {}).items():
        issue_id = f"{ISSUE_PREFIX}{old_id}"
        users = sorted(set(automations_with_entity(hass, old_id)) | set(scripts_with_entity(hass, old_id)))
        if not users:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
            continue
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="fan_migrated",
            translation_placeholders={
                "old": old_id,
                "new": new_id,
                "users": "\n".join(f"- {user}" for user in users),
                **burburito.footer("migracion/desplegar/no-encontrado", hass.config.language),
            },
        )
