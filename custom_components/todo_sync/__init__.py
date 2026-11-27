"""Home Assistant entry points for the To-do Sync integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .storage import TodoSyncStorage
from .syncer import TodoSyncer

PLATFORMS = ["button", "sensor"]

TodoSyncConfigEntry = ConfigEntry[TodoSyncer]


async def async_setup_entry(hass: HomeAssistant, entry: TodoSyncConfigEntry) -> bool:
    syncer = TodoSyncer(hass, entry)
    entry.runtime_data = syncer
    # Home Assistant runs this callback after a successful unload and also when
    # setup fails, so partially initialized resources cannot outlive the entry.
    entry.async_on_unload(syncer.async_stop)

    await syncer.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: TodoSyncConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TodoSyncConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: TodoSyncConfigEntry
) -> None:
    """Remove persisted synchronization data only when the config entry is deleted."""
    await TodoSyncStorage(hass, f"{DOMAIN}.{entry.entry_id}").async_remove()
