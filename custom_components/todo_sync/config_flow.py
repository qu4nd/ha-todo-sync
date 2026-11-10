"""Config flow for To-do Sync."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import selector

from homeassistant.core import callback

from .const import CONF_INTERVAL, CONF_LIST_A, CONF_LIST_B, DOMAIN, SCAN_INTERVAL_MINUTES

_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="todo"))


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
            if user_input[CONF_LIST_A] == user_input[CONF_LIST_B]:
                errors["base"] = "same_list"
            else:
                await self.async_set_unique_id(
                    "|".join(sorted((user_input[CONF_LIST_A], user_input[CONF_LIST_B])))
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{user_input[CONF_LIST_A]} ⇄ {user_input[CONF_LIST_B]}",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LIST_A): _SELECTOR,
                    vol.Required(CONF_LIST_B): _SELECTOR,
                }
            ),
            errors=errors,
        )


class TodoSyncOptionsFlow(config_entries.OptionsFlow):
    """Configure the periodic sync interval."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_INTERVAL, SCAN_INTERVAL_MINUTES)
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
                    )
                }
            ),
        )
