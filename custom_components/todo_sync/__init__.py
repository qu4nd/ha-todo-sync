"""Home Assistant entry points for the To-do Sync integration."""

from __future__ import annotations

import asyncio
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .syncer import TodoSyncer

PLATFORMS = ["button", "sensor"]
_CARD_REGISTERED = f"{DOMAIN}_card_registered"
_CARD_LOCK = f"{DOMAIN}_card_registration_lock"
_CARD_URL = "/api/todo_sync/ha-todo-card.js"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve and register the Lovelace card once per Home Assistant instance."""
    lock = hass.data.setdefault(_CARD_LOCK, asyncio.Lock())
    async with lock:
        if hass.data.get(_CARD_REGISTERED):
            return

        card_path = Path(__file__).parent / "www" / "ha-todo-card.js"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(_CARD_URL, str(card_path), False)]
        )
        add_extra_js_url(hass, _CARD_URL)
        hass.data[_CARD_REGISTERED] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the synchronization entry and register its frontend card."""
    await _async_register_card(hass)

    syncer = TodoSyncer(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = syncer
    await syncer.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await hass.data[DOMAIN].pop(entry.entry_id).async_stop()
    return ok
