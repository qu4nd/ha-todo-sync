"""Unit tests for the bidirectional synchronization logic."""

from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync import TodoSyncer
from custom_components.todo_sync.const import CONF_LIST_A, CONF_LIST_B


@pytest.fixture
def syncer(hass):
    entry = MockConfigEntry(
        domain="todo_sync",
        data={CONF_LIST_A: "todo.a", CONF_LIST_B: "todo.b"},
    )
    instance = TodoSyncer(hass, entry)
    instance._store.async_save = AsyncMock()
    return instance


def item(name, status="needs_action", description=""):
    return {
        "title": name,
        "name": name,
        "status": status,
        "description": description,
    }


def test_split_title_extracts_quantity_and_unit(syncer):
    assert syncer._split_title("Milch 0,5 l", {}) == ("Milch", "0,5 l")
    assert syncer._split_title("Eier 10", {}) == ("Eier", "10")


def test_split_title_prefers_exact_known_title(syncer):
    known = {"milch 3": ("Milch", "3")}
    assert syncer._split_title("Milch 3", known) == ("Milch", "3")


def test_parse_preserves_description_when_supported(syncer, hass):
    syncer._supports_description = lambda _entity_id: True

    parsed = syncer._parse(
        "todo.a",
        [{"summary": "Milch", "status": "needs_action", "description": "3"}],
        {},
    )

    assert parsed == {
        "milch": {
            "title": "Milch",
            "name": "Milch",
            "status": "needs_action",
            "description": "3",
        }
    }


@pytest.mark.asyncio
async def test_new_item_on_a_is_applied_to_b(syncer):
    source = item("Milch", description="3")
    syncer._fetch = AsyncMock(
        side_effect=[[
            {"summary": "Milch", "status": "needs_action", "description": "3"}
        ], []]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync("todo.a")

    syncer._apply.assert_awaited_once_with("todo.b", {}, "milch", source)
    assert syncer._snapshot == {"milch": source}
    syncer._store.async_save.assert_awaited_once_with({"snapshot": {"milch": source}})


@pytest.mark.asyncio
async def test_periodic_conflict_defaults_to_list_a(syncer):
    old = item("Milch")
    changed_a = item("Milch", description="3")
    changed_b = item("Milch", description="2")
    syncer._snapshot = {"milch": old}
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Milch", "status": "needs_action", "description": "3"}],
            [{"summary": "Milch", "status": "needs_action", "description": "2"}],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync(None)

    syncer._apply.assert_awaited_once_with("todo.b", {"milch": changed_b}, "milch", changed_a)
    assert syncer._snapshot == {"milch": changed_a}


@pytest.mark.asyncio
async def test_triggering_list_wins_conflict(syncer):
    old = item("Milch")
    changed_a = item("Milch", description="3")
    changed_b = item("Milch", description="2")
    syncer._snapshot = {"milch": old}
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Milch", "status": "needs_action", "description": "3"}],
            [{"summary": "Milch", "status": "needs_action", "description": "2"}],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync("todo.b")

    syncer._apply.assert_awaited_once_with("todo.a", {"milch": changed_a}, "milch", changed_b)
    assert syncer._snapshot == {"milch": changed_b}


@pytest.mark.asyncio
async def test_completed_history_is_not_recreated(syncer):
    completed = item("Milch", status="completed")
    syncer._snapshot = {"milch": completed}
    syncer._fetch = AsyncMock(
        side_effect=[
            [],
            [{"summary": "Milch", "status": "completed", "description": ""}],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync("todo.a")

    syncer._apply.assert_not_awaited()
    assert syncer._snapshot == {}


@pytest.mark.asyncio
async def test_failed_apply_keeps_previous_snapshot_for_retry(syncer):
    old = item("Milch")
    changed = item("Milch", description="3")
    syncer._snapshot = {"milch": old}
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Milch", "status": "needs_action", "description": "3"}],
            [{"summary": "Milch", "status": "needs_action", "description": ""}],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock(side_effect=RuntimeError("temporary service error"))

    await syncer._sync("todo.a")

    syncer._apply.assert_awaited_once()
    assert syncer._snapshot == {"milch": old}
