"""Fans move from climate to fan keeping the user's settings, and a repair lists what still uses the old id."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_OFF
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.homewizard_climate.const import DOMAIN, legacy_unique_id

from .conftest import make_entry, wait_for
from .fake_cloud import FakeCloud

BEDROOM_ID = "FAN000000000001"
OLD = "climate.ventilador_cama"
NEW = "fan.ventilador_cama"


def _old_registry_entry(hass: HomeAssistant, entry) -> er.RegistryEntry:
    """What the original integration left behind for this fan, as stored on a real install."""
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, BEDROOM_ID)}, name="Bedroom fan"
    )
    dr.async_get(hass).async_update_device(device.id, area_id="bedroom")
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "climate",
        DOMAIN,
        legacy_unique_id("fan", BEDROOM_ID),
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="ventilador_cama",
        original_name="Ventilador cama",
    )
    ent_reg.async_update_entity(old.entity_id, area_id="bedroom", name="Cama", aliases={"fan by the bed"})
    ent_reg.async_update_entity_options(old.entity_id, "conversation", {"should_expose": True})
    return old


async def test_the_climate_fan_becomes_a_fan_with_the_same_settings(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass)
    old = _old_registry_entry(hass, entry)
    assert old.entity_id == OLD
    assert await hass.config_entries.async_setup(entry.entry_id)
    await wait_for(lambda: hass.states.get(NEW) and hass.states.get(NEW).state == STATE_OFF, hass)

    ent_reg = er.async_get(hass)
    assert ent_reg.async_get(OLD) is None
    new = ent_reg.async_get(NEW)
    assert new.area_id == "bedroom"
    assert new.name == "Cama"
    assert new.aliases == {"fan by the bed"}
    assert new.options["conversation"]["should_expose"] is True
    assert new.device_id == old.device_id
    assert entry.data["migrated_fans"] == {OLD: NEW}
    assert hass.states.get(NEW).name == "Cama"


async def test_second_start_does_not_migrate_again(hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = make_entry(hass)
    _old_registry_entry(hass, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(NEW) is not None
    assert entry.data["migrated_fans"] == {OLD: NEW}


async def test_automations_still_using_the_old_entity_get_a_repair_until_fixed(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    automation = {
        "id": "away",
        "alias": "Away",
        "triggers": [{"trigger": "event", "event_type": "test_away"}],
        "actions": [{"action": "climate.set_hvac_mode", "target": {"entity_id": OLD}, "data": {"hvac_mode": "off"}}],
    }
    assert await async_setup_component(hass, "automation", {"automation": [automation]})
    entry = make_entry(hass)
    _old_registry_entry(hass, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"fan_migrated_{OLD}")
    assert issue is not None
    assert "automation.away" in issue.translation_placeholders["users"]
    assert issue.translation_placeholders["new"] == NEW
    assert issue.translation_placeholders["code"] == "028-004-141-062"

    # Fixed and reloaded, the way the automation editor does it: the issue goes away by itself.
    fixed = {**automation, "actions": [{"action": "fan.turn_off", "target": {"entity_id": NEW}}]}
    with patch("homeassistant.config.load_yaml_config_file", return_value={"automation": [fixed]}):
        await hass.services.async_call("automation", "reload", blocking=True)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"fan_migrated_{OLD}") is None


async def test_no_repair_when_nothing_uses_the_old_entity(hass: HomeAssistant, cloud: FakeCloud) -> None:
    assert await async_setup_component(hass, "automation", {"automation": []})
    entry = make_entry(hass)
    _old_registry_entry(hass, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"fan_migrated_{OLD}") is None


async def test_the_repair_also_appears_when_home_assistant_is_still_starting(
    hass: HomeAssistant, cloud: FakeCloud
) -> None:
    # A real restart: the integration is set up before Home Assistant has finished starting.
    automation = {
        "id": "away",
        "alias": "Away",
        "triggers": [{"trigger": "event", "event_type": "test_away"}],
        "actions": [{"action": "climate.set_hvac_mode", "target": {"entity_id": [OLD]}, "data": {"hvac_mode": "off"}}],
    }
    hass.set_state(CoreState.starting)
    assert await async_setup_component(hass, "automation", {"automation": [automation]})
    entry = make_entry(hass)
    _old_registry_entry(hass, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"fan_migrated_{OLD}")
    assert issue is not None
    assert "automation.away" in issue.translation_placeholders["users"]


async def test_automations_not_ready_at_start_are_found_a_minute_later(hass: HomeAssistant, cloud: FakeCloud) -> None:
    # What happened on a real 2026.10.1 restart: at "started" nothing could be asked yet.
    entry = make_entry(hass)
    _old_registry_entry(hass, entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"fan_migrated_{OLD}") is None
    automation = {
        "id": "away",
        "alias": "Away",
        "triggers": [{"trigger": "event", "event_type": "test_away"}],
        "actions": [{"action": "climate.set_hvac_mode", "target": {"entity_id": OLD}, "data": {"hvac_mode": "off"}}],
    }
    with patch("homeassistant.components.automation.EVENT_AUTOMATION_RELOADED", "not_listened"):
        assert await async_setup_component(hass, "automation", {"automation": [automation]})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"fan_migrated_{OLD}") is not None
