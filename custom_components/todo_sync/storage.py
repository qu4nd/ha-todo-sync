"""Persistence boundary for synchronization snapshots and status."""

from __future__ import annotations

import copy

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_VERSION
from .models import ItemKey, TodoItem
from .status import SyncStatus


class TodoSyncStorage:
    """Own Store I/O, persisted-format conversion, and save deduplication."""

    def __init__(self, hass: HomeAssistant, key: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, key)
        self._last_saved_data: dict | None = None
        self._last_scheduled_data: dict | None = None
        self._scheduled_data: dict | None = None

    async def async_load(self) -> dict | None:
        """Load the persisted payload and remember its exact representation."""
        data = await self._store.async_load()
        self.set_loaded_data(data)
        return data

    def set_loaded_data(self, data: dict | None) -> None:
        """Record the payload read from storage for subsequent write deduplication."""
        self._last_saved_data = copy.deepcopy(data)

    @staticmethod
    def migrate_snapshot(snapshot: dict) -> dict[ItemKey, TodoItem]:
        """Convert legacy or current storage keys into the in-memory item model."""
        migrated: dict[ItemKey, TodoItem] = {}
        for old_key, item in snapshot.items():
            if isinstance(item, dict) and item.get("name"):
                key = ItemKey(item["name"], item.get("description") or "")
                # Older snapshots may contain provider UIDs; they are never shared identity.
                migrated_item = {
                    field: value for field, value in item.items() if field != "uid"
                }
                migrated[key] = migrated_item
                continue

            # Preserve malformed/legacy entries as far as possible instead of dropping data.
            try:
                key = ItemKey.from_storage_key(old_key)
            except (TypeError, ValueError):
                key = ItemKey(str(old_key))
            migrated[key] = item
        return migrated

    @staticmethod
    def serialize(
        snapshot: dict[ItemKey, TodoItem],
        pending_writes: dict[str, dict],
        status: SyncStatus,
    ) -> dict:
        """Return the existing JSON-compatible storage envelope."""
        stored_snapshot = {
            key.storage_key: (
                {field: value for field, value in item.items() if field != "uid"}
                if isinstance(item, dict)
                else item
            )
            for key, item in snapshot.items()
        }
        return {
            "snapshot": copy.deepcopy(stored_snapshot),
            "status": status.to_dict(),
            "pending_writes": copy.deepcopy(pending_writes),
        }

    async def async_save(self, data: dict) -> None:
        """Persist a changed payload immediately; skip unchanged data."""
        if data == self._last_saved_data:
            return
        await self._store.async_save(data)
        self._last_saved_data = copy.deepcopy(data)

    def async_delay_save(self, data: dict, delay: float) -> None:
        """Schedule the latest changed payload while avoiding duplicate timers."""
        if data == self._last_saved_data or data == self._last_scheduled_data:
            return
        self._scheduled_data = copy.deepcopy(data)
        self._last_scheduled_data = copy.deepcopy(data)
        self._store.async_delay_save(self._scheduled_payload, delay)

    def _scheduled_payload(self) -> dict:
        """Return the newest scheduled payload when Home Assistant flushes the save."""
        return copy.deepcopy(self._scheduled_data)
