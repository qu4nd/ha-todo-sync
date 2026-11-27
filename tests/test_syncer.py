"""Unit tests for the bidirectional synchronization logic."""

import logging
from itertools import permutations
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.components.todo import TodoListEntityFeature
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync.const import (
    CONF_LIST_A,
    CONF_LIST_B,
    CONF_SPLIT_TITLE,
)
from custom_components.todo_sync.policy import MAX_RETRY_SECONDS, RETRY_SECONDS
from custom_components.todo_sync.storage import TodoSyncStorage
from custom_components.todo_sync.syncer import (
    TodoSyncer,
    _DuplicateCleanupError,
    _InvalidItemIdentityError,
    _TodoListReadError,
    _UnsupportedTodoOperationError,
    _identity,
)


@pytest.fixture
def syncer(hass):
    entry = MockConfigEntry(
        domain="todo_sync",
        data={CONF_LIST_A: "todo.a", CONF_LIST_B: "todo.b"},
    )
    instance = TodoSyncer(hass, entry)
    instance._store._store.async_save = AsyncMock()
    instance._store._store.async_delay_save = Mock()
    return instance


@pytest.mark.asyncio
async def test_fetch_requests_open_items_only(syncer):
    response = {
        "todo.a": {
            "items": [
                {"summary": "Milk", "status": "needs_action", "uid": "open"}
            ]
        }
    }
    with patch.object(
        type(syncer.hass.services), "async_call", autospec=True
    ) as async_call:
        async_call.return_value = response

        items = await syncer._fetch("todo.a")

    assert items == response["todo.a"]["items"]
    async_call.assert_awaited_once_with(
        syncer.hass.services,
        "todo",
        "get_items",
        {"entity_id": "todo.a"},
        blocking=True,
        return_response=True,
    )


def item(name, status="needs_action", description=""):
    return {
        "title": name,
        "name": name,
        "status": status,
        "description": description,
    }



@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "feature", "data"),
    [
        (
            "add_item",
            TodoListEntityFeature.CREATE_TODO_ITEM,
            {"entity_id": "todo.a", "item": "Milk"},
        ),
        (
            "update_item",
            TodoListEntityFeature.UPDATE_TODO_ITEM,
            {"entity_id": "todo.a", "item": "milk-uid", "status": "completed"},
        ),
        (
            "remove_item",
            TodoListEntityFeature.DELETE_TODO_ITEM,
            {"entity_id": "todo.a", "item": "milk-uid"},
        ),
    ],
)
@pytest.mark.parametrize("supported", [True, False])
async def test_call_checks_explicit_write_capabilities(
    syncer, hass, service, feature, data, supported
):
    hass.states.async_set(
        "todo.a",
        "0",
        attributes={"supported_features": int(feature) if supported else 0},
    )
    with patch.object(type(syncer.hass.services), "async_call", autospec=True) as call:
        if supported:
            await syncer._call(service, data)
            call.assert_awaited_once_with(
                syncer.hass.services, "todo", service, data, blocking=True
            )
        else:
            with pytest.raises(_UnsupportedTodoOperationError) as err:
                await syncer._call(service, data)
            assert err.value.service == service
            assert err.value.feature == feature
            call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {"supported_features": None},
        {"supported_features": "unknown"},
    ],
)
@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("add_item", {"entity_id": "todo.a", "item": "Milk"}),
        ("update_item", {"entity_id": "todo.a", "item": "milk-uid", "status": "completed"}),
        ("remove_item", {"entity_id": "todo.a", "item": "milk-uid"}),
    ],
)
async def test_call_does_not_assume_missing_or_invalid_capabilities_are_unsupported(
    syncer, hass, attributes, service, data
):
    hass.states.async_set("todo.a", "0", attributes=attributes)
    with patch.object(type(syncer.hass.services), "async_call", autospec=True) as call:
        await syncer._call(service, data)
    call.assert_awaited_once_with(
        syncer.hass.services, "todo", service, data, blocking=True
    )


@pytest.mark.asyncio
async def test_call_checks_description_feature_when_description_is_sent(syncer, hass):
    hass.states.async_set("todo.a", "0", attributes={"supported_features": 0})
    data = {"entity_id": "todo.a", "item": "Milk", "description": "1 litre"}

    with patch.object(type(syncer.hass.services), "async_call", autospec=True) as call:
        with pytest.raises(_UnsupportedTodoOperationError) as err:
            await syncer._call("add_item", data)

    assert err.value.feature == TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    call.assert_not_awaited()


def test_missing_capability_metadata_preserves_native_descriptions(syncer, hass):
    hass.states.async_set("todo.a", "0", attributes={})

    assert syncer._supports_description("todo.a") is None
    assert syncer._title("todo.a", "Milk", "1 litre") == "Milk"
    assert syncer._parse(
        "todo.a",
        [{"summary": "Milk", "description": "1 litre", "status": "needs_action"}],
    ) == {
        _identity("Milk", "1 litre"): {
            "title": "Milk",
            "name": "Milk",
            "status": "needs_action",
            "description": "1 litre",
        }
    }


@pytest.mark.asyncio
async def test_create_keeps_description_when_capability_metadata_is_missing(syncer, hass):
    hass.states.async_set("todo.a", "0", attributes={})
    syncer._call = AsyncMock()
    target = item("Milk", description="1 litre")

    await syncer._apply("todo.a", {}, _identity("Milk", "1 litre"), target)

    syncer._call.assert_awaited_once_with(
        "add_item",
        {"entity_id": "todo.a", "item": "Milk", "description": "1 litre"},
    )


def test_pending_write_masks_stale_destination_read_until_provider_catches_up(syncer):
    key = _identity("Milk", "")
    before = item("Milk")
    expected = None
    syncer._track_pending_write("todo.b", key, before, expected)
    items_a = {}
    items_b = {key: before}

    syncer._resolve_pending_writes(items_a, items_b)

    assert key not in items_b
    assert syncer._pending_key("todo.b", key) in syncer._pending_writes

    # Once the provider reflects the removal, the expectation is acknowledged.
    syncer._resolve_pending_writes(items_a, items_b)
    assert syncer._pending_writes == {}


def test_pending_write_does_not_hide_a_genuine_conflicting_edit(syncer):
    key = _identity("Milk", "")
    before = item("Milk")
    expected = None
    genuine_edit = item("Milk", description="oat")
    syncer._track_pending_write("todo.b", key, before, expected)
    items_a = {}
    items_b = {key: genuine_edit}

    syncer._resolve_pending_writes(items_a, items_b)

    assert items_b[key] == genuine_edit
    assert syncer._pending_writes == {}


def test_pending_write_expires(syncer):
    key = _identity("Milk", "")
    syncer._track_pending_write("todo.b", key, item("Milk"), None)
    pending_id = syncer._pending_key("todo.b", key)
    syncer._pending_writes[pending_id]["expires"] = 0

    syncer._resolve_pending_writes({}, {key: item("Milk")})

    assert syncer._pending_writes == {}


@pytest.mark.asyncio
async def test_unchanged_store_payload_is_not_written(syncer):
    syncer._store.set_loaded_data(syncer._store_data())

    await syncer._save_store()

    syncer._store._store.async_save.assert_not_awaited()


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
    assert syncer._split_title(title) == expected


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
    assert syncer._split_title(title) == expected


def test_parse_preserves_description_when_supported(syncer, hass):
    syncer._supports_description = lambda _entity_id: True

    parsed = syncer._parse(
        "todo.a",
        [{"summary": "Milch", "status": "needs_action", "description": "3"}],
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
    assert syncer._split_title(title) == expected


def test_parse_alexa_titles_splits_name_and_details(syncer):
    syncer._supports_description = lambda _entity_id: False

    parsed = syncer._parse(
        "todo.b",
        [
            {"summary": "Pizza 4 Käse", "status": "needs_action", "uid": "alexa-1"},
            {"summary": "Pizza 4 Stagioni", "status": "needs_action", "uid": "alexa-2"},
        ],
    )

    assert set(parsed) == {
        _identity("Pizza", "4 Käse"),
        _identity("Pizza", "4 Stagioni"),
    }


def test_title_splitting_is_enabled_for_existing_entries_by_default(syncer):
    assert syncer.split_title is True


@pytest.mark.asyncio
@pytest.mark.parametrize("new_split_title", [False, True])
async def test_changing_title_splitting_preserves_snapshot_and_clears_pending_writes(
    syncer, new_split_title
):
    stored_snapshot = {
        _identity("Milk", "3"): item("Milk", description="3")
    }
    stored_data = {
        "snapshot": {
            '["milk","3"]': stored_snapshot[_identity("Milk", "3")]
        },
        "pending_writes": {"old-identity": {"expires": 9999999999}},
        "status": {},
        "split_title": not new_split_title,
    }
    syncer.split_title = new_split_title
    syncer._store.async_load = AsyncMock(return_value=stored_data)
    syncer._store.set_loaded_data(stored_data)
    syncer._schedule = Mock()

    with (
        patch(
            "custom_components.todo_sync.syncer.async_track_state_change_event",
            return_value=lambda: None,
        ),
        patch(
            "custom_components.todo_sync.syncer.async_track_time_interval",
            return_value=lambda: None,
        ),
    ):
        await syncer.async_start()

    assert syncer._snapshot == stored_snapshot
    assert syncer._pending_writes == {}
    saved_data = syncer._store._store.async_save.await_args.args[0]
    assert saved_data["split_title"] is new_split_title
    assert saved_data["snapshot"] == {
        '["milk","3"]': stored_snapshot[_identity("Milk", "3")]
    }
    assert saved_data["pending_writes"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old_split_title", "new_split_title"),
    [(True, False), (False, True)],
)
async def test_sync_keeps_description_provider_and_title_only_identity_aligned(
    syncer, old_split_title, new_split_title
):
    # The stored snapshot was created with the previous parsing strategy.
    assert old_split_title != new_split_title
    syncer.split_title = new_split_title
    key = _identity("Milk", "3")
    baseline = item("Milk", description="3")
    syncer._snapshot = {key: dict(baseline)}
    syncer._supports_description = lambda entity_id: entity_id == "todo.a"
    syncer._fetch = AsyncMock(side_effect=[
        [{"summary": "Milk", "description": "3", "status": "needs_action"}],
        [{"summary": "Milk 3", "status": "needs_action"}],
        [{"summary": "Milk", "description": "3", "status": "needs_action"}],
        [{"summary": "Milk 3", "status": "needs_action"}],
    ])
    syncer._apply = AsyncMock()

    await syncer._sync("todo.a")
    await syncer._sync("todo.b")

    syncer._apply.assert_not_awaited()
    assert syncer._snapshot == {key: baseline}


def test_title_splitting_can_be_disabled_per_config_entry(hass, syncer):
    entry = MockConfigEntry(
        domain="todo_sync",
        data={CONF_LIST_A: "todo.c", CONF_LIST_B: "todo.d"},
        options={CONF_SPLIT_TITLE: False},
    )
    other_syncer = TodoSyncer(hass, entry)

    assert syncer.split_title is True
    assert other_syncer.split_title is False


def test_parse_keeps_full_title_when_splitting_is_disabled(syncer):
    syncer.split_title = False
    syncer._supports_description = lambda _entity_id: False

    parsed = syncer._parse(
        "todo.a",
        [{"summary": "500 g chicken breast", "status": "needs_action", "uid": "chicken"}],
    )

    assert parsed == {
        _identity("500 g chicken breast", ""): {
            "title": "500 g chicken breast",
            "name": "500 g chicken breast",
            "status": "needs_action",
            "description": "",
            "uid": "chicken",
        }
    }


def test_duplicate_cleanup_does_not_split_titles_when_disabled(syncer):
    syncer.split_title = False
    syncer._supports_description = lambda _entity_id: False
    syncer._split_title = Mock(side_effect=AssertionError("title must not be split"))
    raw = [
        {"summary": "500 g chicken breast", "status": "needs_action", "uid": "one"},
        {"summary": "1 kg potatoes", "status": "needs_action", "uid": "two"},
    ]

    assert syncer._duplicate_cleanup_plan("todo.a", raw) == []
    syncer._split_title.assert_not_called()


def test_migrate_preserves_name_and_numeric_detail_pair(syncer):
    old = {
        "pizza": {
            "title": "Pizza 4 Käse",
            "name": "Pizza",
            "status": "needs_action",
            "description": "4 Käse",
        }
    }

    assert TodoSyncStorage.migrate_snapshot(old) == {
        _identity("Pizza", "4 Käse"): old["pizza"]
    }


def test_migrate_snapshot_drops_provider_local_uid(syncer):
    old = {
        "milk": {
            "title": "Milk 3",
            "name": "Milk",
            "status": "needs_action",
            "description": "3",
            "uid": "bring-local-123",
        }
    }

    migrated = TodoSyncStorage.migrate_snapshot(old)

    assert migrated == {
        _identity("Milk", "3"): {
            "title": "Milk 3",
            "name": "Milk",
            "status": "needs_action",
            "description": "3",
        }
    }


def test_migrate_name_keyed_snapshot(syncer):
    old = {"pizza": item("Pizza", description="4 Käse")}

    assert TodoSyncStorage.migrate_snapshot(old) == {
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
    syncer._store._store.async_save.assert_awaited_once_with({
        "snapshot": {_identity("Milch", "3").storage_key: source},
        "status": syncer._persisted_status.to_dict(),
        "pending_writes": {
            syncer._pending_key("todo.b", _identity("Milch", "3")): {
                "entity_id": "todo.b", "key": _identity("Milch", "3").storage_key,
                "before": None, "expected": ["needs_action", "3"],
                "item": {"title": "Milch", "name": "Milch", "status": "needs_action", "description": "3"},
                "expires": syncer._pending_writes[syncer._pending_key("todo.b", _identity("Milch", "3"))]["expires"],
            }
        },
        "split_title": True,
    })


def test_last_list_change_event_wins_debounce_window(syncer):
    scheduled = []

    def fake_async_call_later(_hass, delay, callback):
        handle = Mock()
        scheduled.append((delay, callback, handle))
        return handle

    with patch("custom_components.todo_sync.syncer.async_call_later", side_effect=fake_async_call_later):
        syncer._schedule("todo.a", 3)
        first_handle = syncer._debounce
        syncer._schedule("todo.b", 3)

    assert first_handle.called
    assert syncer._pending_trigger == "todo.b"
    assert [delay for delay, _, _ in scheduled] == [3, 3]


@pytest.mark.asyncio
async def test_failed_apply_keeps_previous_snapshot_for_retry(syncer):
    old = item("Milch", description="3")
    bread = item("Brot")
    syncer._snapshot = {
        _identity("Milch", "3"): old,
        _identity("Brot", ""): bread,
    }
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Brot", "status": "needs_action", "description": ""}],
            [
                {"summary": "Milch", "status": "needs_action", "description": "3"},
                {"summary": "Brot", "status": "needs_action", "description": ""},
            ],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock(side_effect=RuntimeError("temporary service error"))

    write_failed = await syncer._sync("todo.a")

    syncer._apply.assert_awaited_once()
    assert write_failed is True
    assert syncer._snapshot == {
        _identity("Milch", "3"): old,
        _identity("Brot", ""): bread,
    }
    assert syncer._pending_writes == {}


@pytest.mark.asyncio
async def test_sync_continues_after_write_failure_and_preserves_only_failed_snapshot(
    syncer,
):
    old_items = {
        _identity("Milch", ""): item("Milch"),
        _identity("Brot", ""): item("Brot"),
        _identity("Wasser", ""): item("Wasser"),
    }
    syncer._snapshot = dict(old_items)
    syncer._fetch = AsyncMock(
        side_effect=[
            [{"summary": "Wasser", "status": "needs_action", "description": ""}],
            [
                {"summary": name, "status": "needs_action", "description": ""}
                for name in ("Milch", "Brot", "Wasser")
            ],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    attempted_keys = []

    async def apply_with_one_failure(_entity_id, _current, key, _target):
        attempted_keys.append(key)
        if len(attempted_keys) == 1:
            raise RuntimeError("temporary service error")
        return True

    syncer._apply = AsyncMock(side_effect=apply_with_one_failure)

    write_failed = await syncer._sync("todo.a")

    assert write_failed is True
    expected_write_keys = {
        _identity("Milch", ""),
        _identity("Brot", ""),
    }
    assert set(attempted_keys) == expected_write_keys
    assert syncer._apply.await_count == 2

    failed_key = attempted_keys[0]
    successful_key = attempted_keys[1]
    assert syncer._snapshot == {
        failed_key: old_items[failed_key],
        _identity("Wasser", ""): old_items[_identity("Wasser", "")],
    }
    assert syncer._last_synced_items == 1
    assert syncer._pending_key("todo.b", successful_key) in syncer._pending_writes
    assert syncer._pending_key("todo.b", failed_key) not in syncer._pending_writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("trigger", "fetch_results", "destination"),
    [
        (
            "todo.a",
            [
                [{"summary": "Brot", "status": "needs_action", "description": ""}],
                [
                    {"summary": "Milch", "status": "needs_action", "description": ""},
                    {"summary": "Brot", "status": "needs_action", "description": ""},
                ],
            ],
            "todo.b",
        ),
        (
            "todo.b",
            [
                [
                    {"summary": "Milch", "status": "needs_action", "description": ""},
                    {"summary": "Brot", "status": "needs_action", "description": ""},
                ],
                [{"summary": "Brot", "status": "needs_action", "description": ""}],
            ],
            "todo.a",
        ),
    ],
)
async def test_deleting_open_item_is_synced(syncer, trigger, fetch_results, destination):
    milk = item("Milch")
    bread = item("Brot")
    milk_key = _identity("Milch", "")
    bread_key = _identity("Brot", "")
    syncer._snapshot = {milk_key: milk, bread_key: bread}
    syncer._fetch = AsyncMock(side_effect=fetch_results)
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync(trigger)

    syncer._apply.assert_awaited_once_with(
        destination, {milk_key: milk, bread_key: bread}, milk_key, None
    )
    assert syncer._snapshot == {bread_key: bread}

def test_empty_list_suspects_only_when_a_list_is_completely_empty(syncer):
    syncer._snapshot = {
        _identity("Milk", ""): item("Milk"),
        _identity("Bread", ""): item("Bread"),
    }
    partial_a = {_identity("Bread", ""): item("Bread")}

    assert syncer._empty_list_suspects(partial_a, dict(syncer._snapshot)) == frozenset()
    assert syncer._empty_list_suspects({}, dict(syncer._snapshot)) == frozenset({"todo.a"})


def test_empty_list_suspects_ignore_snapshots_without_open_items(syncer):
    syncer._snapshot = {_identity("Milk", ""): item("Milk", status="completed")}

    assert syncer._empty_list_suspects({}, {}) == frozenset()


def test_empty_list_hold_requires_confirmation_window(syncer):
    suspects = frozenset({"todo.a"})
    with patch("custom_components.todo_sync.syncer.time.monotonic", side_effect=[100.0, 459.0, 460.0]):
        assert syncer._hold_back(suspects) is True
        assert syncer._hold_back(suspects) is True
        assert syncer._hold_back(suspects) is False


def test_changed_empty_list_result_restarts_confirmation(syncer):
    first = frozenset({"todo.a"})
    second = frozenset({"todo.a", "todo.b"})
    with patch("custom_components.todo_sync.syncer.time.monotonic", side_effect=[100.0, 200.0]):
        assert syncer._hold_back(first) is True
        assert syncer._hold_back(second) is True

    assert syncer._empty_list_guard.suspect == (second, 200.0)


def test_empty_list_suspect_clearing_resets_confirmation(syncer):
    suspects = frozenset({"todo.a"})
    with patch("custom_components.todo_sync.syncer.time.monotonic", side_effect=[100.0, 200.0]):
        assert syncer._hold_back(suspects) is True
        assert syncer._hold_back(frozenset()) is False

    assert syncer._empty_list_guard.suspect is None


@pytest.mark.asyncio
async def test_sync_holds_back_when_provider_list_loses_all_three_open_items(syncer):
    items = {
        _identity(name, ""): item(name)
        for name in ("Apfel", "Brot", "Milch")
    }
    syncer._snapshot = dict(items)
    syncer._fetch = AsyncMock(
        side_effect=[
            [],
            [
                {"summary": name, "status": "needs_action"}
                for name in ("Apfel", "Brot", "Milch")
            ],
        ]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()
    scheduled = []
    syncer._schedule = lambda trigger, delay: scheduled.append((trigger, delay))

    await syncer._sync("todo.a")

    syncer._apply.assert_not_awaited()
    assert syncer._snapshot == items
    assert syncer._sync_deferred is True
    assert scheduled == [("todo.a", 370)]


@pytest.mark.asyncio
async def test_sync_holds_back_when_list_is_empty(syncer):
    old = item("Milk")
    syncer._snapshot = {_identity("Milk", ""): old}
    syncer._fetch = AsyncMock(
        side_effect=[[], [{"summary": "Milk", "status": "needs_action"}]]
    )
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()
    scheduled = []
    syncer._schedule = lambda trigger, delay: scheduled.append((trigger, delay))

    await syncer._sync("todo.a")

    syncer._apply.assert_not_awaited()
    assert syncer._snapshot == {_identity("Milk", ""): old}
    assert syncer._sync_deferred is True
    assert scheduled == [("todo.a", 370)]

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
    syncer._store._store.async_save.assert_not_awaited()


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
async def test_unsupported_write_error_is_exposed_in_sync_status(syncer):
    syncer._ready = lambda: True

    async def fail_with_unsupported_operation(_trigger):
        syncer._last_write_error_type = "UnsupportedTodoOperationError"
        return True

    syncer._sync = AsyncMock(side_effect=fail_with_unsupported_operation)
    syncer._schedule = Mock()

    await syncer._run(None)

    assert syncer.status == "error"
    assert (
        syncer.status_attributes["last_error_type"]
        == "UnsupportedTodoOperationError"
    )


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected_state"),
    [(None, "missing"), ("unavailable", "unavailable"), ("unknown", "unknown")],
)
async def test_unready_list_is_exposed_in_status(hass, syncer, state, expected_state):
    hass.states.async_set("todo.a", "ready")
    if state is not None:
        hass.states.async_set("todo.b", state)
    scheduled = []
    syncer._schedule = lambda trigger, delay: scheduled.append((trigger, delay))
    syncer._fetch = AsyncMock()

    await syncer._run(None)

    assert syncer.status == "waiting"
    assert syncer.status_attributes["waiting_entity"] == "todo.b"
    assert syncer.status_attributes["waiting_state"] == expected_state
    assert scheduled == [(None, RETRY_SECONDS)]
    # Missing/unavailable entity checks use the local HA state machine only.
    syncer._fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_unready_list_status_clears_when_list_returns(hass, syncer):
    hass.states.async_set("todo.a", "ready")
    hass.states.async_set("todo.b", "unavailable")
    syncer._schedule = Mock()
    await syncer._run(None)

    assert syncer.status == "waiting"

    hass.states.async_set("todo.b", "0")
    syncer._sync = AsyncMock(return_value=False)
    await syncer._run(None)

    assert syncer.status == "success"
    assert syncer.status_attributes["waiting_entity"] is None
    assert syncer.status_attributes["waiting_state"] is None


@pytest.mark.parametrize(
    ("first", "second", "expected_count"),
    [
        (
            {"summary": " Milk ", "description": " 3 ", "status": "needs_action"},
            {"summary": "milk", "description": "3", "status": "needs_action"},
            1,
        ),
        (
            {"summary": "Milk", "description": "3", "status": "needs_action"},
            {"summary": "Milk", "description": "oat", "status": "needs_action"},
            2,
        ),
        (
            {"summary": "Milk", "description": "3", "status": "needs_action"},
            {"summary": "Bread", "description": "3", "status": "needs_action"},
            2,
        ),
    ],
)
def test_parse_matches_items_by_normalized_name_and_description(
    syncer, first, second, expected_count
):
    syncer._supports_description = lambda _entity_id: True

    parsed = syncer._parse("todo.a", [first, second])

    assert len(parsed) == expected_count


_ORDERING_ITEMS = (
    {
        "summary": "Pizza",
        "description": "4 Käse",
        "status": "needs_action",
        "uid": "pizza-cheese",
    },
    {
        "summary": "Pizza",
        "description": "4 Stagioni",
        "status": "needs_action",
        "uid": "pizza-stagioni",
    },
    {
        "summary": "Milch",
        "description": "1 l",
        "status": "needs_action",
        "uid": "milk",
    },
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("items_a", "items_b"),
    [
        (list(order_a), list(order_b))
        for order_a in permutations(_ORDERING_ITEMS)
        for order_b in permutations(_ORDERING_ITEMS)
    ],
)
async def test_sync_does_not_depend_on_provider_item_order(syncer, items_a, items_b):
    expected_snapshot = {
        _identity("Pizza", "4 Käse"): item("Pizza", description="4 Käse"),
        _identity("Pizza", "4 Stagioni"): item("Pizza", description="4 Stagioni"),
        _identity("Milch", "1 l"): item("Milch", description="1 l"),
    }
    syncer._snapshot = dict(expected_snapshot)
    syncer._fetch = AsyncMock(side_effect=[items_a, items_b])
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock()

    await syncer._sync("todo.a")

    syncer._apply.assert_not_awaited()
    assert syncer._snapshot == expected_snapshot


def test_parse_rejects_invalid_identity_without_exposing_summary(syncer):
    syncer._supports_description = lambda _entity_id: True

    with pytest.raises(_InvalidItemIdentityError, match="missing_or_empty_summary"):
        syncer._parse(
            "todo.a",
            [{"summary": "  ", "status": "needs_action"}],
        )


@pytest.mark.asyncio
async def test_invalid_identity_is_classified_and_logged_without_item_content(
    syncer, caplog
):
    syncer._ready = lambda: True
    syncer._sync = AsyncMock(
        side_effect=_InvalidItemIdentityError("todo.a", "missing_or_empty_summary")
    )
    syncer._schedule = lambda _trigger, _delay: None

    with caplog.at_level(logging.ERROR, logger="custom_components.todo_sync"):
        await syncer._run(None)

    assert syncer.status == "error"
    assert syncer.status_attributes["last_error_type"] == "InvalidItemIdentityError"
    assert "sync_event=invalid_identity" in caplog.text
    assert "category=invalid_identity" in caplog.text
    assert "todo.a" not in caplog.text
    assert "todo.b" not in caplog.text


@pytest.mark.asyncio
async def test_read_failure_logs_category_and_retry_delay_without_entity_id(
    syncer, caplog
):
    syncer._ready = lambda: True
    syncer._sync = AsyncMock(
        side_effect=_TodoListReadError("todo.a")
    )
    syncer._schedule = lambda _trigger, _delay: None

    with caplog.at_level(logging.WARNING, logger="custom_components.todo_sync"):
        await syncer._run(None)

    assert "sync_event=read_failed" in caplog.text
    assert "category=read_failure" in caplog.text
    assert "sync_event=retry_scheduled" in caplog.text
    assert "delay_seconds=30" in caplog.text
    assert "todo.a" not in caplog.text


def test_empty_list_guard_emits_structured_activation_log(syncer, caplog):
    syncer._snapshot = {_identity("Secret item", ""): item("Secret item")}
    with patch(
        "custom_components.todo_sync.syncer.time.monotonic", return_value=100.0
    ):
        with caplog.at_level(logging.WARNING, logger="custom_components.todo_sync"):
            assert syncer._hold_back(frozenset({"todo.a"})) is True

    assert "sync_event=empty_list_guard" in caplog.text
    assert "category=empty_list_guard" in caplog.text
    assert "action=hold" in caplog.text
    assert "Secret item" not in caplog.text
    assert "todo.a" not in caplog.text


@pytest.mark.asyncio
async def test_write_failure_log_has_category_without_item_content(syncer, caplog):
    key = _identity("Secret item", "")
    destination = item("Secret item")
    syncer._supports_description = lambda _entity_id: True
    syncer._apply = AsyncMock(side_effect=RuntimeError("Secret item provider failure"))

    with caplog.at_level(logging.ERROR, logger="custom_components.todo_sync"):
        failed = await syncer._sync_item(
            key,
            {},
            {key: destination},
            {key: destination},
            "todo.a",
            {},
        )

    assert failed is True
    assert "sync_event=write_failed" in caplog.text
    assert "category=write_failure" in caplog.text
    assert "destination=B" in caplog.text
    assert "Secret item" not in caplog.text


@pytest.mark.parametrize(
    ("destination_item", "expected_outcome"),
    [
        (None, "acknowledged"),
        (item("Secret item"), "stale_read_masked"),
        (item("Secret item", description="changed"), "conflict"),
    ],
)
def test_pending_write_resolution_logs_outcome_without_item_content(
    syncer, caplog, destination_item, expected_outcome
):
    key = _identity("Secret item", "")
    before = item("Secret item")
    expected = None
    syncer._track_pending_write("todo.b", key, before, expected)
    items_a = {}
    items_b = {} if destination_item is None else {key: destination_item}

    with caplog.at_level(logging.DEBUG, logger="custom_components.todo_sync"):
        syncer._resolve_pending_writes(items_a, items_b)

    assert f"outcome={expected_outcome}" in caplog.text
    assert "sync_event=pending_write_resolved" in caplog.text
    assert "Secret item" not in caplog.text



@pytest.mark.asyncio
async def test_duplicate_cleanup_completes_extra_exact_matches_by_uid(syncer):
    syncer._supports_description = lambda _entity_id: True
    raw = [
        {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "keep"},
        {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "complete"},
        {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "complete-2"},
        {"summary": "Pizza", "description": "4 Käse", "status": "needs_action", "uid": "pizza-a"},
        {"summary": "Pizza", "description": "4 Stagioni", "status": "needs_action", "uid": "pizza-b"},
    ]
    refreshed = [raw[0], *raw[3:]]
    syncer._call = AsyncMock()
    syncer._fetch = AsyncMock(return_value=refreshed)

    plan = syncer._duplicate_cleanup_plan("todo.a", raw)
    result = await syncer._cleanup_duplicate_uids("todo.a", raw, plan)

    assert plan == ["complete", "complete-2"]
    assert [call.args for call in syncer._call.await_args_list] == [
        ("update_item", {"entity_id": "todo.a", "item": "complete", "status": "completed"}),
        ("update_item", {"entity_id": "todo.a", "item": "complete-2", "status": "completed"}),
    ]
    assert result == refreshed
    syncer._fetch.assert_awaited_once_with("todo.a")


def test_duplicate_cleanup_uses_name_and_description(syncer):
    syncer._supports_description = lambda _entity_id: True
    raw = [
        {"summary": "Pizza", "description": "4 Käse", "status": "needs_action", "uid": "a"},
        {"summary": "Pizza", "description": "4 Stagioni", "status": "needs_action", "uid": "b"},
        {"summary": "Milch", "description": "1 Liter", "status": "needs_action", "uid": "c"},
        {"summary": "Milch", "description": "2 Liter", "status": "needs_action", "uid": "d"},
    ]

    assert syncer._duplicate_cleanup_plan("todo.a", raw) == []


def test_duplicate_cleanup_requires_unique_uid_for_extra_entry(syncer):
    syncer._supports_description = lambda _entity_id: True
    raw = [
        {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "same"},
        {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "same"},
    ]

    with pytest.raises(_DuplicateCleanupError, match="duplicate_without_unique_uid"):
        syncer._duplicate_cleanup_plan("todo.a", raw)


@pytest.mark.asyncio
async def test_duplicate_cleanup_verification_failure_aborts(syncer):
    syncer._call = AsyncMock()
    syncer._fetch = AsyncMock(return_value=[
        {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "duplicate"}
    ])

    with pytest.raises(_DuplicateCleanupError, match="duplicate_update_not_reflected"):
        await syncer._cleanup_duplicate_uids("todo.a", [], ["duplicate"])


@pytest.mark.asyncio
async def test_sync_runs_duplicate_cleanup_before_three_way_diff(syncer):
    syncer.remove_duplicates = True
    syncer._supports_description = lambda _entity_id: True
    first_a = [
        {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "keep"},
        {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "duplicate"},
    ]
    first_b = []
    refreshed_a = [first_a[0]]
    syncer._fetch = AsyncMock(side_effect=[first_a, first_b, refreshed_a])
    syncer._call = AsyncMock()
    syncer._apply = AsyncMock()

    await syncer._sync("todo.a")

    syncer._call.assert_awaited_once_with(
        "update_item",
        {"entity_id": "todo.a", "item": "duplicate", "status": "completed"},
    )
    assert [call.args for call in syncer._fetch.await_args_list] == [
        ("todo.a",),
        ("todo.b",),
        ("todo.a",),
    ]
    syncer._apply.assert_awaited_once()
    applied_item = syncer._apply.await_args.args[3]
    assert applied_item["status"] == "needs_action"
    assert applied_item["uid"] == "keep"


def test_duplicate_cleanup_stays_disabled_for_legacy_entries(syncer):
    assert syncer.remove_duplicates is False


def test_duplicate_cleanup_parses_title_only_provider_identity(syncer):
    syncer._supports_description = lambda _entity_id: False
    raw = [
        {"summary": "Milch 4 Stück", "status": "needs_action", "uid": "one"},
        {"summary": "Milch 4 Stück", "status": "needs_action", "uid": "two"},
        {"summary": "Pizza 4 Käse", "status": "needs_action", "uid": "pizza-a"},
        {"summary": "Pizza 4 Stagioni", "status": "needs_action", "uid": "pizza-b"},
    ]

    assert syncer._duplicate_cleanup_plan("todo.a", raw) == ["two"]


@pytest.mark.asyncio
async def test_duplicate_cleanup_without_duplicates_makes_no_extra_calls(syncer):
    raw = [{"summary": "Milch", "status": "needs_action", "uid": "one"}]
    syncer._call = AsyncMock()
    syncer._fetch = AsyncMock()

    result = await syncer._cleanup_duplicate_uids("todo.a", raw, [])

    assert result is raw
    syncer._call.assert_not_awaited()
    syncer._fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_cleanup_preflights_both_lists_before_writing(syncer):
    syncer.remove_duplicates = True
    syncer._supports_description = lambda _entity_id: True
    syncer._fetch = AsyncMock(side_effect=[
        [
            {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "keep"},
            {"summary": "Milch", "description": "4 Stück", "status": "needs_action", "uid": "extra"},
        ],
        [
            {"summary": "Brot", "description": "", "status": "needs_action"},
            {"summary": "Brot", "description": "", "status": "needs_action"},
        ],
    ])
    syncer._call = AsyncMock()

    with pytest.raises(_DuplicateCleanupError):
        await syncer._sync("todo.a")

    syncer._call.assert_not_awaited()



@pytest.mark.asyncio
async def test_duplicate_cleanup_does_not_propagate_removal_but_later_removal_does(syncer):
    syncer.remove_duplicates = True
    syncer._supports_description = lambda _entity_id: True
    duplicate_a = [
        {"summary": "Salz", "description": "", "status": "needs_action", "uid": "keep"},
        {"summary": "Salz", "description": "", "status": "needs_action", "uid": "duplicate"},
        {"summary": "Brot", "description": "", "status": "needs_action", "uid": "bread-a"},
    ]
    cleaned_a = [duplicate_a[0], duplicate_a[2]]
    open_b = [
        {"summary": "Salz", "description": "", "status": "needs_action", "uid": "bring"},
        {"summary": "Brot", "description": "", "status": "needs_action", "uid": "bread-b"},
    ]
    syncer._fetch = AsyncMock(side_effect=[
        duplicate_a, open_b, cleaned_a,  # First run: cleanup only.
        cleaned_a, open_b,               # Second run: stable, no sync write.
        [duplicate_a[2]], open_b,        # Third run: Salz is no longer open.
    ])
    syncer._call = AsyncMock()
    syncer._apply = AsyncMock()

    await syncer._sync("todo.a")

    syncer._call.assert_awaited_once_with(
        "update_item",
        {"entity_id": "todo.a", "item": "duplicate", "status": "completed"},
    )
    syncer._apply.assert_not_awaited()
    assert syncer._snapshot[_identity("Salz", "")]["status"] == "needs_action"

    await syncer._sync("todo.a")

    syncer._apply.assert_not_awaited()
    assert syncer._snapshot[_identity("Salz", "")]["status"] == "needs_action"

    await syncer._sync("todo.a")

    syncer._apply.assert_awaited_once_with(
        "todo.b",
        {
            _identity("Salz", ""): {**item("Salz"), "uid": "bring"},
            _identity("Brot", ""): {**item("Brot"), "uid": "bread-b"},
        },
        _identity("Salz", ""),
        None,
    )
    assert _identity("Salz", "") not in syncer._snapshot
    assert _identity("Brot", "") in syncer._snapshot
