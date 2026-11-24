"""Tests for the To-do Sync config flow."""

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.todo_sync.const import (
    CONF_INTERVAL,
    CONF_LIST_A,
    CONF_LIST_B,
    CONF_REMOVE_DUPLICATES,
    CONF_SPLIT_TITLE,
    DOMAIN,
    SCAN_INTERVAL_MINUTES,
)


@pytest.mark.asyncio
async def test_setup_stores_lists_as_data_and_settings_as_options(
    hass, enable_custom_integrations
):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_LIST_A: "todo.list_a",
            CONF_LIST_B: "todo.list_b",
            CONF_INTERVAL: 15,
            CONF_REMOVE_DUPLICATES: True,
            CONF_SPLIT_TITLE: False,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data == {
        CONF_LIST_A: "todo.list_a",
        CONF_LIST_B: "todo.list_b",
    }
    assert entry.options == {
        CONF_INTERVAL: 15,
        CONF_REMOVE_DUPLICATES: True,
        CONF_SPLIT_TITLE: False,
    }


@pytest.mark.asyncio
async def test_setup_defaults_are_preserved(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_LIST_A: "todo.list_a",
            CONF_LIST_B: "todo.list_b",
            CONF_INTERVAL: SCAN_INTERVAL_MINUTES,
            CONF_REMOVE_DUPLICATES: False,
            CONF_SPLIT_TITLE: True,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.options[CONF_INTERVAL] == SCAN_INTERVAL_MINUTES
    assert entry.options[CONF_REMOVE_DUPLICATES] is False
    assert entry.options[CONF_SPLIT_TITLE] is True


@pytest.mark.asyncio
async def test_options_flow_can_change_setup_settings(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_LIST_A: "todo.list_a",
            CONF_LIST_B: "todo.list_b",
            CONF_INTERVAL: SCAN_INTERVAL_MINUTES,
            CONF_REMOVE_DUPLICATES: False,
            CONF_SPLIT_TITLE: True,
        },
    )
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    assert options_result["type"] is FlowResultType.FORM

    options_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"],
        user_input={
            CONF_INTERVAL: 30,
            CONF_REMOVE_DUPLICATES: True,
            CONF_SPLIT_TITLE: False,
        },
    )

    assert options_result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_INTERVAL: 30,
        CONF_REMOVE_DUPLICATES: True,
        CONF_SPLIT_TITLE: False,
    }


@pytest.mark.asyncio
async def test_setup_rejects_the_same_list_twice(hass, enable_custom_integrations):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_LIST_A: "todo.list_a",
            CONF_LIST_B: "todo.list_a",
            CONF_INTERVAL: SCAN_INTERVAL_MINUTES,
            CONF_REMOVE_DUPLICATES: False,
            CONF_SPLIT_TITLE: True,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "same_list"}
