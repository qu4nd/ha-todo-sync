"""Bidirectional sync between two Home Assistant to-do lists (title + status)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import timedelta

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

PLATFORMS = ["button"]
RETRY_SECONDS = 30
MASS_DELETE_MIN = 5
DONE = "completed"
OPEN = "needs_action"
_QTY_RE = re.compile(r"^(.+?)\s+(\d+(?:[.,]\d+)?(?:\s*[^\W\d_]+\.?)?)$")


def _key(summary: str) -> str:
    return summary.strip().casefold()


class TodoSyncer:
    """Syncs two lists using a snapshot of the last synced state for diffing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.a: str = entry.data[CONF_LIST_A]
        self.b: str = entry.data[CONF_LIST_B]
        self.interval: int = int(entry.options.get(CONF_INTERVAL, SCAN_INTERVAL_MINUTES))
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        self._snapshot: dict[str, dict] = {}  # key -> {"name", "status"}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debounce: CALLBACK_TYPE | None = None
        self._pending_trigger: str | None = None
        self._suspect_runs = 0

    async def async_start(self) -> None:
        data = await self._store.async_load()
        self._snapshot = (data or {}).get("snapshot", {})
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

    @callback
    def async_sync_now(self) -> None:
        self._schedule(None, 0)

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._debounce:
            self._debounce()
            self._debounce = None

    @callback
    def _on_change(self, event: Event) -> None:
        self._schedule(event.data["entity_id"], DEBOUNCE_SECONDS)

    @callback
    def _schedule(self, trigger: str | None, delay: float) -> None:
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
        trigger, self._pending_trigger = self._pending_trigger, None
        if not self._ready():
            # Entities are not loaded yet (e.g. at startup); a state change or retry follows
            _LOGGER.debug("Lists not ready, retrying in %s s", RETRY_SECONDS)
            self._schedule(trigger, RETRY_SECONDS)
            return
        async with self._lock:
            try:
                await self._sync(trigger)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Sync of %s and %s failed", self.a, self.b)

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
                items[_key(name)] = {
                    "title": title,
                    "name": name,
                    "status": item["status"],
                    "description": desc,
                }
        return items

    @staticmethod
    def _split_title(title: str, known: dict[str, tuple[str, str]]) -> tuple[str, str]:
        """Split "Milch 3" into name and details: exact known title first, else a trailing quantity."""
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

    async def _apply(self, entity_id: str, current: dict, key: str, target: dict | None) -> None:
        existing = current.get(key)
        if target is None:
            if existing:
                await self._call(
                    "remove_item", {"entity_id": entity_id, "item": existing["title"]}
                )
            return
        supports = self._supports_description(entity_id)
        if existing is None:
            title = self._title(entity_id, target["name"], target["description"])
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
        data = {"entity_id": entity_id, "item": existing["title"]}
        if existing["status"] != target["status"]:
            data["status"] = target["status"]
        if existing["description"] != target["description"]:
            if supports:
                data["description"] = target["description"]
            else:
                data["rename"] = self._title(
                    entity_id, existing["name"], target["description"]
                )
        if len(data) > 2:
            await self._call("update_item", data)

    def _mass_delete_suspected(
        self, items_a: dict[str, dict], items_b: dict[str, dict]
    ) -> bool:
        """True if a list lost most open items at once (likely a faulty read)."""
        open_snap = {k for k, s in self._snapshot.items() if s["status"] == OPEN}
        for items in (items_a, items_b):
            missing = {k for k in open_snap if k not in items}
            if len(missing) >= MASS_DELETE_MIN and len(missing) * 2 > len(open_snap):
                return True
        return False

    async def _sync(self, trigger: str | None) -> None:
        raw = {e: await self._fetch(e) for e in (self.a, self.b)}
        # Exact "name" and "name details" titles known from description-capable lists / last sync
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
        if self._mass_delete_suspected(items_a, items_b):
            self._suspect_runs += 1
            if self._suspect_runs < 2:
                _LOGGER.warning(
                    "Most open items vanished from a list at once; skipping this run "
                    "and re-checking (a second identical result is accepted)"
                )
                self._schedule(trigger, RETRY_SECONDS)
                return
        self._suspect_runs = 0
        snap = self._snapshot
        _LOGGER.debug(
            "Sync (trigger=%s): %s has %d items, %s has %d items, snapshot %d",
            trigger, self.a, len(items_a), self.b, len(items_b), len(snap),
        )
        _LOGGER.debug("A items: %s", {k: self._val(v) for k, v in items_a.items()})
        _LOGGER.debug("B items: %s", {k: self._val(v) for k, v in items_b.items()})
        new_snap: dict[str, dict] = {}

        for key in set(items_a) | set(items_b) | set(snap):
            a, b, s = items_a.get(key), items_b.get(key), snap.get(key)
            sa, sb, ss = (self._val(x) for x in (a, b, s))

            if sa == sb:
                if a:
                    new_snap[key] = a
                continue

            changed_a, changed_b = sa != ss, sb != ss
            if changed_a and changed_b:
                from_a = trigger != self.b  # conflict: triggering side wins, default A
            else:
                from_a = changed_a

            source, dest_id, dest_items = (
                (a, self.b, items_b) if from_a else (b, self.a, items_a)
            )
            dest = dest_items.get(key)
            _LOGGER.debug(
                "%r: A=%s B=%s snapshot=%s -> %s to %s",
                key, sa, sb, ss, "copy" if source else "delete", dest_id,
            )
            # Completed items are history: never create or delete them on the other side
            if (source is None and dest and dest["status"] == DONE) or (
                dest is None and source and source["status"] == DONE
            ):
                _LOGGER.debug("%r: skipped (completed history)", key)
                continue
            await self._apply(dest_id, dest_items, key, source)
            if source:
                new_snap[key] = source

        self._snapshot = new_snap
        await self._store.async_save({"snapshot": new_snap})


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
        hass.data[DOMAIN].pop(entry.entry_id).async_stop()
    return ok

