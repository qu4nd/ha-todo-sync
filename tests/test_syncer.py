"""Unit tests for the bidirectional synchronization logic."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync import (
    MAX_RETRY_SECONDS,
    RETRY_SECONDS,
    TodoSyncer,
    _TodoListReadError,
    _identity,
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
    instance._store.async_delay_save = Mock()
    return instance


def item(name, status="needs_action", description=""):
    return {
        "title": name,
        "name": name,
        "status": status,
        "description": description,
    }



def test_pending_write_masks_stale_destination_read_until_provider_catches_up(syncer):
    key = _identity("Milk", "")
    before = item("Milk")
    expected = item("Milk", status="completed")
    syncer._track_pending_write("todo.b", key, before, expected)
    items_a = {key: expected}
    items_b = {key: before}

    syncer._resolve_pending_writes(items_a, items_b)

    assert syncer._val(items_b[key]) == syncer._val(expected)
    assert syncer._pending_key("todo.b", key) in syncer._pending_writes

    # Once the provider exposes the expected value, the expectation is acknowledged.
    syncer._resolve_pending_writes(items_a, items_b)
    assert syncer._pending_writes == {}


def test_pending_write_does_not_hide_a_genuine_conflicting_edit(syncer):
    key = _identity("Milk", "")
    before = item("Milk")
    expected = item("Milk", status="completed")
    genuine_edit = item("Milk", description="oat")
    syncer._track_pending_write("todo.b", key, before, expected)
    items_a = {key: expected}
    items_b = {key: genuine_edit}

    syncer._resolve_pending_writes(items_a, items_b)

    assert items_b[key] == genuine_edit
    assert syncer._pending_writes == {}


def test_pending_write_expires(syncer):
    key = _identity("Milk", "")
    syncer._track_pending_write("todo.b", key, item("Milk"), item("Milk", status="completed"))
    pending_id = syncer._pending_key("todo.b", key)
    syncer._pending_writes[pending_id]["expires"] = 0

    syncer._resolve_pending_writes({key: item("Milk", status="completed")}, {key: item("Milk")})

    assert syncer._pending_writes == {}


@pytest.mark.asyncio
async def test_unchanged_store_payload_is_not_written(syncer):
    syncer._last_saved_data = syncer._store_data()

    await syncer._save_store()

    syncer._store.async_save.assert_not_awaited()


def test_split_title_uses_first_word_as_identity(syncer):
    assert syncer._split_title("Milch 0,5 l") == ("Milch", "0,5 l")
    assert syncer._split_title("Eier 10") == ("Eier", "10")
    assert syncer._split_title("gelbe Tomaten") == ("gelbe", "Tomaten")
    assert syncer._split_title("rote Zwiebeln") == ("rote", "Zwiebeln")
    assert syncer._split_title("Buttermilch") == ("Buttermilch", "")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Pizza 4 Käse", ("Pizza", "4 Käse")),
        ("Pizza 4 Stagioni", ("Pizza", "4 Stagioni")),
        ("Formel 1", ("Formel", "1")),
        ("Windows 11 Pro", ("Windows", "11 Pro")),
        ("gelbe Tomaten", ("gelbe", "Tomaten")),
        ("rote Zwiebeln", ("rote", "Zwiebeln")),
    ],
)
def test_split_title_uses_first_word_for_numbered_and_text_details(syncer, title, expected):
    assert syncer._split_title(title, {}) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Milch 3", ("Milch", "3")),
        ("Käse 200 g", ("Käse", "200 g")),
        ("Milch 0,5l", ("Milch", "0,5l")),
        ("Wasser 1,5 l", ("Wasser", "1,5 l")),
    ],
)
def test_split_title_extracts_numeric_quantities(syncer, title, expected):
    assert syncer._split_title(title, {}) == expected


def test_split_title_is_independent_of_known_title_hints(syncer):
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
        _identity("Milch", "3"): {
            "title": "Milch",
            "name": "Milch",
            "status": "needs_action",
            "description": "3",
        }
    }


def test_parse_keeps_same_name_with_different_descriptions(syncer):
    syncer._supports_description = lambda _entity_id: True

    parsed = syncer._parse(
        "todo.a",
        [
            {"summary": "Pizza", "status": "needs_action", "description": "4 Käse", "uid": "uid-1"},
            {"summary": "Pizza", "status": "needs_action", "description": "4 Stagioni", "uid": "uid-2"},
        ],
        {},
    )

    assert set(parsed) == {
        _identity("Pizza", "4 Käse"),
        _identity("Pizza", "4 Stagioni"),
    }
    assert parsed[_identity("Pizza", "4 Käse")]["uid"] == "uid-1"
    assert parsed[_identity("Pizza", "4 Stagioni")]["uid"] == "uid-2"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Pizza mit viel Liebe", ("Pizza", "mit viel Liebe")),
        ("Buttermilch", ("Buttermilch", "")),
    ],
)
def test_split_title_handles_text_details(syncer, title, expected):
    assert syncer._split_title(title, {}) == expected


def test_parse_alexa_titles_uses_known_name_details_pairs(syncer):
    syncer._supports_description = lambda _entity_id: False
    known = {
        "pizza 4 käse": ("Pizza", "4 Käse"),
        "pizza 4 stagioni": ("Pizza", "4 Stagioni"),
    }

    parsed = syncer._parse(
        "todo.b",
        [
            {"summary": "Pizza 4 Käse", "status": "needs_action", "uid": "alexa-1"},
            {"summary": "Pizza 4 Stagioni", "status": "needs_action", "uid": "alexa-2"},
        ],
        known,
    )

    assert set(parsed) == {
        _identity("Pizza", "4 Käse"),
        _identity("Pizza", "4 Stagioni"),
    }


def test_migrate_preserves_name_and_numeric_detail_pair(syncer):
    old = {
        "pizza": {
            "title": "Pizza 4 Käse",
            "name": "Pizza",
            "status": "needs_action",
            "description": "4 Käse",
        }
    }

    assert syncer._migrate_snapshot(old) == {
        _identity("Pizza", "4 Käse"): old["pizza"]
    }


def test_migrate_name_keyed_snapshot(syncer):
    old = {"pizza": item("Pizza", description="4 Käse")}

    assert syncer._migrate_snapshot(old) == {
        _identity("Pizza", "4 Käse"): item("Pizza", description="4 Käse")
    }


def test_parse_title_only_provider_splits_pizza_details(syncer):
    syncer._supports_description = lambda _entity_id: False

    parsed = syncer._parse(
        "todo.a",
        [
            {"summary": "Pizza 4 Käse", "status": "needs_action", "uid": "pizza-cheese"},
            {"summary": "Pizza 4 Stagioni", "status": "needs_action", "uid": "pizza-stagioni"},
        ],
        {},
    )

    assert set(parsed) == {
        _identity("Pizza", "4 Käse"),
        _identity("Pizza", "4 Stagioni"),
    }


@pytest.mark.asyncio
async def test_sync_keeps_numbered_names_distinct_across_provider_types(syncer):
    syncer._fetch = AsyncMock(
        side_effect=[
            [
                {"summary": "Pizza 4 Käse", "status": "needs_action", "uid": "a1"},
                {"summary": "Pizza 4 Stagioni", "status": "needs_action", "uid": "a2"},
            ],
            [],
        ]
    )
    syncer._supports_description = lambda entity_id: entity_id == "todo.b"
    syncer._apply = AsyncMock()

    await syncer._sync("todo.a")

    assert syncer._apply.await_count == 2
    assert set(syncer._snapshot) == {
        _identity("Pizza", "4 Käse"),
        _identity("Pizza", "4 Stagioni"),
    }


@pytest.mark.asyncio
async def test_sync_preserves_two_items_with_same_name(syncer):
    syncer._fetch = AsyncMock(
        side_effect=[
            [
                {"summary": "Pizza", "status": "needs_action", "description": "4 Käse", "uid": "a1"},
                {"summary": "Pizza", "status": "needs_action", "description": "4 Stagioni", "uid": "a2"},
            ],
            [],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync("todo.a")

    assert syncer._apply.await_count == 2
    assert set(syncer._snapshot) == {
        _identity("Pizza", "4 Käse"),
        _identity("Pizza", "4 Stagioni"),
    }


@pytest.mark.asyncio
async def test_delete_uses_uid_for_duplicate_summary(syncer):
    syncer._call = AsyncMock()
    current = {
        _identity("Pizza", "4 Käse"): item("Pizza", description="4 Käse"),
        _identity("Pizza", "4 Stagioni"): item("Pizza", description="4 Stagioni"),
    }
    current[_identity("Pizza", "4 Käse")]["uid"] = "bring-1"
    current[_identity("Pizza", "4 Stagioni")]["uid"] = "bring-2"

    await syncer._apply("todo.a", current, _identity("Pizza", "4 Käse"), None)

    syncer._call.assert_awaited_once_with(
        "remove_item", {"entity_id": "todo.a", "item": "bring-1"}
    )


@pytest.mark.asyncio
async def test_update_uses_uid_for_duplicate_summary(syncer):
    syncer._supports_description = lambda _entity_id: True
    syncer._call = AsyncMock()
    current = {
        _identity("Pizza", "4 Käse"): {
            **item("Pizza", description="4 Käse"),
            "uid": "bring-1",
        },
        _identity("Pizza", "4 Stagioni"): {
            **item("Pizza", description="4 Stagioni"),
            "uid": "bring-2",
        },
    }
    target = item("Pizza", status="completed", description="4 Käse")

    await syncer._apply("todo.a", current, _identity("Pizza", "4 Käse"), target)

    syncer._call.assert_awaited_once_with(
        "update_item",
        {"entity_id": "todo.a", "item": "bring-1", "status": "completed"},
    )


@pytest.mark.asyncio
async def test_new_completed_item_is_updated_by_resolved_uid(syncer):
    syncer._supports_description = lambda _entity_id: True
    syncer._call = AsyncMock()
    syncer._fetch = AsyncMock(
        return_value=[
            {"summary": "Pizza", "description": "4 Käse", "status": "needs_action", "uid": "new-pizza"}
        ]
    )
    target = item("Pizza", status="completed", description="4 Käse")

    await syncer._apply("todo.a", {}, _identity("Pizza", "4 Käse"), target)

    assert syncer._call.await_args_list[0].args == (
        "add_item",
        {"entity_id": "todo.a", "item": "Pizza", "description": "4 Käse"},
    )
    assert syncer._call.await_args_list[1].args == (
        "update_item",
        {"entity_id": "todo.a", "item": "new-pizza", "status": "completed"},
    )


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

    syncer._apply.assert_awaited_once_with("todo.b", {}, _identity("Milch", "3"), source)
    assert syncer._snapshot == {_identity("Milch", "3"): source}
    syncer._store.async_save.assert_awaited_once_with({
        "snapshot": {_identity("Milch", "3"): source},
        "status": syncer._persisted_status,
        "pending_writes": {
            syncer._pending_key("todo.b", _identity("Milch", "3")): {
                "entity_id": "todo.b", "key": _identity("Milch", "3"),
                "before": None, "expected": ["needs_action", "3"],
                "item": {"title": "Milch", "name": "Milch", "status": "needs_action", "description": "3"},
                "expires": syncer._pending_writes[syncer._pending_key("todo.b", _identity("Milch", "3"))]["expires"],
            }
        },
    })


@pytest.mark.asyncio
async def test_periodic_conflict_defaults_to_list_a(syncer):
    old = item("Milch", description="3")
    changed_a = item("Milch", status="completed", description="3")
    changed_b = item("Milch", description="3")
    syncer._snapshot = {_identity("Milch", "3"): old}
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Milch", "status": "completed", "description": "3"}],
            [{"summary": "Milch", "status": "needs_action", "description": "3"}],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync(None)

    syncer._apply.assert_awaited_once_with("todo.b", {_identity("Milch", "3"): changed_b}, _identity("Milch", "3"), changed_a)
    assert syncer._snapshot == {_identity("Milch", "3"): changed_a}


@pytest.mark.asyncio
async def test_triggering_list_wins_conflict(syncer):
    old = item("Milch", description="3")
    changed_a = item("Milch", description="3")
    changed_b = item("Milch", status="completed", description="3")
    syncer._snapshot = {_identity("Milch", "3"): old}
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Milch", "status": "needs_action", "description": "3"}],
            [{"summary": "Milch", "status": "completed", "description": "3"}],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync("todo.b")

    syncer._apply.assert_awaited_once_with("todo.a", {_identity("Milch", "3"): changed_a}, _identity("Milch", "3"), changed_b)
    assert syncer._snapshot == {_identity("Milch", "3"): changed_b}


@pytest.mark.asyncio
async def test_completed_history_is_not_recreated(syncer):
    completed = item("Milch", status="completed")
    syncer._snapshot = {_identity("Milch", ""): completed}
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
    old = item("Milch", description="3")
    changed = item("Milch", status="completed", description="3")
    syncer._snapshot = {_identity("Milch", "3"): old}
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Milch", "status": "completed", "description": "3"}],
            [{"summary": "Milch", "status": "needs_action", "description": "3"}],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock(side_effect=RuntimeError("temporary service error"))

    write_failed = await syncer._sync("todo.a")

    syncer._apply.assert_awaited_once()
    assert write_failed is True
    assert syncer._snapshot == {_identity("Milch", "3"): old}
    assert syncer._pending_writes == {}


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
    syncer._snapshot = {_identity("Milch", ""): old}
    syncer._fetch = AsyncMock(side_effect=fetch_results)
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync(trigger)

    syncer._apply.assert_awaited_once_with(destination, {_identity("Milch", ""): old}, _identity("Milch", ""), None)
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
    syncer._snapshot = {_identity("Milch", ""): old}
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
    destination_items = {_identity("Milch", ""): changed_b if destination == "todo.b" else changed_a}
    syncer._apply.assert_awaited_once_with(destination, destination_items, _identity("Milch", ""), source)
    assert syncer._snapshot == {_identity("Milch", ""): source}


@pytest.mark.asyncio
async def test_deleting_completed_item_keeps_history_on_other_list(syncer):
    completed = item("Milch", status="completed")
    syncer._snapshot = {_identity("Milch", ""): completed}
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
    syncer._snapshot = {_identity("Milch", ""): old}
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

    assert syncer._snapshot == {_identity("Milch", ""): old}
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
    syncer._sync = AsyncMock(return_value=False)

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
