"""Tests for storage format compatibility and persistence scheduling."""

from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.todo_sync.models import ItemKey
from custom_components.todo_sync.status import SyncStatus
from custom_components.todo_sync.storage import TodoSyncStorage


@pytest.mark.asyncio
async def test_storage_skips_unchanged_payload():
    storage = TodoSyncStorage.__new__(TodoSyncStorage)
    storage._store = Mock()
    storage._store.async_save = AsyncMock()
    storage._last_saved_data = {"snapshot": {}, "status": {}, "pending_writes": {}}
    storage._last_scheduled_data = None
    storage._scheduled_data = None

    await storage.async_save(storage._last_saved_data)

    storage._store.async_save.assert_not_awaited()


def test_delayed_save_callback_returns_latest_payload():
    storage = TodoSyncStorage.__new__(TodoSyncStorage)
    storage._store = Mock()
    storage._store.async_delay_save = Mock()
    storage._last_saved_data = {"state": "old"}
    storage._last_scheduled_data = None
    storage._scheduled_data = None

    storage.async_delay_save({"state": "first"}, 5)
    callback = storage._store.async_delay_save.call_args.args[0]
    storage.async_delay_save({"state": "latest"}, 5)

    assert callback() == {"state": "latest"}
    assert storage._store.async_delay_save.call_count == 2


def test_storage_serialization_preserves_existing_snapshot_key_format():
    key = ItemKey("Milk", "3")
    snapshot = {
        key: {
            "title": "Milk 3",
            "name": "Milk",
            "status": "needs_action",
            "description": "3",
            "uid": "provider-local",
        }
    }

    data = TodoSyncStorage.serialize(snapshot, {}, SyncStatus())

    assert data == {
        "snapshot": {
            '["milk","3"]': {
                "title": "Milk 3",
                "name": "Milk",
                "status": "needs_action",
                "description": "3",
            }
        },
        "status": SyncStatus().to_dict(),
        "pending_writes": {},
    }
