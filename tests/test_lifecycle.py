"""Integration lifecycle regression tests."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync import (
    _async_reload,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.todo_sync.const import CONF_LIST_A, CONF_LIST_B, DOMAIN
from custom_components.todo_sync.syncer import TodoSyncer


@pytest.fixture
def entry():
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LIST_A: "todo.a", CONF_LIST_B: "todo.b"},
    )


@pytest.mark.asyncio
async def test_setup_starts_and_registers_syncer(hass, entry, monkeypatch):
    syncer = Mock()
    syncer.async_start = AsyncMock()
    monkeypatch.setattr("custom_components.todo_sync.TodoSyncer", lambda _hass, _entry: syncer)
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    assert await async_setup_entry(hass, entry)

    assert hass.data[DOMAIN][entry.entry_id] is syncer
    syncer.async_start.assert_awaited_once()
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, ["button", "sensor"]
    )


@pytest.mark.asyncio
async def test_unload_failure_keeps_syncer_running(hass, entry):
    syncer = Mock()
    syncer.async_stop = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = syncer
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    assert not await async_unload_entry(hass, entry)

    syncer.async_stop.assert_not_awaited()
    assert hass.data[DOMAIN][entry.entry_id] is syncer


@pytest.mark.asyncio
async def test_successful_unload_stops_and_removes_syncer(hass, entry):
    syncer = Mock()
    syncer.async_stop = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = syncer
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    assert await async_unload_entry(hass, entry)

    syncer.async_stop.assert_awaited_once()
    assert entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_reload_delegates_to_config_entry_manager(hass, entry):
    hass.config_entries.async_reload = AsyncMock()

    await _async_reload(hass, entry)

    hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_stop_waits_for_in_flight_sync_lock(hass, entry):
    syncer = TodoSyncer(hass, entry)
    syncer._store.async_save = AsyncMock()
    await syncer._lock.acquire()

    stop_task = asyncio.create_task(syncer.async_stop())
    await asyncio.sleep(0)

    assert not stop_task.done()
    assert syncer._stopped is True

    syncer._lock.release()
    await stop_task

    syncer._store.async_save.assert_awaited_once_with(syncer._store_data())
