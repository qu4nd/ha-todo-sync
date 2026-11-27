"""Integration lifecycle regression tests."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync import (
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.todo_sync.const import (
    CONF_LIST_A,
    CONF_LIST_B,
    CONF_RESET_SYNC_STATE,
    DOMAIN,
)
from custom_components.todo_sync.syncer import TodoSyncer

@pytest.fixture
def entry():
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LIST_A: "todo.a", CONF_LIST_B: "todo.b"},
    )

@pytest.mark.asyncio
async def test_setup_stores_syncer_in_runtime_data_and_registers_cleanup(
    hass, entry, monkeypatch
):
    syncer = Mock()
    syncer.async_start = AsyncMock()
    on_unload = Mock()
    entry.async_on_unload = on_unload
    monkeypatch.setattr("custom_components.todo_sync.TodoSyncer", lambda _hass, _entry: syncer)
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    assert await async_setup_entry(hass, entry)

    assert entry.runtime_data is syncer
    syncer.async_start.assert_awaited_once()
    on_unload.assert_any_call(syncer.async_stop)
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, ["button", "sensor"]
    )

@pytest.mark.asyncio
async def test_setup_failure_has_registered_syncer_cleanup(hass, entry, monkeypatch):
    syncer = Mock()
    syncer.async_start = AsyncMock(side_effect=RuntimeError("start failed"))
    on_unload = Mock()
    entry.async_on_unload = on_unload
    monkeypatch.setattr("custom_components.todo_sync.TodoSyncer", lambda _hass, _entry: syncer)

    with pytest.raises(RuntimeError, match="start failed"):
        await async_setup_entry(hass, entry)

    assert entry.runtime_data is syncer
    on_unload.assert_any_call(syncer.async_stop)

@pytest.mark.asyncio
async def test_unload_failure_keeps_runtime_data(hass, entry):
    syncer = Mock()
    entry.runtime_data = syncer
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    assert not await async_unload_entry(hass, entry)

    assert entry.runtime_data is syncer

@pytest.mark.asyncio
async def test_successful_unload_delegates_cleanup_to_config_entry(hass, entry):
    syncer = Mock()
    entry.runtime_data = syncer
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    assert await async_unload_entry(hass, entry)

    # Home Assistant invokes the registered async_on_unload callback after this
    # function succeeds and then clears ConfigEntry.runtime_data.
    hass.config_entries.async_unload_platforms.assert_awaited_once_with(
        entry, ["button", "sensor"]
    )

@pytest.mark.asyncio
async def test_remove_entry_deletes_persisted_data(hass, entry, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(
        "custom_components.todo_sync.TodoSyncStorage.async_remove", remove
    )

    await async_remove_entry(hass, entry)

    remove.assert_awaited_once()

@pytest.mark.asyncio
async def test_stop_waits_for_in_flight_sync_lock(hass, entry):
    syncer = TodoSyncer(hass, entry)
    syncer._storage_loaded = True
    syncer._store.async_save = AsyncMock()
    await syncer._lock.acquire()

    stop_task = asyncio.create_task(syncer.async_stop())
    await asyncio.sleep(0)

    assert not stop_task.done()
    assert syncer._stopped is True

    syncer._lock.release()
    await stop_task

    syncer._store.async_save.assert_awaited_once_with(syncer._store_data())

@pytest.mark.asyncio
async def test_stop_does_not_overwrite_storage_when_load_fails(hass, entry):
    syncer = TodoSyncer(hass, entry)
    syncer._store.async_load = AsyncMock(side_effect=OSError("storage unavailable"))
    syncer._store.async_save = AsyncMock()

    with pytest.raises(OSError, match="storage unavailable"):
        await syncer.async_start()

    await syncer.async_stop()

    syncer._store.async_save.assert_not_awaited()

@pytest.mark.asyncio
async def test_reconfigure_reset_marker_clears_old_storage_before_start(
    hass, entry, monkeypatch
):
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_LIST_A: "todo.new_a",
            CONF_LIST_B: "todo.new_b",
            CONF_RESET_SYNC_STATE: True,
        },
    )
    remove = AsyncMock()
    monkeypatch.setattr(
        "custom_components.todo_sync.TodoSyncStorage.async_remove", remove
    )
    syncer = Mock()
    syncer.async_start = AsyncMock()
    entry.async_on_unload = Mock()
    monkeypatch.setattr(
        "custom_components.todo_sync.TodoSyncer", lambda _hass, _entry: syncer
    )
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    assert await async_setup_entry(hass, entry)

    remove.assert_awaited_once()
    assert CONF_RESET_SYNC_STATE not in entry.data
    assert entry.data[CONF_LIST_A] == "todo.new_a"
    assert entry.data[CONF_LIST_B] == "todo.new_b"
    syncer.async_start.assert_awaited_once()
