"""Diagnostic sensor exposing the latest synchronization status."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    syncer = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SyncStatusSensor(entry, syncer)])


class SyncStatusSensor(SensorEntity):
    """Expose synchronization state without exposing list contents."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_icon = "mdi:sync"

    def __init__(self, entry: ConfigEntry, syncer) -> None:
        self._syncer = syncer
        self._attr_unique_id = f"{entry.entry_id}_sync_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=entry.title
        )
        self._remove_status_listener = None

    @property
    def native_value(self) -> str:
        return self._syncer.status

    @property
    def extra_state_attributes(self) -> dict:
        return self._syncer.status_attributes

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_status_listener = self._syncer.async_add_status_listener(
            self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_status_listener:
            self._remove_status_listener()
            self._remove_status_listener = None
        await super().async_will_remove_from_hass()
