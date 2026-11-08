"""Tests for setup and the Configure dialog."""

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.irrigation.const import DOMAIN

from .conftest import HOST, PORT, TOKEN

USER_INPUT = {
    "name": "Back yard",
    "host": HOST,
    "port": PORT,
    "zones": 3,
    "default_duration": 600,
    "token": TOKEN,
}


async def start_user_flow(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result


async def test_user_flow_creates_entry(hass, daemon):
    """Setup stores the connection and gives every zone the default run time."""
    # Finishing the flow sets the entry up, so its first poll goes to the fake daemon
    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Back yard"
    data = result["data"]
    assert data["host"] == HOST
    assert data["zone_durations"] == {"1": 600, "2": 600, "3": 600}
    assert data["controller_number"] == 1
    await hass.async_block_till_done()
    assert daemon.commands == ["STATUS"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("default_duration", 0),
        ("default_duration", 9),
        ("default_duration", 7201),
        ("port", 0),
        ("port", 70000),
        ("zones", 15),
        ("token", ""),
    ],
)
async def test_user_flow_rejects_out_of_range(hass, field, value):
    """A run time of 0 (a stop), a bad port or too many zones never gets saved."""
    result = await start_user_flow(hass)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, field: value}
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("token", "two words", "invalid_token"),
        ("token", "abc\nZONE=1 TIME=7200", "invalid_token"),
        ("host", "bad host", "invalid_host"),
    ],
)
async def test_user_flow_rejects_unsafe_characters(hass, field, value, error):
    """A space or newline that would split or add a command is refused with a message."""
    result = await start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, field: value}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: error}


async def test_options_blank_token_keeps_the_stored_one(hass, loaded):
    """Saving Configure with the token left blank keeps the existing token."""
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"host": HOST, "port": PORT, "zones": 4, "default_duration": 300, "zone_1_duration": 900},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert loaded.data["token"] == TOKEN
    assert loaded.data["zone_durations"]["1"] == 900


async def test_options_new_token_replaces_it(hass, loaded):
    """A new token entered in Configure replaces the stored one."""
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"host": HOST, "port": PORT, "zones": 4, "default_duration": 300, "token": "new-token"},
    )
    assert loaded.data["token"] == "new-token"


async def test_options_rejects_unsafe_token(hass, loaded):
    """Configure refuses a token with a space, and keeps the old one."""
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"host": HOST, "port": PORT, "zones": 4, "default_duration": 300, "token": "a b"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"token": "invalid_token"}
    assert loaded.data["token"] == TOKEN


async def test_options_rejects_zero_duration(hass, loaded):
    """Configure refuses a default run time of 0."""
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"host": HOST, "port": PORT, "zones": 4, "default_duration": 0},
        )


async def test_options_master_zone_must_exist(hass, loaded):
    """The master zone has to be one of the controller's zones."""
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"host": HOST, "port": PORT, "zones": 4, "default_duration": 300, "master_zone": 5},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"master_zone": "invalid_master_zone"}


async def test_options_sets_master_valve(hass, loaded, daemon):
    """Saving a master zone and lead time stores them and reloads."""
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"host": HOST, "port": PORT, "zones": 4, "default_duration": 300,
         "master_zone": 4, "master_lead": 2},
    )
    await hass.async_block_till_done()
    assert loaded.data["master_zone"] == 4
    assert loaded.data["master_lead"] == 2
    assert loaded.data["master_switch"] is None
    assert hass.data[DOMAIN][loaded.entry_id]["queue"].master_zone == 4
