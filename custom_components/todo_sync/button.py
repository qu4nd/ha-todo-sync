"""Button to trigger an immediate sync."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TodoSyncConfigEntry
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TodoSyncConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([SyncNowButton(entry, entry.runtime_data)])


class SyncNowButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "sync_now"
    _attr_icon = "mdi:sync"

    def __init__(self, entry: TodoSyncConfigEntry, syncer) -> None:
        self._syncer = syncer
        self._attr_unique_id = f"{entry.entry_id}_sync_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title
        )

    async def async_press(self) -> None:
        self._syncer.async_sync_now()
