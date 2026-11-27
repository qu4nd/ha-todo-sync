"""Tests for the To-do Sync config flow."""

import pytest

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.todo_sync.const import (
    CONF_INTERVAL,
    CONF_LIST_A,
    CONF_LIST_B,
    CONF_REMOVE_DUPLICATES,
    CONF_RESET_SYNC_STATE,
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
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.options[CONF_INTERVAL] == SCAN_INTERVAL_MINUTES
    assert entry.options[CONF_REMOVE_DUPLICATES] is True
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



@pytest.mark.asyncio
async def test_reconfigure_updates_existing_entry_and_preserves_options(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="todo.list_a|todo.list_b",
        title="todo.list_a ⇄ todo.list_b",
        data={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_b"},
        options={
            CONF_INTERVAL: 30,
            CONF_REMOVE_DUPLICATES: False,
            CONF_SPLIT_TITLE: False,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set("todo.list_a", "0")
    hass.states.async_set("todo.list_b", "0")
    hass.states.async_set("todo.list_c", "0")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_c"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert entry.data[CONF_LIST_A] == "todo.list_a"
    assert entry.data[CONF_LIST_B] == "todo.list_c"
    assert entry.data["reset_sync_state"] is True
    assert entry.unique_id == "todo.list_a|todo.list_b"
    assert entry.options == {
        CONF_INTERVAL: 30,
        CONF_REMOVE_DUPLICATES: False,
        CONF_SPLIT_TITLE: False,
    }


@pytest.mark.asyncio
async def test_reconfigure_rejects_same_list(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="todo.list_a|todo.list_b",
        data={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_b"},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_a"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "same_list"}


@pytest.mark.asyncio
async def test_reconfigure_rejects_non_todo_entity(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="todo.list_a|todo.list_b",
        data={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_b"},
    )
    entry.add_to_hass(hass)
    hass.states.async_set("todo.list_a", "0")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "sensor.other"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_entity"}


@pytest.mark.asyncio
async def test_reconfigure_rejects_missing_entity(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="todo.list_a|todo.list_b",
        data={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_b"},
    )
    entry.add_to_hass(hass)
    hass.states.async_set("todo.list_a", "0")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.missing"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_found"}


@pytest.mark.asyncio
async def test_reconfigure_rejects_pair_already_used_by_another_entry(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="todo.list_a|todo.list_b",
        data={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_b"},
    )
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="todo.list_c|todo.list_d",
        data={CONF_LIST_A: "todo.list_c", CONF_LIST_B: "todo.list_d"},
    )
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    for entity_id in ("todo.list_a", "todo.list_b", "todo.list_c", "todo.list_d"):
        hass.states.async_set(entity_id, "0")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LIST_A: "todo.list_d", CONF_LIST_B: "todo.list_c"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_LIST_A] == "todo.list_a"
    assert entry.data[CONF_LIST_B] == "todo.list_b"



@pytest.mark.asyncio
async def test_setup_rejects_an_existing_pair_in_reverse_order(
    hass, enable_custom_integrations
):
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="todo.list_a|todo.list_b",
        data={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_b"},
    )
    existing.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_LIST_A: "todo.list_b",
            CONF_LIST_B: "todo.list_a",
            CONF_INTERVAL: SCAN_INTERVAL_MINUTES,
            CONF_REMOVE_DUPLICATES: False,
            CONF_SPLIT_TITLE: True,
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1



@pytest.mark.asyncio
async def test_reconfigure_same_pair_in_reverse_order_keeps_sync_state(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="todo.list_a|todo.list_b",
        data={CONF_LIST_A: "todo.list_a", CONF_LIST_B: "todo.list_b"},
        options={
            CONF_INTERVAL: 45,
            CONF_REMOVE_DUPLICATES: True,
            CONF_SPLIT_TITLE: False,
        },
    )
    entry.add_to_hass(hass)
    hass.states.async_set("todo.list_a", "0")
    hass.states.async_set("todo.list_b", "0")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_LIST_A: "todo.list_b", CONF_LIST_B: "todo.list_a"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert CONF_RESET_SYNC_STATE not in entry.data
    assert entry.options == {
        CONF_INTERVAL: 45,
        CONF_REMOVE_DUPLICATES: True,
        CONF_SPLIT_TITLE: False,
    }
