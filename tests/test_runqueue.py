"""Tests for the run queue: one zone at a time, Stop all, Skip and the master valve."""

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irrigation.const import DOMAIN

from .conftest import ENTRY_DATA

ZONE_1 = "valve.irrigation_zone_1"
ZONE_2 = "valve.irrigation_zone_2"


@pytest.fixture(autouse=True)
def no_gap():
    """Don't wait between zones in tests."""
    with patch("custom_components.irrigation.runqueue.ZONE_GAP", 0):
        yield


def queue_of(hass, entry):
    return hass.data[DOMAIN][entry.entry_id]["queue"]


async def open_zone(hass, entity_id):
    await hass.services.async_call("valve", "open_valve", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def press(hass, entity_id):
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()


async def settle(hass):
    """Let the queue's background task take its next steps."""
    for _ in range(10):
        await asyncio.sleep(0.02)
        await hass.async_block_till_done()


async def test_second_zone_waits_its_turn(hass, loaded, daemon):
    """A start while another zone runs is queued, not sent."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    assert daemon.sent() == ["ZONE=1 TIME=300"]
    assert hass.states.get(ZONE_2).attributes["queued"] is True
    status = hass.states.get("sensor.irrigation_status")
    assert status.state == "running"
    assert status.attributes["current_zone"] == 1
    assert status.attributes["queue"] == [{"zone": 2, "seconds": 120}]
    assert hass.states.get("sensor.irrigation_queued_runs").state == "1"


async def test_skip_closes_the_zone_and_starts_the_next(hass, loaded, daemon):
    """Skip ends the running zone first, then starts the next one."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    await press(hass, "button.irrigation_skip")
    await settle(hass)
    assert daemon.sent() == ["ZONE=1 TIME=300", "ZONE=1 TIME=0", "ZONE=2 TIME=120"]
    assert hass.states.get(ZONE_1).state == "closed"
    assert hass.states.get(ZONE_2).state == "open"


async def test_status_stays_running_between_zones(hass, loaded, daemon):
    """The pause between two zones still counts as running."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    with patch("custom_components.irrigation.runqueue.ZONE_GAP", 0.5):
        await press(hass, "button.irrigation_skip")
        await asyncio.sleep(0.1)
        assert hass.states.get(ZONE_1).state == "closed"
        assert hass.states.get(ZONE_2).state == "closed"
        assert hass.states.get("sensor.irrigation_status").state == "running"
        await asyncio.sleep(0.6)
        await settle(hass)
    assert hass.states.get(ZONE_2).state == "open"
    assert hass.states.get("sensor.irrigation_status").state == "running"


async def test_zones_run_in_order_when_each_ends(hass, loaded, daemon):
    """When a zone's time is up, the next one starts by itself."""
    queue = queue_of(hass, loaded)
    await queue.async_enqueue(1, 1)
    await queue.async_enqueue(2, 1)
    await asyncio.sleep(1.3)
    await settle(hass)
    assert daemon.sent()[:3] == ["ZONE=1 TIME=1", "ZONE=1 TIME=0", "ZONE=2 TIME=1"]
    await asyncio.sleep(1.3)
    await settle(hass)
    assert daemon.sent()[-1] == "ZONE=2 TIME=0"
    assert hass.states.get("sensor.irrigation_status").state == "idle"


async def test_closing_the_running_zone_starts_the_next(hass, loaded, daemon):
    """Closing the running valve is the same as Skip."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    await hass.services.async_call("valve", "close_valve", {"entity_id": ZONE_1}, blocking=True)
    await settle(hass)
    assert daemon.sent()[-1] == "ZONE=2 TIME=120"


async def test_closing_a_waiting_zone_cancels_it(hass, loaded, daemon):
    """Closing a zone that's only waiting takes it out of the queue."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    await hass.services.async_call("valve", "close_valve", {"entity_id": ZONE_2}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(ZONE_2).attributes["queued"] is False
    assert hass.states.get("sensor.irrigation_queued_runs").state == "0"
    assert hass.states.get(ZONE_1).state == "open"


async def test_stop_all_clears_the_queue(hass, loaded, daemon):
    """Stop all closes the running zone and starts nothing else."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    await settle(hass)
    assert "ZONE=2 TIME=120" not in daemon.sent()
    assert hass.states.get(ZONE_1).state == "closed"
    assert hass.states.get("sensor.irrigation_status").state == "idle"
    assert hass.states.get("sensor.irrigation_queued_runs").state == "0"


async def test_stop_all_button_closes_zones_started_elsewhere(hass, loaded, daemon):
    """Stop all also closes a zone that irrigationd's CLI started."""
    daemon.run(3, 60)
    await hass.data[DOMAIN][loaded.entry_id]["status"].async_poll()
    await hass.async_block_till_done()
    assert hass.states.get("valve.irrigation_zone_3").state == "open"
    await press(hass, "button.irrigation_stop_all")
    assert "ZONE=3 TIME=0" in daemon.sent()
    assert hass.states.get("valve.irrigation_zone_3").state == "closed"


async def test_refused_first_zone_fails_the_action(hass, loaded, daemon):
    """If nothing is running, a refusal fails the start straight away."""
    daemon.refuse = {1}
    with pytest.raises(HomeAssistantError, match="maximum runtime"):
        await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    assert hass.states.get("sensor.irrigation_status").state == "idle"


async def test_refused_waiting_zone_is_skipped(hass, loaded, daemon):
    """A queued zone that irrigationd refuses doesn't stop the zones after it."""
    daemon.refuse = {2}
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    await open_zone(hass, "valve.irrigation_zone_3")
    await press(hass, "button.irrigation_skip")
    await settle(hass)
    assert daemon.sent()[-1] == "ZONE=3 TIME=300"
    assert hass.states.get("valve.irrigation_zone_3").state == "open"


async def test_unload_stops_the_running_zone(hass, loaded, daemon):
    """Unloading or reloading leaves every zone closed."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    assert await hass.config_entries.async_unload(loaded.entry_id)
    await hass.async_block_till_done()
    assert daemon.sent()[-1] == "ZONE=1 TIME=0"
    assert "ZONE=2 TIME=120" not in daemon.sent()


async def setup_with(hass, daemon, **extra):
    entry = MockConfigEntry(domain=DOMAIN, title="Test Controller", data={**ENTRY_DATA, **extra})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_master_zone_opens_with_each_zone(hass, daemon):
    """The master zone opens before each zone and closes after it."""
    await setup_with(hass, daemon, master_zone=4, master_lead=0)
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    assert daemon.sent() == ["ZONE=4 TIME=300", "ZONE=1 TIME=300"]
    await press(hass, "button.irrigation_skip")
    await settle(hass)
    assert daemon.sent()[2:] == ["ZONE=1 TIME=0", "ZONE=4 TIME=0", "ZONE=4 TIME=120", "ZONE=2 TIME=120"]
    assert hass.states.get("valve.irrigation_zone_4").attributes["master"] is True


async def test_master_zone_cant_run_alone(hass, daemon):
    """The master zone has no Start of its own."""
    await setup_with(hass, daemon, master_zone=4)
    with pytest.raises(HomeAssistantError, match="master valve"):
        await hass.services.async_call(
            "valve", "open_valve", {"entity_id": "valve.irrigation_zone_4"}, blocking=True
        )
    assert daemon.sent() == []


async def test_master_closes_if_the_zone_is_refused(hass, daemon):
    """A refused zone doesn't leave the master valve open."""
    await setup_with(hass, daemon, master_zone=4)
    daemon.refuse = {1}
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    # The refused start is sent, then a stop in case only its reply was lost,
    # then the master closes again
    assert daemon.sent() == ["ZONE=4 TIME=300", "ZONE=1 TIME=300", "ZONE=1 TIME=0", "ZONE=4 TIME=0"]


async def test_master_switch_follows_the_queue(hass, daemon):
    """A Home Assistant switch used as the master turns on with a zone and off after."""
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"pump": {}}})
    await setup_with(hass, daemon, master_switch="input_boolean.pump", master_lead=0)
    await open_zone(hass, ZONE_1)
    assert hass.states.get("input_boolean.pump").state == "on"
    await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    await settle(hass)
    assert hass.states.get("input_boolean.pump").state == "off"


async def test_one_call_for_several_zones_runs_them_in_turn(hass, loaded, daemon):
    """irrigation.run on several zones at once opens one and queues the rest."""
    await hass.services.async_call(
        "irrigation",
        "run",
        {"entity_id": [ZONE_1, ZONE_2, "valve.irrigation_zone_3"], "duration": 10},
        blocking=True,
    )
    await hass.async_block_till_done()
    starts = [c for c in daemon.sent() if not c.endswith("TIME=0")]
    assert len(starts) == 1
    queue = queue_of(hass, loaded)
    assert len(queue.waiting) == 2
    open_valves = [
        z for z in (1, 2, 3) if hass.states.get(f"valve.irrigation_zone_{z}").state == "open"
    ]
    assert len(open_valves) == 1


def stuck_issue(hass, entry):
    from homeassistant.helpers import issue_registry as ir

    return ir.async_get(hass).async_get_issue(DOMAIN, f"master_switch_stuck_{entry.entry_id}")


async def test_master_switch_left_on_is_turned_off_at_startup(hass, daemon):
    """A pump left on, such as by a crash mid-run, is turned off when the controller loads."""
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"pump": {"initial": True}}})
    assert hass.states.get("input_boolean.pump").state == "on"
    await setup_with(hass, daemon, master_switch="input_boolean.pump")
    await settle(hass)
    assert hass.states.get("input_boolean.pump").state == "off"


async def test_master_switch_is_turned_off_once_it_loads(hass, daemon):
    """A switch that isn't available yet at startup is turned off as soon as it is."""
    await setup_with(hass, daemon, master_switch="switch.pump")
    hass.states.async_set("switch.pump", "unavailable")
    await settle(hass)
    calls = []

    async def turn_off(call):
        calls.append(call.data["entity_id"])
        hass.states.async_set("switch.pump", "off")

    hass.services.async_register("switch", "turn_off", turn_off)
    hass.states.async_set("switch.pump", "on")
    await settle(hass)
    assert calls == ["switch.pump"]

    # Only once: turning the pump on by hand later is left alone
    hass.states.async_set("switch.pump", "on")
    await settle(hass)
    assert calls == ["switch.pump"]


async def test_master_switch_that_wont_turn_off_raises_an_issue(hass, daemon):
    """A failed turn-off is a Repairs issue, cleared when a later turn-off works."""
    hass.states.async_set("switch.pump", "off")
    entry = await setup_with(hass, daemon, master_switch="switch.pump", master_lead=0)
    fail = True

    async def turn_on(call):
        hass.states.async_set("switch.pump", "on")

    async def turn_off(call):
        if fail:
            raise HomeAssistantError("relay not responding")
        hass.states.async_set("switch.pump", "off")

    hass.services.async_register("switch", "turn_on", turn_on)
    hass.services.async_register("switch", "turn_off", turn_off)

    await open_zone(hass, ZONE_1)
    await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    await settle(hass)
    assert stuck_issue(hass, entry) is not None
    # The zones still closed
    assert hass.states.get(ZONE_1).state == "closed"

    fail = False
    await open_zone(hass, ZONE_1)
    await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    await settle(hass)
    assert hass.states.get("switch.pump").state == "off"
    assert stuck_issue(hass, entry) is None


async def test_failing_master_switch_closes_the_master_zone(hass, daemon):
    """If the switch fails after the master zone opened, the master zone closes again."""
    await setup_with(hass, daemon, master_zone=4, master_switch="switch.pump", master_lead=0)

    async def turn_on(call):
        raise RuntimeError("relay not responding")

    async def turn_off(call):
        pass

    hass.services.async_register("switch", "turn_on", turn_on)
    hass.services.async_register("switch", "turn_off", turn_off)
    with pytest.raises(Exception, match="relay not responding"):
        await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    await settle(hass)
    assert daemon.sent() == ["ZONE=4 TIME=300", "ZONE=4 TIME=0"]
    assert hass.states.get("valve.irrigation_zone_4").state == "closed"


async def test_unexpected_error_skips_only_that_zone(hass, loaded, daemon):
    """An unexpected error starting a waiting zone skips it, and the queue goes on."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_2)
    await open_zone(hass, "valve.irrigation_zone_3")
    queue = queue_of(hass, loaded)
    zone_2 = next(e for e in hass.data[DOMAIN][loaded.entry_id]["entities"] if e._zone == 2)
    real_send_run = zone_2.async_send_run

    async def broken(seconds):
        raise RuntimeError("unexpected")

    zone_2.async_send_run = broken
    await press(hass, "button.irrigation_skip")
    await settle(hass)
    zone_2.async_send_run = real_send_run
    assert queue.current is not None and queue.current.zone == 3
    assert not queue.waiting


async def test_stop_all_between_zones_starts_nothing(hass, daemon):
    """Stop all pressed in the gap between zones doesn't let the next one start."""
    entry = await setup_with(hass, daemon)
    queue = queue_of(hass, entry)
    with patch("custom_components.irrigation.runqueue.ZONE_GAP", 0.6):
        await queue.async_enqueue(1, 1)
        await queue.async_enqueue(2, 300)
        await asyncio.sleep(1.2)  # zone 1 has ended; the next waits out the gap
        async with asyncio.timeout(3):
            await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    assert "ZONE=2 TIME=300" not in daemon.sent()
    assert daemon.zones[2] == 0
    assert not queue.running


async def test_stop_all_during_master_lead_starts_nothing(hass, daemon):
    """Stop all during the master lead time closes the master and opens no zone."""
    entry = await setup_with(hass, daemon, master_zone=4, master_lead=3)
    queue = queue_of(hass, entry)
    await queue.async_enqueue(1, 1)  # returns after the lead, once zone 1 is open
    await queue.async_enqueue(2, 300)
    await asyncio.sleep(2)  # zone 1 has ended; zone 2's master lead is under way
    async with asyncio.timeout(3):
        await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    assert "ZONE=2 TIME=300" not in daemon.sent()
    assert daemon.zones[2] == 0 and daemon.zones[4] == 0
    assert not queue.running


async def test_starting_the_running_zone_again_does_nothing(hass, loaded, daemon):
    """A second open_valve on the running zone doesn't queue another run."""
    await open_zone(hass, ZONE_1)
    await open_zone(hass, ZONE_1)
    assert [(run.zone, run.seconds) for run in queue_of(hass, loaded).runs()] == [(1, 300)]
    assert daemon.sent() == ["ZONE=1 TIME=300"]


async def test_lost_start_reply_sends_a_stop(hass, daemon):
    """If irrigationd opened the zone but the reply was lost, it's closed again."""
    await setup_with(hass, daemon, master_zone=4)
    real = daemon.handle

    def lose_zone_1_reply(command, authenticated=False):
        reply = real(command, authenticated)
        if command.startswith("ZONE=1 TIME=300"):
            raise TimeoutError("reply lost")
        return reply

    daemon.handle = lose_zone_1_reply
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("valve", "open_valve", {"entity_id": ZONE_1}, blocking=True)
    assert daemon.zones[1] == 0 and daemon.zones[4] == 0


async def test_stopping_a_zone_about_to_start_keeps_it_closed(hass, daemon):
    """Stop on the next zone, in the gap before it opens, calls its start off."""
    entry = await setup_with(hass, daemon)
    queue = queue_of(hass, entry)
    with patch("custom_components.irrigation.runqueue.ZONE_GAP", 0.6):
        await queue.async_enqueue(1, 1)
        await queue.async_enqueue(2, 300)
        await queue.async_enqueue(3, 300)
        await asyncio.sleep(1.2)  # zone 1 has ended; zone 2 waits out the gap
        assert hass.states.get(ZONE_2).attributes["queued"] is True
        await hass.services.async_call("valve", "close_valve", {"entity_id": ZONE_2}, blocking=True)
        await asyncio.sleep(1.5)
    assert "ZONE=2 TIME=300" not in daemon.sent()
    assert daemon.zones[2] == 0
    assert queue.current is not None and queue.current.zone == 3


async def test_stopping_a_zone_during_the_master_lead_keeps_it_closed(hass, daemon):
    """Stop on a zone while the master valve opens ahead of it closes both."""
    entry = await setup_with(hass, daemon, master_zone=4, master_lead=3)
    queue = queue_of(hass, entry)
    await queue.async_enqueue(1, 1)
    await queue.async_enqueue(2, 300)
    await asyncio.sleep(2)  # zone 1 has ended; zone 2's master lead is under way
    await hass.services.async_call("valve", "close_valve", {"entity_id": ZONE_2}, blocking=True)
    await asyncio.sleep(3)  # past the end of the lead
    assert "ZONE=2 TIME=300" not in daemon.sent()
    assert daemon.zones[2] == 0 and daemon.zones[4] == 0
    assert not queue.running


async def test_starting_a_zone_about_to_start_again_does_nothing(hass, daemon):
    """A second start of the next zone, in the gap before it opens, adds no run."""
    entry = await setup_with(hass, daemon)
    queue = queue_of(hass, entry)
    with patch("custom_components.irrigation.runqueue.ZONE_GAP", 0.6):
        await queue.async_enqueue(1, 1)
        await queue.async_enqueue(2, 2)
        await asyncio.sleep(1.2)
        await queue.async_enqueue(2, 2)
        await asyncio.sleep(3.5)
    assert daemon.sent().count("ZONE=2 TIME=2") == 1, daemon.sent()


async def test_starting_a_zone_again_during_the_master_lead_does_nothing(hass, daemon):
    """A second start of a zone waiting for the master valve adds no run."""
    entry = await setup_with(hass, daemon, master_zone=4, master_lead=2)
    queue = queue_of(hass, entry)
    await queue.async_enqueue(1, 1)
    await queue.async_enqueue(2, 2)
    await asyncio.sleep(1.5)
    await queue.async_enqueue(2, 2)
    await asyncio.sleep(8)
    assert daemon.sent().count("ZONE=2 TIME=2") == 1, daemon.sent()


async def test_unload_during_the_first_zones_master_lead_opens_nothing(hass, daemon):
    """Unloading while the first zone waits for the master valve leaves both closed."""
    entry = await setup_with(hass, daemon, master_zone=4, master_lead=2)
    start = hass.async_create_task(queue_of(hass, entry).async_enqueue(1, 300))
    await asyncio.sleep(0.5)  # the master is open; zone 1 waits out the lead
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(HomeAssistantError):
        await start
    await asyncio.sleep(0.2)
    assert daemon.zones[1] == 0 and daemon.zones[4] == 0, daemon.sent()


async def test_stop_all_while_several_zones_start_opens_nothing_more(hass, daemon):
    """Stop all while one action starts several zones lets none of them open later."""
    entry = await setup_with(hass, daemon, master_zone=4, master_lead=2)
    queue = queue_of(hass, entry)
    start = hass.async_create_task(
        hass.services.async_call(
            "irrigation", "run",
            {"entity_id": [ZONE_1, ZONE_2, "valve.irrigation_zone_3"], "duration": 300},
            blocking=True,
        )
    )
    await asyncio.sleep(0.5)  # zone 1 waits out the master lead; 2 and 3 wait for the lock
    async with asyncio.timeout(5):
        await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    with pytest.raises(HomeAssistantError):
        await start
    await asyncio.sleep(3)
    opened = [c for c in daemon.sent() if c.startswith(("ZONE=1 ", "ZONE=2 ", "ZONE=3 ")) and not c.endswith("TIME=0")]
    assert opened == [], daemon.sent()
    assert not queue.running
