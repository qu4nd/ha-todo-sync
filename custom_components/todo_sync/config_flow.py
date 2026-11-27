"""Config flow for To-do Sync."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_INTERVAL,
    CONF_LIST_A,
    CONF_LIST_B,
    CONF_REMOVE_DUPLICATES,
    CONF_RESET_SYNC_STATE,
    CONF_SPLIT_TITLE,
    DOMAIN,
    SCAN_INTERVAL_MINUTES,
)

_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="todo"))

def _pair_is_configured(
    hass, list_a: str, list_b: str, *, exclude_entry_id: str | None = None
) -> bool:
    """Check configured pairs independently of the entry's immutable unique ID."""
    selected = frozenset((list_a, list_b))
    return any(
        entry.entry_id != exclude_entry_id
        and frozenset(
            (entry.data.get(CONF_LIST_A), entry.data.get(CONF_LIST_B))
        ) == selected
        for entry in hass.config_entries.async_entries(DOMAIN)
    )

class TodoSyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Select the two lists to keep in sync."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TodoSyncOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            list_a = user_input[CONF_LIST_A]
            list_b = user_input[CONF_LIST_B]
            if list_a == list_b:
                errors["base"] = "same_list"
            elif _pair_is_configured(self.hass, list_a, list_b):
                return self.async_abort(reason="already_configured")
            else:
                await self.async_set_unique_id("|".join(sorted((list_a, list_b))))
                return self.async_create_entry(
                    title=f"{list_a} ⇄ {list_b}",
                    data={
                        CONF_LIST_A: list_a,
                        CONF_LIST_B: list_b,
                    },
                    options={
                        CONF_INTERVAL: user_input[CONF_INTERVAL],
                        CONF_REMOVE_DUPLICATES: user_input[CONF_REMOVE_DUPLICATES],
                        CONF_SPLIT_TITLE: user_input[CONF_SPLIT_TITLE],
                    },
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LIST_A): _SELECTOR,
                    vol.Required(CONF_LIST_B): _SELECTOR,
                    vol.Required(
                        CONF_INTERVAL, default=SCAN_INTERVAL_MINUTES
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=1440,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    ),
                    vol.Required(
                        CONF_REMOVE_DUPLICATES, default=True
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_SPLIT_TITLE, default=True
                    ): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Change the lists associated with an existing config entry."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            list_a = user_input[CONF_LIST_A]
            list_b = user_input[CONF_LIST_B]
            if list_a == list_b:
                errors["base"] = "same_list"
            elif self.hass.states.get(list_a) is None or self.hass.states.get(list_b) is None:
                errors["base"] = "entity_not_found"
            elif _pair_is_configured(
                self.hass, list_a, list_b, exclude_entry_id=entry.entry_id
            ):
                return self.async_abort(reason="already_configured")
            else:
                # The config entry identity and entity unique IDs remain stable.
                # A changed pair must start with a fresh baseline and no old write
                # expectations, otherwise old-list state could affect new lists.
                await self.async_set_unique_id(entry.unique_id)
                self._abort_if_unique_id_mismatch()
                pair_changed = frozenset(
                    (entry.data[CONF_LIST_A], entry.data[CONF_LIST_B])
                ) != frozenset((list_a, list_b))
                data_updates = {
                    CONF_LIST_A: list_a,
                    CONF_LIST_B: list_b,
                }
                if pair_changed:
                    data_updates[CONF_RESET_SYNC_STATE] = True
                return self.async_update_reload_and_abort(
                    entry,
                    title=f"{list_a} ⇄ {list_b}",
                    data_updates=data_updates,
                    reload_even_if_entry_is_unchanged=False,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_LIST_A): _SELECTOR,
                vol.Required(CONF_LIST_B): _SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, entry.data),
            errors=errors,
        )

class TodoSyncOptionsFlow(config_entries.OptionsFlowWithReload):
    """Configure synchronization behavior for this list pair."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_INTERVAL, SCAN_INTERVAL_MINUTES)
        remove_duplicates = self.config_entry.options.get(CONF_REMOVE_DUPLICATES, False)
        split_title = self.config_entry.options.get(CONF_SPLIT_TITLE, True)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INTERVAL, default=current): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=1440,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    ),
                    vol.Required(
                        CONF_REMOVE_DUPLICATES, default=remove_duplicates
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_SPLIT_TITLE, default=split_title
                    ): selector.BooleanSelector(),
                }
            ),
        )
