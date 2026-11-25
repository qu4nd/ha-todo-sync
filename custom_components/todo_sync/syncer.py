"""Runtime coordination and bidirectional to-do synchronization."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from homeassistant.components.todo import TodoListEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    CONF_INTERVAL,
    CONF_LIST_A,
    CONF_LIST_B,
    CONF_REMOVE_DUPLICATES,
    CONF_SPLIT_TITLE,
    DEBOUNCE_SECONDS,
    DOMAIN,
    DONE,
    OPEN,
    PENDING_WRITE_SECONDS,
    SCAN_INTERVAL_MINUTES,
)
from .models import ItemKey, TodoItem
from .policy import (
    CONFIRM_SECONDS,
    EMPTY_LIST_RECHECK_SECONDS,
    MAX_RETRY_SECONDS,
    RETRY_SECONDS,
    EmptyListGuard,
    calculate_retry_delay,
    select_retry_trigger,
)
from .status import SyncState, SyncStatus
from .storage import TodoSyncStorage

_LOGGER = logging.getLogger(__name__)


def _identity(name: str, description: str) -> ItemKey:
    """Build the normalized identity shared by all providers."""
    return ItemKey(name, description)


class _TodoListReadError(Exception):
    """Raised when fetching either source list fails before sync changes are applied."""


class _DuplicateCleanupError(Exception):
    """Raised when duplicate cleanup cannot be completed safely."""

    def __init__(self, entity_id: str, reason: str) -> None:
        super().__init__(reason)
        self.entity_id = entity_id
        self.reason = reason


class _InvalidItemIdentityError(ValueError):
    """Raised when provider data cannot produce a safe, stable item identity."""

    def __init__(self, entity_id: str, reason: str) -> None:
        super().__init__(reason)
        self.entity_id = entity_id
        self.reason = reason


class TodoSyncer:
    """Syncs two lists using a snapshot of the last synced state for diffing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.a: str = entry.data[CONF_LIST_A]
        self.b: str = entry.data[CONF_LIST_B]
        self.interval: int = int(entry.options.get(CONF_INTERVAL, SCAN_INTERVAL_MINUTES))
        # Missing options belong to configurations created before this setting existed;
        # keep their historical behavior. New config flows store the enabled default explicitly.
        self.remove_duplicates = bool(entry.options.get(CONF_REMOVE_DUPLICATES, False))
        self.split_title = bool(entry.options.get(CONF_SPLIT_TITLE, True))
        self._store = TodoSyncStorage(hass, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        # Last successfully synchronized state, keyed by normalized name + description.
        # Comparing both live lists with this baseline lets us tell which side changed.
        # ItemKey keeps normalized name/details identity separate from provider addressing.
        self._snapshot: dict[ItemKey, TodoItem] = {}
        # Expected destination values protect against providers that expose writes late.
        self._pending_writes: dict[str, dict] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debounce: CALLBACK_TYPE | None = None
        # Remember the latest list that caused a run; it breaks simultaneous-change ties.
        self._pending_trigger: str | None = None
        self._empty_list_guard = EmptyListGuard()
        self._stopped = False
        self._retry_attempt = 0
        self._last_synced_items = 0
        self._sync_deferred = False
        self._status = SyncStatus()
        self._status_listeners = []
        # Transient states (notably syncing) stay in memory and are not persisted.
        self._persisted_status = self._status

    async def async_start(self) -> None:
        data = await self._store.async_load()
        self._snapshot = self._store.migrate_snapshot((data or {}).get("snapshot", {}))
        self._pending_writes = (data or {}).get("pending_writes", {})
        # Pending writes use provider-independent identity keys from the previous
        # parsing mode. They cannot safely be resolved after the identity strategy
        # changes, but the snapshot is retained: it lets _prepare_items recognize
        # the same logical entries in their new provider-specific representation.
        if (data or {}).get("split_title", True) != self.split_title:
            self._pending_writes = {}
        now = time.time()
        self._pending_writes = {
            key: value for key, value in self._pending_writes.items()
            if value.get("expires", 0) > now
        }
        self._status = SyncStatus.from_dict((data or {}).get("status", {}))
        # A process cannot still be syncing after Home Assistant has restarted.
        if self._status.state is SyncState.SYNCING:
            self._status = self._status.updated(SyncState.IDLE)
        self._persisted_status = self._status
        await self._save_store()
        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.a, self.b], self._on_change)
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                lambda _now: self._schedule(None, 0),
                timedelta(minutes=self.interval),
            )
        )
        self._schedule(None, 0)

    @property
    def status(self) -> str:
        return self._status.state.value

    @property
    def status_attributes(self) -> dict:
        return self._status.attributes

    @callback
    def async_add_status_listener(self, listener):
        self._status_listeners.append(listener)

        @callback
        def remove_listener():
            self._status_listeners.remove(listener)

        return remove_listener

    @callback
    def _notify_status(self) -> None:
        for listener in tuple(self._status_listeners):
            listener()

    def _store_data(self) -> dict:
        return self._store.serialize(
            self._snapshot,
            self._pending_writes,
            self._persisted_status,
            split_title=self.split_title,
        )

    async def _save_store(self) -> None:
        """Persist the current state through the storage boundary."""
        await self._store.async_save(self._store_data())

    async def _set_status(
        self, state: SyncState | str, *, persist: bool = True, **attributes
    ) -> None:
        self._status = self._status.updated(state, **attributes)
        self._notify_status()
        if persist:
            self._persisted_status = self._status
            self._store.async_delay_save(self._store_data(), 5, self._store_data)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @callback
    def async_sync_now(self) -> None:
        self._schedule(None, 0)

    async def async_stop(self) -> None:
        # A sync that is still running must not re-arm timers after unload
        self._stopped = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._debounce:
            self._debounce()
            self._debounce = None
        # Wait for an in-flight sync so a reloaded instance never overlaps with it
        async with self._lock:
            pass
        await self._save_store()

    @callback
    def _on_change(self, event: Event) -> None:
        self._schedule(event.data["entity_id"], DEBOUNCE_SECONDS)

    @callback
    def _schedule(self, trigger: str | None, delay: float) -> None:
        if self._stopped:
            return
        # The most recent trigger decides conflicts (the list that changed last)
        if trigger:
            self._pending_trigger = trigger
        if self._debounce:
            self._debounce()
        self._debounce = async_call_later(self.hass, delay, self._run)

    def _unavailable_entity(self) -> tuple[str, str] | None:
        for entity_id in (self.a, self.b):
            state = self.hass.states.get(entity_id)
            if state is None:
                return entity_id, "missing"
            if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                return entity_id, state.state
        return None

    def _list_side(self, entity_id: str) -> str:
        """Return a stable, privacy-safe label for one configured list."""
        return "A" if entity_id == self.a else "B"

    def _ready(self) -> bool:
        return self._unavailable_entity() is None

    async def _run(self, _now) -> None:
        self._debounce = None
        if self._stopped:
            return
        trigger, self._pending_trigger = self._pending_trigger, None
        unavailable = self._unavailable_entity() if not self._ready() else None
        if unavailable is not None:
            entity_id, entity_state = unavailable
            changed = (
                self._status.state is not SyncState.WAITING
                or self._status.waiting_entity != entity_id
                or self._status.waiting_state != entity_state
            )
            await self._set_status(
                SyncState.WAITING,
                waiting_entity=entity_id,
                waiting_state=entity_state,
            )
            if changed:
                _LOGGER.warning(
                    "sync_event=list_unavailable category=list_unavailable "
                    "list=%s state=%s action=pause",
                    self._list_side(entity_id),
                    entity_state,
                )
            _LOGGER.debug(
                "sync_event=retry_scheduled category=list_unavailable "
                "delay_seconds=%d",
                RETRY_SECONDS,
            )
            self._schedule(trigger, RETRY_SECONDS)
            return
        async with self._lock:
            if self._stopped:
                return
            self._last_synced_items = 0
            await self._set_status(
                SyncState.SYNCING,
                persist=False,
                synced_items=0,
                waiting_entity=None,
                waiting_state=None,
            )
            try:
                write_failed = await self._sync(trigger)
            except _TodoListReadError as err:
                cause_type = type(err.__cause__).__name__ if err.__cause__ else "UnknownError"
                _LOGGER.error(
                    "sync_event=read_failed category=read_failure list=%s error=%s",
                    self._list_side(err.args[0]) if err.args else "unknown",
                    cause_type,
                )
                await self._set_status(
                    SyncState.ERROR,
                    last_error=self._now(),
                    last_error_type="TodoListReadError",
                    synced_items=0,
                )
                self._schedule_retry(trigger, "read_failure")
            except _DuplicateCleanupError as err:
                _LOGGER.error(
                    "sync_event=duplicate_cleanup_failed category=duplicate_cleanup_failure "
                    "list=%s reason=%s",
                    self._list_side(err.entity_id),
                    err.reason,
                )
                await self._set_status(
                    SyncState.ERROR,
                    last_error=self._now(),
                    last_error_type="DuplicateCleanupError",
                    synced_items=0,
                )
                if err.reason != "duplicate_without_unique_uid":
                    self._schedule_retry(trigger, "duplicate_cleanup_failure")
            except _InvalidItemIdentityError as err:
                _LOGGER.error(
                    "sync_event=invalid_identity category=invalid_identity "
                    "list=%s reason=%s",
                    self._list_side(err.entity_id),
                    err.reason,
                )
                await self._set_status(
                    SyncState.ERROR,
                    last_error=self._now(),
                    last_error_type="InvalidItemIdentityError",
                    synced_items=0,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "sync_event=sync_failed category=unexpected error=%s",
                    type(err).__name__,
                )
                await self._set_status(
                    SyncState.ERROR,
                    last_error=self._now(),
                    last_error_type=type(err).__name__,
                    synced_items=self._last_synced_items,
                )
            else:
                if write_failed:
                    await self._set_status(
                        SyncState.ERROR,
                        last_error=self._now(),
                        last_error_type="WriteError",
                        synced_items=self._last_synced_items,
                    )
                    self._schedule_retry(trigger, "write_failure")
                elif self._sync_deferred:
                    self._retry_attempt = 0
                    await self._set_status(SyncState.HELD_BACK, synced_items=0)
                else:
                    self._retry_attempt = 0
                    await self._set_status(
                        SyncState.SUCCESS,
                        last_success=self._now(),
                        synced_items=self._last_synced_items,
                    )

    def _schedule_retry(self, trigger: str | None, category: str) -> None:
        """Schedule a bounded retry while preserving the most recent change trigger."""
        self._retry_attempt += 1
        delay = calculate_retry_delay(
            self._retry_attempt, RETRY_SECONDS, MAX_RETRY_SECONDS
        )
        _LOGGER.warning(
            "sync_event=retry_scheduled category=%s attempt=%d delay_seconds=%d",
            category,
            self._retry_attempt,
            delay,
        )
        retry_trigger = select_retry_trigger(self._pending_trigger, trigger)
        self._schedule(retry_trigger, delay)

    async def _fetch(self, entity_id: str) -> list[dict]:
        resp = await self.hass.services.async_call(
            "todo",
            "get_items",
            {"entity_id": entity_id},
            blocking=True,
            return_response=True,
        )
        return resp[entity_id]["items"]

    def _duplicate_cleanup_plan(self, entity_id: str, raw: list[dict]) -> list[str]:
        """Return the UIDs of extra open occurrences, grouped by logical identity."""
        supports = self._supports_description(entity_id)
        groups: dict[ItemKey, list[dict]] = {}
        uid_counts: dict[str, int] = {}
        for item in raw:
            if not isinstance(item, dict):
                raise _InvalidItemIdentityError(entity_id, "invalid_item_record")
            uid = item.get("uid")
            if isinstance(uid, str) and uid:
                uid_counts[uid] = uid_counts.get(uid, 0) + 1
            if item.get("status") != OPEN:
                continue
            summary = item.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise _InvalidItemIdentityError(entity_id, "missing_or_empty_summary")
            description = item.get("description")
            if description is None:
                description = ""
            if not isinstance(description, str):
                raise _InvalidItemIdentityError(entity_id, "invalid_description")
            name, details = summary.strip(), description.strip()
            if not supports:
                if self.split_title:
                    name, details = self._split_title(name)
                else:
                    details = ""
            if name:
                groups.setdefault(_identity(name, details), []).append(item)

        duplicates: list[str] = []
        for occurrences in groups.values():
            for duplicate in occurrences[1:]:
                uid = duplicate.get("uid")
                if not isinstance(uid, str) or not uid or uid_counts.get(uid) != 1:
                    raise _DuplicateCleanupError(entity_id, "duplicate_without_unique_uid")
                duplicates.append(uid)
        return duplicates

    async def _cleanup_duplicate_uids(
        self, entity_id: str, raw: list[dict], duplicate_uids: list[str]
    ) -> list[dict]:
        """Complete extra open duplicates by UID and verify the provider reflects it."""
        if not duplicate_uids:
            return raw
        try:
            for uid in duplicate_uids:
                await self._call(
                    "update_item",
                    {"entity_id": entity_id, "item": uid, "status": DONE},
                )
            refreshed = await self._fetch(entity_id)
        except Exception as err:  # noqa: BLE001
            raise _DuplicateCleanupError(entity_id, "duplicate_update_failed") from err

        for uid in duplicate_uids:
            matches = [item for item in refreshed if item.get("uid") == uid]
            if len(matches) > 1 or (matches and matches[0].get("status") != DONE):
                raise _DuplicateCleanupError(entity_id, "duplicate_update_not_reflected")
        return refreshed

    def _parse(self, entity_id: str, raw: list[dict]) -> dict[ItemKey, TodoItem]:
        items: dict[ItemKey, TodoItem] = {}
        supports = self._supports_description(entity_id)
        for item in raw:
            if not isinstance(item, dict):
                raise _InvalidItemIdentityError(entity_id, "invalid_item_record")
            summary = item.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise _InvalidItemIdentityError(entity_id, "missing_or_empty_summary")
            title = summary.strip()
            description = item.get("description")
            if description is None:
                description = ""
            if not isinstance(description, str):
                raise _InvalidItemIdentityError(entity_id, "invalid_description")
            name, desc = title, description.strip()
            if not supports:
                if self.split_title:
                    name, desc = self._split_title(title)
                else:
                    name, desc = title, ""
            if name:
                # Keep the original provider title for safe service addressing;
                # it is not part of cross-provider identity.
                parsed_item: TodoItem = {
                    "title": title,
                    "name": name,
                    "status": item["status"],
                    "description": desc,
                }
                if item.get("uid"):
                    parsed_item["uid"] = item["uid"]
                key = _identity(name, desc)
                existing = items.get(key)
                # Open entries are active list content; completed entries are history.
                # If both exist, never let the history record hide the open entry.
                if existing is None or (
                    existing["status"] == DONE and parsed_item["status"] == OPEN
                ):
                    items[key] = parsed_item
        return items

    @staticmethod
    def _split_title(title: str) -> tuple[str, str]:
        """Use the first word as the item name and everything after it as details."""
        parts = title.strip().split(maxsplit=1)
        if not parts:
            return "", ""
        return parts[0], parts[1] if len(parts) == 2 else ""

    def _supports_description(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        features = state.attributes.get("supported_features", 0) if state else 0
        return bool(features & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

    def _title(self, entity_id: str, name: str, desc: str) -> str:
        # Title-only providers (notably Alexa) carry details in the title. Keep this
        # translation at the provider boundary; the shared ItemKey remains name/details.
        if desc and not self._supports_description(entity_id):
            return f"{name} {desc}"
        return name

    @staticmethod
    def _val(item: TodoItem | None) -> tuple[str, str] | None:
        return None if item is None else (item["status"], item.get("description", ""))

    async def _call(self, service: str, data: dict) -> None:
        await self.hass.services.async_call("todo", service, data, blocking=True)

    async def _apply(
        self,
        entity_id: str,
        current: dict[ItemKey, TodoItem],
        key: ItemKey,
        target: TodoItem | None,
    ) -> bool:
        existing = current.get(key)

        def service_item(item: TodoItem) -> str:
            """Prefer the provider UID; a summary is safe only when it is unique."""
            if item.get("uid"):
                return item["uid"]
            same_title = sum(
                candidate["title"] == item["title"] for candidate in current.values()
            )
            if same_title > 1:
                raise RuntimeError(
                    "Cannot safely address duplicate to-do summaries without item UIDs"
                )
            return item["title"]

        # The key is provider-independent; the stored title/UID below is deliberately
        # provider-specific and is used only to address the destination service.
        # A missing target means the source side deleted this item. Remove it only
        # when it exists on the destination; otherwise there is nothing to apply.
        if target is None:
            if existing:
                await self._call(
                    "remove_item", {"entity_id": entity_id, "item": service_item(existing)}
                )
                return True
            return False
        supports = self._supports_description(entity_id)
        created = existing is None
        if existing is None:
            # Create the item first. Some providers need a follow-up update to set
            # its status, so the common update logic below also handles new items.
            title = self._title(entity_id, target["name"], target["description"])
            previous_uids = {
                item.get("uid") for item in current.values() if item.get("uid")
            }
            data = {"entity_id": entity_id, "item": title}
            if supports and target["description"]:
                data["description"] = target["description"]
            await self._call("add_item", data)
            existing = {
                "title": title,
                "name": target["name"],
                "status": OPEN,
                "description": target["description"],
            }
            # add_item cannot set a completed status. Resolve the newly created
            # item's UID before updating it, so another item with the same summary
            # but different details is never modified by mistake.
            if target["status"] != OPEN:
                refreshed = await self._fetch(entity_id)
                expected_description = target["description"] if supports else ""
                created_item = next(
                    (
                        item for item in refreshed
                        if item["summary"] == title
                        and (item.get("description") or "").strip() == expected_description
                        and (
                            item.get("uid") not in previous_uids
                            if item.get("uid")
                            else not any(
                                current_item["title"] == title
                                for current_item in current.values()
                            )
                        )
                    ),
                    None,
                )
                if created_item is None:
                    raise RuntimeError("Could not safely identify newly created to-do item")
                if created_item.get("uid"):
                    existing["uid"] = created_item["uid"]
        data = {"entity_id": entity_id, "item": service_item(existing)}
        if existing["status"] != target["status"]:
            data["status"] = target["status"]
        if existing["description"] != target["description"]:
            if supports:
                data["description"] = target["description"]
            else:
                data["rename"] = self._title(
                    entity_id, existing["name"], target["description"]
                )
        changed = created or len(data) > 2
        if len(data) > 2:
            await self._call("update_item", data)
        return changed

    def _empty_list_suspects(
        self,
        items_a: dict[ItemKey, TodoItem],
        items_b: dict[ItemKey, TodoItem],
    ) -> frozenset[str]:
        """Return the IDs of completely empty lists while open snapshot items exist."""
        if not any(item["status"] == OPEN for item in self._snapshot.values()):
            return frozenset()
        return frozenset(
            entity_id
            for entity_id, items in ((self.a, items_a), (self.b, items_b))
            if not items
        )

    def _hold_back(self, suspects: frozenset) -> bool:
        """True while an empty-list result is not yet confirmed."""
        previous_suspect = self._empty_list_guard.suspect
        is_new_suspect = (
            bool(suspects)
            and (
                previous_suspect is None
                or previous_suspect[0] != suspects
            )
        )
        should_hold, remaining = self._empty_list_guard.evaluate(
            suspects, time.monotonic(), CONFIRM_SECONDS
        )
        if should_hold and is_new_suspect:
            _LOGGER.warning(
                "sync_event=empty_list_guard category=empty_list_guard "
                "action=hold suspect_lists=%d remaining_seconds=%d",
                len(suspects),
                remaining,
            )
        return should_hold

    @staticmethod
    def _pending_key(entity_id: str, key: ItemKey) -> str:
        return json.dumps(
            [entity_id, key.storage_key], ensure_ascii=False, separators=(",", ":")
        )

    def _track_pending_write(
        self,
        entity_id: str,
        key: ItemKey,
        before: TodoItem | None,
        expected: TodoItem | None,
    ) -> None:
        expected_item = None
        if expected is not None:
            expected_item = {
                "title": self._title(entity_id, expected["name"], expected["description"]),
                "name": expected["name"],
                "status": expected["status"],
                "description": expected["description"],
            }
        self._pending_writes[self._pending_key(entity_id, key)] = {
            "entity_id": entity_id,
            "key": key.storage_key,
            "before": list(self._val(before)) if before is not None else None,
            "expected": list(self._val(expected)) if expected is not None else None,
            "item": expected_item,
            "expires": time.time() + PENDING_WRITE_SECONDS,
        }

    def _resolve_pending_writes(
        self,
        items_a: dict[ItemKey, TodoItem],
        items_b: dict[ItemKey, TodoItem],
    ) -> None:
        """Mask only stale destination reads while the source still has our expected value."""
        now = time.time()
        for pending_id, pending in list(self._pending_writes.items()):
            if pending.get("expires", 0) <= now:
                self._pending_writes.pop(pending_id, None)
                _LOGGER.debug(
                    "sync_event=pending_write_resolved outcome=expired list=%s",
                    self._list_side(pending.get("entity_id", self.a)),
                )
                continue
            entity_id = pending["entity_id"]
            key = ItemKey.from_storage_key(pending["key"])
            destination = items_a if entity_id == self.a else items_b
            source = items_b if entity_id == self.a else items_a
            current_item = destination.get(key)
            current = list(self._val(current_item)) if current_item is not None else None
            source_item = source.get(key)
            source_value = list(self._val(source_item)) if source_item is not None else None
            expected = pending["expected"]
            if current == expected:
                self._pending_writes.pop(pending_id, None)
                outcome = "acknowledged"
            elif current == pending["before"] and source_value == expected:
                if pending["item"] is None:
                    destination.pop(key, None)
                else:
                    destination[key] = dict(pending["item"])
                outcome = "stale_read_masked"
            else:
                # A third value is a genuine edit/conflict, not a stale provider read.
                self._pending_writes.pop(pending_id, None)
                outcome = "conflict"
            _LOGGER.debug(
                "sync_event=pending_write_resolved outcome=%s list=%s",
                outcome,
                self._list_side(entity_id),
            )

    async def _read_lists(self) -> tuple[list[dict], list[dict]]:
        """Read both source lists before making any synchronization changes."""
        raw = {}
        for entity_id in (self.a, self.b):
            try:
                raw[entity_id] = await self._fetch(entity_id)
            except Exception as err:  # noqa: BLE001
                raise _TodoListReadError(entity_id) from err
        return raw[self.a], raw[self.b]

    def _align_items_to_snapshot(
        self, entity_id: str, items: dict[ItemKey, TodoItem]
    ) -> dict[ItemKey, TodoItem]:
        """Keep known logical identities stable across title-splitting changes."""
        supports_description = self._supports_description(entity_id)
        matches_by_item: dict[ItemKey, list[tuple[ItemKey, TodoItem]]] = {}

        for snapshot_key, snapshot_item in self._snapshot.items():
            if snapshot_item["status"] != OPEN:
                continue
            if supports_description:
                matches = [
                    key for key, item in items.items()
                    if item["name"] == snapshot_item["name"]
                    and item["description"] == snapshot_item["description"]
                ]
            else:
                expected_title = self._title(
                    entity_id,
                    snapshot_item["name"],
                    snapshot_item["description"],
                )
                matches = [
                    key for key, item in items.items()
                    if item["title"] == expected_title
                ]

            if len(matches) == 1:
                matches_by_item.setdefault(matches[0], []).append(
                    (snapshot_key, snapshot_item)
                )

        # Only apply one-to-one matches. Ambiguous representations must not be
        # guessed, and a target key occupied by an unrelated item must not be
        # overwritten.
        mappings = {
            parsed_key: candidates[0]
            for parsed_key, candidates in matches_by_item.items()
            if len(candidates) == 1
        }
        mapped_keys = set(mappings)
        mappings = {
            parsed_key: (snapshot_key, snapshot_item)
            for parsed_key, (snapshot_key, snapshot_item) in mappings.items()
            if snapshot_key not in items or snapshot_key in mapped_keys
        }

        aligned = {
            key: item for key, item in items.items() if key not in mappings
        }
        for parsed_key, (snapshot_key, snapshot_item) in mappings.items():
            current = dict(items[parsed_key])
            current["name"] = snapshot_item["name"]
            current["description"] = snapshot_item["description"]
            aligned[snapshot_key] = current

        return aligned

    def _prepare_items(
        self, raw_a: list[dict], raw_b: list[dict]
    ) -> tuple[dict[ItemKey, TodoItem], dict[ItemKey, TodoItem]]:
        """Parse provider data and resolve reads that are stale after our own writes."""
        # Preserve snapshot identities when a title-only provider changes between
        # split and unsplit parsing. Its raw title can still identify the prior
        # logical name/details pair, even though its newly parsed ItemKey differs.
        items_a = self._align_items_to_snapshot(self.a, self._parse(self.a, raw_a))
        items_b = self._align_items_to_snapshot(self.b, self._parse(self.b, raw_b))
        # Completed provider records are history, not active list content. Keep
        # them in the comparison only when the last common snapshot says the item
        # was open; that is the one case where completion is a real state change.
        previously_open = {
            key for key, item in self._snapshot.items() if item["status"] == OPEN
        }
        items_a = {
            key: item for key, item in items_a.items()
            if item["status"] != DONE or key in previously_open
        }
        items_b = {
            key: item for key, item in items_b.items()
            if item["status"] != DONE or key in previously_open
        }
        self._resolve_pending_writes(items_a, items_b)
        return items_a, items_b

    def _defer_if_empty_list_is_suspect(
        self,
        items_a: dict[ItemKey, TodoItem],
        items_b: dict[ItemKey, TodoItem],
        trigger: str | None,
    ) -> bool:
        """Hold back deletions until a transient empty-list result is confirmed."""
        if not self._hold_back(self._empty_list_suspects(items_a, items_b)):
            return False
        self._sync_deferred = True
        self._schedule(trigger, EMPTY_LIST_RECHECK_SECONDS)
        return True

    async def _sync_item(
        self,
        key: ItemKey,
        items_a: dict[ItemKey, TodoItem],
        items_b: dict[ItemKey, TodoItem],
        snapshot: dict[ItemKey, TodoItem],
        trigger: str | None,
        new_snapshot: dict[ItemKey, TodoItem],
    ) -> bool:
        """Resolve and apply one item's three-way diff; return whether its write failed."""
        a, b, s = items_a.get(key), items_b.get(key), snapshot.get(key)
        sa, sb, ss = (self._val(x) for x in (a, b, s))

        if sa == sb:
            if a:
                new_snapshot[key] = {k: v for k, v in a.items() if k != "uid"}
            return False

        changed_a, changed_b = sa != ss, sb != ss
        if changed_a and changed_b:
            # Both sides changed since the snapshot. Prefer the side that triggered
            # this run; periodic runs have no trigger and therefore default to A.
            from_a = trigger != self.b
        else:
            from_a = changed_a

        source, dest_id, dest_items = (
            (a, self.b, items_b) if from_a else (b, self.a, items_a)
        )

        dest = dest_items.get(key)
        source_side = "A" if from_a else "B"
        destination_side = self._list_side(dest_id)
        _LOGGER.debug(
            "sync_event=item_change action=%s source=%s destination=%s",
            "copy" if source else "delete",
            source_side,
            destination_side,
        )
        if changed_a and changed_b:
            _LOGGER.debug(
                "sync_event=conflict_resolved winner=%s destination=%s "
                "reason=both_lists_changed",
                source_side,
                destination_side,
            )
        # Completed entries are provider history, not active list content. Avoid
        # recreating or deleting them on the opposite side when one side omits them.
        if (source is None and dest and dest["status"] == DONE) or (
            dest is None and source and source["status"] == DONE
        ):
            _LOGGER.debug(
                "sync_event=completed_history_skipped source=%s destination=%s",
                source_side,
                destination_side,
            )
            return False
        try:
            previous_destination = dest
            changed = await self._apply(dest_id, dest_items, key, source)
            if changed:
                self._last_synced_items += 1
                self._track_pending_write(dest_id, key, previous_destination, source)
        except Exception as err:  # noqa: BLE001
            # Keep the old baseline for this item so the next run retries it. Other
            # items can still sync; _run schedules a bounded retry after this pass.
            destination_side = "A" if dest_id == self.a else "B"
            _LOGGER.error(
                "sync_event=write_failed category=write_failure "
                "destination=%s error=%s",
                destination_side,
                type(err).__name__,
            )
            if s:
                new_snapshot[key] = s
            return True

        if source:
            # Provider UIDs are local to each list and must not enter the shared snapshot.
            new_snapshot[key] = {k: v for k, v in source.items() if k != "uid"}
        return False

    async def _sync(self, trigger: str | None) -> bool:
        self._sync_deferred = False
        # Read both lists completely before applying anything. A failed read must
        # never be interpreted as an empty list or advance the persisted snapshot.
        raw_a, raw_b = await self._read_lists()
        if self.remove_duplicates:
            # Validate both lists before making any cleanup writes.
            duplicates_a = self._duplicate_cleanup_plan(self.a, raw_a)
            duplicates_b = self._duplicate_cleanup_plan(self.b, raw_b)
            raw_a = await self._cleanup_duplicate_uids(self.a, raw_a, duplicates_a)
            raw_b = await self._cleanup_duplicate_uids(self.b, raw_b, duplicates_b)
        items_a, items_b = self._prepare_items(raw_a, raw_b)

        # A completely empty list can be a transient provider/API read failure.
        # Do not propagate its deletions until the same result is seen again after
        # the confirmation window.
        if self._defer_if_empty_list_is_suspect(items_a, items_b, trigger):
            return False

        self._last_synced_items = 0
        # A completed snapshot is no longer active list content. Only an open
        # baseline is needed to recognize a genuine open -> completed transition.
        snapshot = {
            key: item for key, item in self._snapshot.items()
            if item["status"] == OPEN
        }
        trigger_side = (
            "A" if trigger == self.a else "B" if trigger == self.b else "periodic"
        )
        _LOGGER.debug(
            "sync_event=run_started trigger=%s list_a_items=%d "
            "list_b_items=%d snapshot_items=%d",
            trigger_side,
            len(items_a),
            len(items_b),
            len(snapshot),
        )
        new_snapshot: dict[ItemKey, TodoItem] = {}
        write_failed = False

        # Three-way diff: compare each side (A/B) with the last synced value (snapshot).
        # This distinguishes a one-sided edit from a conflict where both sides changed.
        for key in set(items_a) | set(items_b) | set(snapshot):
            item_write_failed = await self._sync_item(
                key, items_a, items_b, snapshot, trigger, new_snapshot
            )
            write_failed = item_write_failed or write_failed

        self._snapshot = new_snapshot
        # Persist even if unload started during this run: list changes have already been
        # applied, so the stored baseline must match them before a reloaded instance starts.
        await self._save_store()
        return write_failed
