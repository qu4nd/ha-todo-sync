"""Unit tests for the bidirectional synchronization logic."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync import (
    MAX_RETRY_SECONDS,
    RETRY_SECONDS,
    TodoSyncer,
    _TodoListReadError,
)
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

    write_failed = await syncer._sync("todo.a")

    syncer._apply.assert_awaited_once()
    assert write_failed is True
    assert syncer._snapshot == {"milch": old}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trigger", "fetch_results", "destination"),
    [
        (
            "todo.a",
            [[], [{"summary": "Milch", "status": "needs_action", "description": ""}]],
            "todo.b",
        ),
        (
            "todo.b",
            [[{"summary": "Milch", "status": "needs_action", "description": ""}], []],
            "todo.a",
        ),
    ],
)
async def test_deleting_open_item_is_synced(syncer, trigger, fetch_results, destination):
    old = item("Milch")
    syncer._snapshot = {"milch": old}
    syncer._fetch = AsyncMock(side_effect=fetch_results)
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync(trigger)

    syncer._apply.assert_awaited_once_with(destination, {"milch": old}, "milch", None)
    assert syncer._snapshot == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trigger", "status_a", "status_b", "destination", "target"),
    [
        ("todo.a", "completed", "needs_action", "todo.b", "todo.a"),
        ("todo.b", "needs_action", "completed", "todo.a", "todo.b"),
    ],
)
async def test_status_change_is_synced_from_triggering_list(
    syncer, trigger, status_a, status_b, destination, target
):
    old = item("Milch")
    changed_a = item("Milch", status=status_a)
    changed_b = item("Milch", status=status_b)
    syncer._snapshot = {"milch": old}
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Milch", "status": status_a, "description": ""}],
            [{"summary": "Milch", "status": status_b, "description": ""}],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync(trigger)

    source = changed_a if target == "todo.a" else changed_b
    destination_items = {"milch": changed_b if destination == "todo.b" else changed_a}
    syncer._apply.assert_awaited_once_with(destination, destination_items, "milch", source)
    assert syncer._snapshot == {"milch": source}


@pytest.mark.asyncio
async def test_deleting_completed_item_keeps_history_on_other_list(syncer):
    completed = item("Milch", status="completed")
    syncer._snapshot = {"milch": completed}
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Milch", "status": "completed", "description": ""}],
            [],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync("todo.b")

    syncer._apply.assert_not_awaited()
    assert syncer._snapshot == {}


def test_mass_delete_suspects_require_minimum_count_and_majority(syncer):
    syncer._snapshot = {f"item {i}": item(f"item {i}") for i in range(8)}
    current_a = {f"item {i}": item(f"item {i}") for i in range(3)}
    current_b = dict(syncer._snapshot)

    suspects = syncer._mass_delete_suspects(current_a, current_b)

    assert suspects == frozenset(("todo.a", f"item {i}") for i in range(3, 8))


@pytest.mark.parametrize("total, missing", [(8, 4), (10, 5), (8, 3)])
def test_mass_delete_suspects_ignore_results_below_threshold(syncer, total, missing):
    syncer._snapshot = {
        f"item {i}": item(f"item {i}") for i in range(total)
    }
    current_a = {
        f"item {i}": item(f"item {i}") for i in range(total - missing)
    }
    current_b = dict(syncer._snapshot)

    assert syncer._mass_delete_suspects(current_a, current_b) == frozenset()


def test_mass_delete_hold_requires_confirmation_window(syncer):
    suspects = frozenset({("todo.a", "milk")})
    with patch("custom_components.todo_sync.time.monotonic", side_effect=[100.0, 459.0, 460.0]):
        assert syncer._hold_back(suspects) is True
        assert syncer._hold_back(suspects) is True
        assert syncer._hold_back(suspects) is False


def test_changed_mass_delete_result_restarts_confirmation(syncer):
    first = frozenset({("todo.a", "milk")})
    second = frozenset({("todo.a", "milk"), ("todo.a", "bread")})
    with patch("custom_components.todo_sync.time.monotonic", side_effect=[100.0, 200.0]):
        assert syncer._hold_back(first) is True
        assert syncer._hold_back(second) is True

    assert syncer._suspect == (second, 200.0)



@pytest.mark.asyncio
@pytest.mark.parametrize("failed_entity", ["todo.a", "todo.b"])
async def test_failed_list_read_keeps_snapshot_and_does_not_apply_changes(
    syncer, failed_entity
):
    old = item("Milch")
    syncer._snapshot = {"milch": old}
    async def fetch(entity_id):
        if entity_id == failed_entity:
            raise RuntimeError("temporary provider error")
        return [
            {"summary": "Milch", "status": "needs_action", "description": ""}
        ]

    syncer._fetch = AsyncMock(side_effect=fetch)
    syncer._apply = AsyncMock()

    with pytest.raises(_TodoListReadError, match=failed_entity):
        await syncer._sync("todo.a")

    assert syncer._snapshot == {"milch": old}
    syncer._apply.assert_not_awaited()
    syncer._store.async_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_read_schedules_bounded_exponential_retry(syncer):
    syncer._ready = lambda: True
    syncer._sync = AsyncMock(side_effect=_TodoListReadError("todo.b"))
    syncer._schedule = lambda _trigger, delay: scheduled.append(delay)
    scheduled = []

    await syncer._run(None)
    await syncer._run(None)
    await syncer._run(None)

    assert scheduled == [RETRY_SECONDS, RETRY_SECONDS * 2, RETRY_SECONDS * 4]
    assert syncer._retry_attempt == 3


@pytest.mark.asyncio
async def test_successful_sync_resets_read_retry_backoff(syncer):
    syncer._ready = lambda: True
    syncer._retry_attempt = 4
    syncer._sync = AsyncMock()

    await syncer._run(None)

    assert syncer._retry_attempt == 0


@pytest.mark.asyncio
async def test_failed_read_does_not_schedule_retry_after_stop(syncer):
    syncer._stopped = True
    syncer._sync = AsyncMock(side_effect=_TodoListReadError("todo.a"))
    syncer._schedule = AsyncMock()

    await syncer._run(None)

    syncer._schedule.assert_not_called()



@pytest.mark.asyncio
async def test_failed_write_schedules_bounded_exponential_retry(syncer):
    syncer._ready = lambda: True
    syncer._sync = AsyncMock(return_value=True)
    scheduled = []
    syncer._schedule = lambda trigger, delay: scheduled.append((trigger, delay))

    for _ in range(7):
        await syncer._run(None)

    assert [delay for _, delay in scheduled] == [
        30, 60, 120, 240, MAX_RETRY_SECONDS, MAX_RETRY_SECONDS,
        MAX_RETRY_SECONDS,
    ]
    assert syncer._retry_attempt == 7


@pytest.mark.asyncio
async def test_failed_write_retry_preserves_newer_trigger(syncer):
    syncer._ready = lambda: True
    syncer._pending_trigger = "todo.a"
    scheduled = []

    async def fail_write(_trigger):
        syncer._pending_trigger = "todo.b"
        return True

    syncer._sync = AsyncMock(side_effect=fail_write)
    syncer._schedule = lambda trigger, delay: scheduled.append((trigger, delay))

    await syncer._run(None)

    assert scheduled == [("todo.b", RETRY_SECONDS)]


@pytest.mark.asyncio
async def test_successful_sync_resets_write_retry_backoff(syncer):
    syncer._ready = lambda: True
    syncer._retry_attempt = 5
    syncer._sync = AsyncMock(return_value=False)

    await syncer._run(None)

    assert syncer._retry_attempt == 0
