"""Bidirectional sync between two Home Assistant to-do lists (title + status).

The integration is intentionally centered around TodoSyncer: it reads both lists,
compares them with the last successfully synchronized snapshot, applies the
resulting changes, and persists the new snapshot. Keeping that flow in one place
makes conflict handling and retries consistent for every supported to-do provider.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
from homeassistant.helpers.storage import Store

from .const import (
    CONF_INTERVAL,
    CONF_LIST_A,
    CONF_LIST_B,
    DEBOUNCE_SECONDS,
    DOMAIN,
    SCAN_INTERVAL_MINUTES,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button", "sensor"]
RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 300
MASS_DELETE_MIN = 5
CONFIRM_SECONDS = 360  # longer than the slowest source poll (Alexa: 300 s)
DONE = "completed"
OPEN = "needs_action"
"Bidirectional sync between two Home Assistant to-do lists (title + status).

The integration is intentionally centered around TodoSyncer: it reads both lists,
compares them with the last successfully synchronized snapshot, applies the
resulting changes, and persists the new snapshot. Keeping that flow in one place
makes conflict handling and retries consistent for every supported to-do provider.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
from homeassistant.helpers.storage import Store

from .const import (
    CONF_INTERVAL,
    CONF_LIST_A,
    CONF_LIST_B,
    DEBOUNCE_SECONDS,
    DOMAIN,
    SCAN_INTERVAL_MINUTES,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button", "sensor"]
RETRY_SECONDS = 30
MAX_RETRY_SECONDS = 300
MASS_DELETE_MIN = 5
CONFIRM_SECONDS = 360  # longer than the slowest source poll (Alexa: 300 s)
DONE = "completed"
OPEN = "needs_action"
_QTY_RE = re.compile(
    r"^(.+?)\s+(\d+(?:[.,]\d+)?(?:\s*(?:kg|g|mg|l|ml|cl|dl|stk\.?|stück))?(?:\s+.*)?)$",
    re.IGNORECASE,
)


def _key(summary: str) -> str:
    return summary.strip().casefold()


def _identity(name: str, description: str) -> str:
    """Return a stable, unambiguous identity for a name/details pair."""
    return json.dumps(
        [_key(name), _key(description)], ensure_ascii=False, separators=(",", ":")
    )


class _TodoListReadError(Exception):
    """Raised when fetching either source list fails before sync changes are applied."""


class TodoSyncer:
    """Syncs two lists using a snapshot of the last synced state for diffing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.a: str = entry.data[CONF_LIST_A]
        self.b: str = entry.data[CONF_LIST_B]
        self.interval: int = int(entry.options.get(CONF_INTERVAL, SCAN_INTERVAL_MINUTES))
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        # Last successfully synchronized state, keyed by normalized name + description.
        # Comparing both live lists with this baseline lets us tell which side changed.
        self._snapshot: dict[str, dict] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debounce: CALLBACK_TYPE | None = None
        # Remember the latest list that caused a run; it breaks simultaneous-change ties.
        self._pending_trigger: str | None = None
        self._suspect: tuple[frozenset, float] | None = None
        self._stopped = False
        self._retry_attempt = 0
        self._last_synced_items = 0
        self._sync_deferred = False
        self._status = {
            "state": "idle",
            "last_success": None,
            "last_error": None,
            "synced_items": 0,
            "last_error_type": None,
        }
        self._status_listeners = []

    async def async_start(self) -> None:
        data = await self._store.async_load()
        self._snapshot = self._migrate_snapshot((data or {}).get("snapshot", {}))
        stored_status = (data or {}).get("status", {})
        self._status.update(
            {key: stored_status[key] for key in self._status if key in stored_status}
        )
        # A process cannot still be syncing after Home Assistant has restarted.
        if self._status["state"] == "syncing":
            self._status["state"] = "idle"
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
        return self._status["state"]

    @property
    def status_attributes(self) -> dict:
        return {key: value for key, value in self._status.items() if key != "state"}

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

    @staticmethod
    def _migrate_snapshot(snapshot: dict) -> dict[str, dict]:
        """Upgrade name-keyed snapshots to the name/details identity format."""
        migrated: dict[str, dict] = {}
        for old_key, item in snapshot.items():
            if not isinstance(item, dict) or not item.get("name"):
                migrated[old_key] = item
                continue
            description = (item.get("description") or "").strip()
            key = _identity(item["name"], description)
            migrated[key] = item
        return migrated

    async def _save_store(self) -> None:
        await self._store.async_save(
            {"snapshot": self._snapshot, "status": dict(self._status)}
        )

    async def _set_status(self, state: str, **attributes) -> None:
        self._status.update(state=state, **attributes)
        self._notify_status()
        await self._save_store()

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

    def _ready(self) -> bool:
        for entity_id in (self.a, self.b):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                return False
        return True

    async def _run(self, _now) -> None:
        self._debounce = None
        if self._stopped:
            return
        trigger, self._pending_trigger = self._pending_trigger, None
        if not self._ready():
            # Entities are not loaded yet (e.g. at startup); a state change or retry follows
            _LOGGER.debug("Lists not ready, retrying in %s s", RETRY_SECONDS)
            self._schedule(trigger, RETRY_SECONDS)
            return
        async with self._lock:
            if self._stopped:
                return
            self._last_synced_items = 0
            await self._set_status("syncing", synced_items=0)
            try:
                write_failed = await self._sync(trigger)
            except _TodoListReadError:
                _LOGGER.exception("Could not read a to-do list")
                await self._set_status(
                    "error",
                    last_error=self._now(),
                    last_error_type="TodoListReadError",
                    synced_items=0,
                )
                self._schedule_retry(trigger, "Could not read a to-do list")
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Sync of %s and %s failed", self.a, self.b)
                await self._set_status(
                    "error",
                    last_error=self._now(),
                    last_error_type=type(err).__name__,
                    synced_items=self._last_synced_items,
                )
            else:
                if write_failed:
                    await self._set_status(
                        "error",
                        last_error=self._now(),
                        last_error_type="WriteError",
                        synced_items=self._last_synced_items,
                    )
                    self._schedule_retry(trigger, "One or more list updates failed")
                elif self._sync_deferred:
                    self._retry_attempt = 0
                    await self._set_status("idle", synced_items=0)
                else:
                    self._retry_attempt = 0
                    await self._set_status(
                        "success",
                        last_success=self._now(),
                        synced_items=self._last_synced_items,
                    )

    def _schedule_retry(self, trigger: str | None, reason: str) -> None:
        """Schedule a bounded retry while preserving the most recent change trigger."""
        self._retry_attempt += 1
        delay = min(
            RETRY_SECONDS * 2 ** (self._retry_attempt - 1),
            MAX_RETRY_SECONDS,
        )
        _LOGGER.warning("%s; retrying in %s seconds", reason, delay)
        # Keep the original trigger unless a newer state change arrived while syncing.
        retry_trigger = self._pending_trigger or trigger
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

    def _parse(
        self, entity_id: str, raw: list[dict], known: dict[str, tuple[str, str]]
    ) -> dict[str, dict]:
        items: dict[str, dict] = {}
        supports = self._supports_description(entity_id)
        for item in raw:
            title = item["summary"].strip()
            name, desc = title, (item.get("description") or "").strip()
            if not supports:
                name, desc = self._split_title(title, known)
            if name:
                parsed_item = {
                    "title": title,
                    "name": name,
                    "status": item["status"],
                    "description": desc,
                }
                if item.get("uid"):
                    parsed_item["uid"] = item["uid"]
                items[_identity(name, desc)] = parsed_item
        return items

    @staticmethod
    def _split_title(title: str, known: dict[str, tuple[str, str]]) -> tuple[str, str]:
        """Split a title at its trailing numeric detail; prefer an exact known name/details pair."""
        # Prefer an exact pair learned from the other list or the previous snapshot.
        # Only fall back to the quantity pattern for titles we have never seen before.
        if (hit := known.get(title.casefold())) is not None:
            return hit
        if m := _QTY_RE.match(title):
            return m.group(1).strip(), m.group(2).strip()
        return title, ""

    def _supports_description(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        features = state.attributes.get("supported_features", 0) if state else 0
        return bool(features & TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)

    def _title(self, entity_id: str, name: str, desc: str) -> str:
        # Lists without description support carry the details in the title: "Milch 3"
        if desc and not self._supports_description(entity_id):
            return f"{name} {desc}"
        return name

    @staticmethod
    def _val(item: dict | None):
        return None if item is None else (item["status"], item.get("description", ""))

    async def _call(self, service: str, data: dict) -> None:
        await self.hass.services.async_call("todo", service, data, blocking=True)

    async def _apply(self, entity_id: str, current: dict, key: str, target: dict | None) -> bool:
        existing = current.get(key)

        def service_item(item: dict) -> str:
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
                "uid": None,
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
                existing["uid"] = created_item.get("uid")
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

    def _mass_delete_suspects(
        self, items_a: dict[str, dict], items_b: dict[str, dict]
    ) -> frozenset:
        """Return (list, key) pairs if a list lost most open items at once (likely a faulty read)."""
        # Only compare open items: completed entries are history and are not part
        # of the deletion safety check.
        open_snap = {k for k, s in self._snapshot.items() if s["status"] == OPEN}
        suspects: set = set()
        for entity_id, items in ((self.a, items_a), (self.b, items_b)):
            missing = {k for k in open_snap if k not in items}
            if len(missing) >= MASS_DELETE_MIN and len(missing) * 2 > len(open_snap):
                suspects |= {(entity_id, k) for k in missing}
        return frozenset(suspects)

    def _hold_back(self, suspects: frozenset) -> bool:
        """True while a mass deletion is not yet confirmed (same result for CONFIRM_SECONDS)."""
        now = time.monotonic()
        if not suspects:
            self._suspect = None
            return False
        if self._suspect is None or self._suspect[0] != suspects:
            self._suspect = (suspects, now)
        waited = now - self._suspect[1]
        if waited >= CONFIRM_SECONDS:
            return False
        _LOGGER.warning(
            "Most open items vanished from a list at once; holding back and re-checking "
            "in %d s (accepted if the result stays the same)",
            CONFIRM_SECONDS - waited,
        )
        return True

    async def _sync(self, trigger: str | None) -> bool:
        self._sync_deferred = False
        # Read both lists completely before applying anything. A failed read must
        # never be interpreted as an empty list or advance the persisted snapshot.
        raw = {}
        for entity_id in (self.a, self.b):
            try:
                raw[entity_id] = await self._fetch(entity_id)
            except Exception as err:  # noqa: BLE001
                raise _TodoListReadError(entity_id) from err
        # Providers without description support encode details after the first
        # word in the title. This deterministic rule keeps identity consistent
        # regardless of which provider supplied the item.
        items_a = self._parse(self.a, raw[self.a], {})
        items_b = self._parse(self.b, raw[self.b], {})
        # A sudden disappearance of most open items can be a transient provider/API
        # read failure. Do not propagate those deletions until the same result is seen
        # again after the confirmation window.
        if self._hold_back(self._mass_delete_suspects(items_a, items_b)):
            self._sync_deferred = True
            self._schedule(trigger, CONFIRM_SECONDS + 10)
            return False
        snap = self._snapshot
        _LOGGER.debug(
            "Sync (trigger=%s): %s has %d items, %s has %d items, snapshot %d",
            trigger, self.a, len(items_a), self.b, len(items_b), len(snap),
        )
        new_snap: dict[str, dict] = {}
        write_failed = False
        self._last_synced_items = 0

        # Three-way diff: compare each side (A/B) with the last synced value (snapshot).
        # This distinguishes a one-sided edit from a conflict where both sides changed.
        for key in set(items_a) | set(items_b) | set(snap):
            a, b, s = items_a.get(key), items_b.get(key), snap.get(key)
            sa, sb, ss = (self._val(x) for x in (a, b, s))

            if sa == sb:
                if a:
                    new_snap[key] = {k: v for k, v in a.items() if k != "uid"}
                continue

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
            _LOGGER.debug(
                "List item change detected; action=%s destination=%s",
                "copy" if source else "delete", dest_id,
            )
            # Completed entries are provider history, not active list content. Avoid
            # recreating or deleting them on the opposite side when one side omits them.
            if (source is None and dest and dest["status"] == DONE) or (
                dest is None and source and source["status"] == DONE
            ):
                _LOGGER.debug("Skipped synchronization of completed item history")
                continue
            try:
                changed = await self._apply(dest_id, dest_items, key, source)
                if changed:
                    self._last_synced_items += 1
            except Exception:  # noqa: BLE001
                # Keep the old baseline for this item so the next run retries it. Other
                # items can still sync; _run schedules a bounded retry after this pass.
                write_failed = True
                _LOGGER.exception("Applying a list item to %s failed, will retry", dest_id)
                if s:
                    new_snap[key] = s
                continue
            if source:
                # Provider UIDs are local to each list and must not enter the shared snapshot.
                new_snap[key] = {k: v for k, v in source.items() if k != "uid"}

        self._snapshot = new_snap
        # Persist even if unload started during this run: list changes have already been
        # applied, so the stored baseline must match them before a reloaded instance starts.
        await self._save_store()
        return write_failed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    syncer = TodoSyncer(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = syncer
    await syncer.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await hass.data[DOMAIN].pop(entry.entry_id).async_stop()
    return ok
    @staticmethod
    def _split_title(title: str, known: dict[str, tuple[str, str]] | None = None) -> tuple[str, str]:
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
        # Lists without description support carry the details in the title: "Milch 3"
        if desc and not self._supports_description(entity_id):
            return f"{name} {desc}"
        return name

    @staticmethod
    def _val(item: dict | None):
        return None if item is None else (item["status"], item.get("description", ""))

    async def _call(self, service: str, data: dict) -> None:
        await self.hass.services.async_call("todo", service, data, blocking=True)

    async def _apply(self, entity_id: str, current: dict, key: str, target: dict | None) -> bool:
        existing = current.get(key)

        def service_item(item: dict) -> str:
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
                "uid": None,
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
                existing["uid"] = created_item.get("uid")
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

    def _mass_delete_suspects(
        self, items_a: dict[str, dict], items_b: dict[str, dict]
    ) -> frozenset:
        """Return (list, key) pairs if a list lost most open items at once (likely a faulty read)."""
        # Only compare open items: completed entries are history and are not part
        # of the deletion safety check.
        open_snap = {k for k, s in self._snapshot.items() if s["status"] == OPEN}
        suspects: set = set()
        for entity_id, items in ((self.a, items_a), (self.b, items_b)):
            missing = {k for k in open_snap if k not in items}
            if len(missing) >= MASS_DELETE_MIN and len(missing) * 2 > len(open_snap):
                suspects |= {(entity_id, k) for k in missing}
        return frozenset(suspects)

    def _hold_back(self, suspects: frozenset) -> bool:
        """True while a mass deletion is not yet confirmed (same result for CONFIRM_SECONDS)."""
        now = time.monotonic()
        if not suspects:
            self._suspect = None
            return False
        if self._suspect is None or self._suspect[0] != suspects:
            self._suspect = (suspects, now)
        waited = now - self._suspect[1]
        if waited >= CONFIRM_SECONDS:
            return False
        _LOGGER.warning(
            "Most open items vanished from a list at once; holding back and re-checking "
            "in %d s (accepted if the result stays the same)",
            CONFIRM_SECONDS - waited,
        )
        return True

    async def _sync(self, trigger: str | None) -> bool:
        self._sync_deferred = False
        # Read both lists completely before applying anything. A failed read must
        # never be interpreted as an empty list or advance the persisted snapshot.
        raw = {}
        for entity_id in (self.a, self.b):
            try:
                raw[entity_id] = await self._fetch(entity_id)
            except Exception as err:  # noqa: BLE001
                raise _TodoListReadError(entity_id) from err
        # Exact "name" and "name details" titles known from description-capable lists / last sync
        # Lists without description support encode details in the title. Remember exact
        # name/details pairs from the snapshot and capable lists before parsing either side,
        # so a previously known title is not split differently on the other side.
        known: dict[str, tuple[str, str]] = {}

        def learn(name: str, desc: str) -> None:
            known[_key(name)] = (name, "")
            if desc:
                known[_key(f"{name} {desc}")] = (name, desc)

        for s in self._snapshot.values():
            learn(s["name"], s.get("description", ""))
        for e, entries in raw.items():
            if self._supports_description(e):
                for i in entries:
                    learn(i["summary"].strip(), (i.get("description") or "").strip())
        items_a = self._parse(self.a, raw[self.a], known)
        items_b = self._parse(self.b, raw[self.b], known)
        # A sudden disappearance of most open items can be a transient provider/API
        # read failure. Do not propagate those deletions until the same result is seen
        # again after the confirmation window.
        if self._hold_back(self._mass_delete_suspects(items_a, items_b)):
            self._sync_deferred = True
            self._schedule(trigger, CONFIRM_SECONDS + 10)
            return False
        snap = self._snapshot
        _LOGGER.debug(
            "Sync (trigger=%s): %s has %d items, %s has %d items, snapshot %d",
            trigger, self.a, len(items_a), self.b, len(items_b), len(snap),
        )
        new_snap: dict[str, dict] = {}
        write_failed = False
        self._last_synced_items = 0

        # Three-way diff: compare each side (A/B) with the last synced value (snapshot).
        # This distinguishes a one-sided edit from a conflict where both sides changed.
        for key in set(items_a) | set(items_b) | set(snap):
            a, b, s = items_a.get(key), items_b.get(key), snap.get(key)
            sa, sb, ss = (self._val(x) for x in (a, b, s))

            if sa == sb:
                if a:
                    new_snap[key] = {k: v for k, v in a.items() if k != "uid"}
                continue

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
            _LOGGER.debug(
                "List item change detected; action=%s destination=%s",
                "copy" if source else "delete", dest_id,
            )
            # Completed entries are provider history, not active list content. Avoid
            # recreating or deleting them on the opposite side when one side omits them.
            if (source is None and dest and dest["status"] == DONE) or (
                dest is None and source and source["status"] == DONE
            ):
                _LOGGER.debug("Skipped synchronization of completed item history")
                continue
            try:
                changed = await self._apply(dest_id, dest_items, key, source)
                if changed:
                    self._last_synced_items += 1
            except Exception:  # noqa: BLE001
                # Keep the old baseline for this item so the next run retries it. Other
                # items can still sync; _run schedules a bounded retry after this pass.
                write_failed = True
                _LOGGER.exception("Applying a list item to %s failed, will retry", dest_id)
                if s:
                    new_snap[key] = s
                continue
            if source:
                # Provider UIDs are local to each list and must not enter the shared snapshot.
                new_snap[key] = {k: v for k, v in source.items() if k != "uid"}

        self._snapshot = new_snap
        # Persist even if unload started during this run: list changes have already been
        # applied, so the stored baseline must match them before a reloaded instance starts.
        await self._save_store()
        return write_failed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    syncer = TodoSyncer(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = syncer
    await syncer.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await hass.data[DOMAIN].pop(entry.entry_id).async_stop()
    return ok

