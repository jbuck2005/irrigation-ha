"""Tests for zone valves, the run action and status polling, against a fake irrigationd."""

import asyncio
from datetime import timedelta

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.irrigation.status import MAX_FAILED_POLLS, STATUS_INTERVAL

from .conftest import TOKEN

ZONE_1 = "valve.irrigation_zone_1"
ZONE_2 = "valve.irrigation_zone_2"


async def poll(hass, times=1):
    """Move time on so the status poller runs `times` more times."""
    for _ in range(times):
        async_fire_time_changed(hass, dt_util.utcnow() + STATUS_INTERVAL + timedelta(seconds=1))
        # A timed poll is a background task, which async_block_till_done doesn't
        # wait for, so give its executor job time to finish. Waiting for every
        # background task would hang on a running zone's countdown.
        await hass.async_block_till_done()
        await asyncio.sleep(0.05)
        await hass.async_block_till_done()


async def test_one_valve_per_zone(hass, loaded):
    """Each configured zone gets a closed valve and a run time number."""
    for zone in range(1, 5):
        assert hass.states.get(f"valve.irrigation_zone_{zone}").state == "closed"
        assert hass.states.get(f"number.irrigation_zone_{zone}_default_duration") is not None
    assert hass.states.get("valve.irrigation_zone_5") is None


async def test_open_runs_for_the_zone_default(hass, loaded, daemon):
    """Opening a valve runs it for that zone's default run time."""
    await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_2}, blocking=True)
    assert daemon.commands[-1] == "ZONE=2 TIME=120"
    state = hass.states.get(ZONE_2)
    assert state.state == "open"
    assert state.attributes["remaining"] == 120


async def test_close_sends_a_stop(hass, loaded, daemon):
    """Closing a valve sends TIME=0."""
    await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    await hass.services.async_call("valve", "close_valve", {"entity_id": ZONE_1}, blocking=True)
    assert daemon.commands[-1] == "ZONE=1 TIME=0"
    assert hass.states.get(ZONE_1).state == "closed"


async def test_run_action_with_duration(hass, loaded, daemon):
    """irrigation.run sends the given duration."""
    await hass.services.async_call(
        "irrigation", "run", {"entity_id": ZONE_1, "duration": 45}, blocking=True
    )
    assert daemon.commands[-1] == "ZONE=1 TIME=45"


@pytest.mark.parametrize("duration", [0, 5, 7201])
async def test_run_action_refuses_out_of_range(hass, loaded, daemon, duration):
    """irrigation.run never sends a stop or an over-long run by mistake."""
    sent = len(daemon.commands)
    with pytest.raises(Exception):
        await hass.services.async_call(
            "irrigation", "run", {"entity_id": ZONE_1, "duration": duration}, blocking=True
        )
    assert not any(c.startswith("ZONE=") for c in daemon.commands[sent:])


async def test_refused_command_is_an_error_without_the_token(hass, loaded, daemon):
    """A refused command fails the action, and the reply shown has no token in it."""
    daemon.fail_with = f"ERR refused ZONE=1 TIME=300 TOKEN={TOKEN}"
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    assert "refused" in str(err.value)
    assert TOKEN not in str(err.value)
    assert hass.states.get(ZONE_1).state == "closed"


async def test_poll_shows_a_run_started_elsewhere(hass, loaded, daemon):
    """A zone started outside Home Assistant shows as open after the next poll."""
    daemon.run(3, 90)
    await poll(hass)
    state = hass.states.get("valve.irrigation_zone_3")
    assert state.state == "open"
    assert 85 <= state.attributes["remaining"] <= 90

    daemon.run(3, 0)
    await poll(hass)
    assert hass.states.get("valve.irrigation_zone_3").state == "closed"


@pytest.mark.parametrize(
    "failure",
    [OSError("unreachable"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), "ERR invalid token"],
    ids=["network", "bad-bytes", "refused"],
)
async def test_unavailable_after_failed_polls(hass, loaded, daemon, caplog, failure):
    """Zones go unavailable after repeated failed polls, whatever the failure, and come back."""
    daemon.fail_with = failure
    await poll(hass, MAX_FAILED_POLLS)
    assert hass.states.get(ZONE_1).state == STATE_UNAVAILABLE
    assert TOKEN not in caplog.text

    daemon.fail_with = None
    await poll(hass)
    assert hass.states.get(ZONE_1).state == "closed"


async def test_setting_the_number_changes_the_valve_default(hass, loaded, daemon):
    """Changing a zone's run time number changes what Start sends, and is saved."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.irrigation_zone_1_default_duration", "value": 600},
        blocking=True,
    )
    assert loaded.data["zone_durations"]["1"] == 600
    await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    assert daemon.commands[-1] == "ZONE=1 TIME=600"


async def test_unload(hass, loaded):
    """The entry unloads cleanly."""
    assert await hass.config_entries.async_unload(loaded.entry_id)
    await hass.async_block_till_done()
