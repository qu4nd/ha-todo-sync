"""Tests for persisted synchronization status and diagnostics."""

from unittest.mock import AsyncMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync import TodoSyncer, _TodoListReadError, _identity
from custom_components.todo_sync.const import CONF_LIST_A, CONF_LIST_B


@pytest.fixture
def syncer(hass):
    entry = MockConfigEntry(
        domain="todo_sync",
        data={CONF_LIST_A: "todo.a", CONF_LIST_B: "todo.b"},
    )
    instance = TodoSyncer(hass, entry)
    instance._store.async_save = AsyncMock()
    instance._store.async_delay_save = Mock()
    return instance


@pytest.mark.asyncio
async def test_status_is_persisted_and_notifies_listeners(syncer):
    notified = []
    syncer.async_add_status_listener(lambda: notified.append(True))

    await syncer._set_status(
        "success", last_success="2026-11-12T12:00:00+00:00", synced_items=2
    )

    assert syncer.status == "success"
    assert syncer.status_attributes == {
        "last_success": "2026-11-12T12:00:00+00:00",
        "last_error": None,
        "synced_items": 2,
        "last_error_type": None,
    }
    assert notified == [True]
    syncer._store.async_delay_save.assert_called_once()
    data_func, delay = syncer._store.async_delay_save.call_args.args
    assert delay == 5
    assert data_func() == {
        "snapshot": {}, "status": syncer._status, "pending_writes": {}
    }
    syncer._store.async_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_restores_history_but_not_syncing_state(syncer, hass):
    syncer._store.async_load = AsyncMock(
        return_value={
            "snapshot": {"milk": {"name": "Milk"}},
            "status": {
                "state": "syncing",
                "last_success": "2026-11-12T12:00:00+00:00",
                "last_error": None,
                "synced_items": 3,
                "last_error_type": None,
            },
        }
    )
    syncer._schedule = lambda _trigger, _delay: None

    await syncer.async_start()

    assert syncer.status == "idle"
    assert syncer.status_attributes["last_success"] == "2026-11-12T12:00:00+00:00"
    assert syncer.status_attributes["synced_items"] == 3
    assert syncer._snapshot == {_identity("Milk", ""): {"name": "Milk"}}


@pytest.mark.asyncio
async def test_restart_restores_pending_write_expectations(syncer):
    pending = {
        syncer._pending_key("todo.b", _identity("Milk", "")): {
            "entity_id": "todo.b",
            "key": _identity("Milk", ""),
            "before": ["needs_action", ""],
            "expected": ["completed", ""],
            "item": {
                "title": "Milk", "name": "Milk",
                "status": "completed", "description": "",
            },
            "expires": 9999999999,
        }
    }
    syncer._store.async_load = AsyncMock(
        return_value={
            "snapshot": {},
            "status": {"state": "success"},
            "pending_writes": pending,
        }
    )
    syncer._schedule = lambda _trigger, _delay: None

    await syncer.async_start()

    assert syncer._pending_writes == pending


@pytest.mark.asyncio
async def test_stop_flushes_latest_snapshot(syncer):
    syncer._snapshot = {_identity("Milk", ""): {
        "title": "Milk", "name": "Milk",
        "status": "needs_action", "description": "",
    }}

    await syncer.async_stop()

    syncer._store.async_save.assert_awaited_once_with(syncer._store_data())


@pytest.mark.asyncio
async def test_read_failure_sets_non_sensitive_error_status(syncer):
    syncer._ready = lambda: True
    syncer._sync = AsyncMock(side_effect=_TodoListReadError("todo.private_list"))
    syncer._schedule = lambda _trigger, _delay: None

    await syncer._run(None)

    assert syncer.status == "error"
    assert syncer.status_attributes["last_error"] is not None
    assert syncer.status_attributes["last_error_type"] == "TodoListReadError"
    assert syncer.status_attributes["synced_items"] == 0
    assert "todo.private_list" not in str(syncer.status_attributes)


@pytest.mark.asyncio
async def test_partial_write_failure_is_reported_as_error(syncer):
    syncer._ready = lambda: True

    async def partial_failure(_trigger):
        syncer._last_synced_items = 2
        return True

    syncer._sync = AsyncMock(side_effect=partial_failure)
    syncer._schedule = lambda _trigger, _delay: None

    await syncer._run(None)

    assert syncer.status == "error"
    assert syncer.status_attributes["last_error_type"] == "WriteError"
    assert syncer.status_attributes["synced_items"] == 2


@pytest.mark.asyncio
async def test_successful_run_updates_last_success_and_count(syncer):
    syncer._ready = lambda: True

    async def successful_run(_trigger):
        syncer._last_synced_items = 4
        return False

    syncer._sync = AsyncMock(side_effect=successful_run)

    await syncer._run(None)

    assert syncer.status == "success"
    assert syncer.status_attributes["last_success"] is not None
    assert syncer.status_attributes["synced_items"] == 4


@pytest.mark.asyncio
async def test_apply_counts_create_update_and_delete_only(syncer):
    syncer._supports_description = lambda _entity_id: True
    syncer._call = AsyncMock()
    target = {
        "title": "Milk",
        "name": "Milk",
        "status": "needs_action",
        "description": "",
    }

    assert await syncer._apply("todo.b", {}, "milk", target) is True
    assert await syncer._apply("todo.b", {"milk": target}, "milk", target) is False
    assert await syncer._apply("todo.b", {"milk": target}, "milk", None) is True
    assert syncer._call.await_count == 2
