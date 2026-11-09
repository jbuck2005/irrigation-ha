"""One test for each race found by the 2026-11-09 race review.

Each sets up the timing by hand, so it fails on the code before its fix.
test_runqueue_interleavings.py finds the same races by trying every order.
"""

import asyncio
import time
from unittest.mock import patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irrigation.const import DOMAIN

from .conftest import ENTRY_DATA

ZONE_1 = "valve.irrigation_zone_1"
ZONE_2 = "valve.irrigation_zone_2"


@pytest.fixture(autouse=True)
def no_gap():
    """Don't wait between zones."""
    with patch("custom_components.irrigation.runqueue.ZONE_GAP", 0):
        yield


async def setup_with(hass, **extra):
    entry = MockConfigEntry(domain=DOMAIN, title="Test Controller", data={**ENTRY_DATA, **extra})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]["queue"]


async def settle(hass, seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        await asyncio.sleep(0.02)
        await hass.async_block_till_done()


def slow(daemon, delays):
    """Make irrigationd take `delays[command]` seconds to handle each listed command, once."""
    real = daemon.handle

    def handle(command, authenticated=False):
        if command in delays:
            time.sleep(delays.pop(command))
        return real(command, authenticated)

    daemon.handle = handle


async def test_cancelled_start_leaves_no_pump_on(hass, daemon):
    """An automation restarted during the master lead doesn't leave the pump on."""
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"pump": {}}})
    queue = await setup_with(hass, master_switch="input_boolean.pump", master_lead=1)
    start = hass.async_create_task(
        hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    )
    await asyncio.sleep(0.3)  # the pump is on, waiting out the lead
    assert hass.states.get("input_boolean.pump").state == "on"
    start.cancel()
    await settle(hass, 1.5)
    pump_on = hass.states.get("input_boolean.pump").state == "on"
    # Either the start went ahead, or nothing is left on
    assert pump_on == bool(daemon.zones[1]), daemon.sent()
    assert (queue.current is not None) == bool(daemon.zones[1]), daemon.sent()


async def test_cancelled_start_doesnt_open_a_second_zone(hass, daemon):
    """A start cancelled while irrigationd answers can't leave its zone open beside the next."""
    queue = await setup_with(hass)
    slow(daemon, {"ZONE=1 TIME=300": 0.5})
    first = hass.async_create_task(queue.async_enqueue(1, 300))
    await asyncio.sleep(0.2)  # zone 1's start is on its way
    first.cancel()
    await asyncio.sleep(0)
    await queue.async_enqueue(2, 300)
    await settle(hass, 1)
    open_zones = [z for z in (1, 2, 3, 4) if daemon.zones[z]]
    assert len(open_zones) == 1, daemon.sent()
    assert queue.current is not None and queue.current.zone == open_zones[0]


async def test_stop_then_start_of_a_zone_leaves_it_running(hass, daemon):
    """A Stop and a start of one zone reach irrigationd in the order they were asked for."""
    queue = await setup_with(hass, master_zone=4, master_lead=0)
    slow(daemon, {"ZONE=2 TIME=0": 0.5})  # the start overtakes the Stop
    stop = hass.async_create_task(
        hass.services.async_call("valve", "close_valve", {"entity_id": ZONE_2}, blocking=True)
    )
    await asyncio.sleep(0.1)
    await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_2}, blocking=True)
    await stop
    await settle(hass)
    assert queue.current is not None and queue.current.zone == 2
    assert daemon.zones[2] and daemon.zones[4], daemon.sent()


async def test_slow_stop_of_an_ending_zone_doesnt_end_the_next(hass, daemon):
    """Stop pressed just as a zone's time ends doesn't also stop the zone after it."""
    queue = await setup_with(hass)
    await queue.async_enqueue(1, 1)
    await queue.async_enqueue(2, 300)
    slow(daemon, {"ZONE=1 TIME=0": 1.5})  # Stop's reply comes after zone 1's time is up
    await asyncio.sleep(0.5)
    await hass.services.async_call("valve", "close_valve", {"entity_id": ZONE_1}, blocking=True)
    await settle(hass, 0.5)
    assert daemon.zones[1] == 0
    assert daemon.zones[2], daemon.sent()
    assert queue.current is not None and queue.current.zone == 2


async def test_start_while_the_same_zone_closes_runs_it_again(hass, daemon):
    """Starting a zone while its last run is closing queues it, rather than taking it for the old run."""
    queue = await setup_with(hass)
    await queue.async_enqueue(1, 1)
    slow(daemon, {"ZONE=1 TIME=0": 0.5})
    await asyncio.sleep(1.2)  # zone 1's time is up and its stop is on its way
    await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    await settle(hass, 1)
    assert daemon.sent()[-1] == "ZONE=1 TIME=300"
    assert daemon.zones[1] and queue.current is not None and queue.current.zone == 1


async def test_stop_all_closes_a_zone_home_assistant_hasnt_seen(hass, daemon):
    """Stop all closes a zone started elsewhere since the last poll."""
    await setup_with(hass)
    daemon.run(3, 60)  # irrigationd's CLI, between polls
    assert hass.states.get("valve.irrigation_zone_3").state == "closed"
    await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    await hass.async_block_till_done()
    assert daemon.zones[3] == 0, daemon.sent()


async def test_stop_all_without_status_still_closes_known_zones(hass, daemon):
    """If irrigationd can't be read after the stops, the zones Home Assistant knew of are still closed."""
    queue = await setup_with(hass)
    await queue.async_enqueue(1, 300)
    real = daemon.handle

    def no_status(command, authenticated=False):
        if command.startswith("STATUS"):
            raise OSError("irrigationd took too long to reply")
        return real(command, authenticated)

    daemon.handle = no_status
    await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    await hass.async_block_till_done()
    assert daemon.zones[1] == 0 and not queue.running


async def test_master_zone_outlasts_a_slow_zone_start(hass, daemon):
    """The master zone's own timer doesn't close it before its zone's when the zone's start is slow."""
    await setup_with(hass, master_zone=4, master_lead=0)
    real = daemon.handle
    ends = {}

    def timed(command, authenticated=False):
        if command.startswith("ZONE=1 TIME=3"):
            time.sleep(1.5)  # a slow network, such as poor Wi-Fi to the Pi
        reply = real(command, authenticated)
        zone, seconds = (int(part.split("=")[1]) for part in command.split()[:2])
        if seconds:
            ends[zone] = time.monotonic() + seconds
        return reply

    daemon.handle = timed
    await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    assert ends[4] >= ends[1], daemon.sent()
