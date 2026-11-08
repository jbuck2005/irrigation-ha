"""Tests for programs: schedules, the Add program flow, entities and starting runs."""

import asyncio
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER, ConfigSubentryData
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irrigation.const import DOMAIN
from custom_components.irrigation.program import next_run, runs_on, zone_runs

from .conftest import ENTRY_DATA

TZ = ZoneInfo("UTC")

PROGRAM = {
    "start_times": ["06:00"],
    "days": "every_day",
    "weekdays": [],
    "interval": 2,
    "zone_minutes": {"1": 2, "3": 1},
    "enabled": True,
    "anchor": "2026-11-01",
    "last_run": None,
    "running_since": None,
}

PROGRAM_SWITCH = "switch.irrigation_program_morning"
RUN_NOW = "button.irrigation_program_morning_run_now"


@pytest.fixture(autouse=True)
def no_gap():
    with patch("custom_components.irrigation.runqueue.ZONE_GAP", 0):
        yield


# -- schedule rules --------------------------------------------------------------


@pytest.mark.parametrize(
    ("program", "day", "expected"),
    [
        ({"days": "every_day"}, date(2026, 11, 8), True),
        ({"days": "weekdays", "weekdays": ["sun"]}, date(2026, 11, 8), True),
        ({"days": "weekdays", "weekdays": ["mon"]}, date(2026, 11, 8), False),
        ({"days": "odd"}, date(2026, 11, 9), True),
        ({"days": "odd"}, date(2026, 11, 8), False),
        ({"days": "even"}, date(2026, 11, 8), True),
        ({"days": "interval", "interval": 3, "anchor": "2026-11-01"}, date(2026, 11, 7), True),
        ({"days": "interval", "interval": 3, "anchor": "2026-11-01"}, date(2026, 11, 8), False),
    ],
)
def test_runs_on(program, day, expected):
    assert runs_on(program, day) is expected


def test_next_run_later_today_and_tomorrow():
    program = {"days": "every_day", "start_times": ["06:00", "18:30"]}
    now = datetime(2026, 11, 8, 7, 0, tzinfo=TZ)
    assert next_run(program, now) == datetime(2026, 11, 8, 18, 30, tzinfo=TZ)
    now = datetime(2026, 11, 8, 19, 0, tzinfo=TZ)
    assert next_run(program, now) == datetime(2026, 11, 9, 6, 0, tzinfo=TZ)


def test_next_run_skips_days_it_doesnt_water():
    program = {"days": "weekdays", "weekdays": ["wed"], "start_times": ["05:00"]}
    assert next_run(program, datetime(2026, 11, 8, 12, 0, tzinfo=TZ)) == datetime(
        2026, 11, 11, 5, 0, tzinfo=TZ
    )


def test_next_run_with_no_start_times():
    assert next_run({"start_times": []}, datetime(2026, 11, 8, tzinfo=TZ)) is None


def test_zone_runs_in_zone_order_without_master():
    program = {"zone_minutes": {"10": 1, "2": 5, "4": 3, "3": 0}}
    assert zone_runs(program, master_zone=4) == [(2, 300), (10, 60)]


# -- set up with programs ---------------------------------------------------------


async def setup_with_program(hass, daemon, **program):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Controller",
        data=dict(ENTRY_DATA),
        subentries_data=[
            ConfigSubentryData(
                data={**PROGRAM, **program},
                subentry_type="program",
                title="Morning",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def program_of(entry):
    return next(iter(entry.subentries.values()))


async def settle(hass):
    for _ in range(10):
        await asyncio.sleep(0.02)
        await hass.async_block_till_done()


async def test_program_entities(hass, daemon):
    """A program gets a schedule switch, Run now, and next and last run sensors."""
    await setup_with_program(hass, daemon)
    assert hass.states.get(PROGRAM_SWITCH).state == "on"
    assert hass.states.get(RUN_NOW) is not None
    assert hass.states.get("sensor.irrigation_program_morning_next_run").state not in ("unknown", None)
    assert hass.states.get("sensor.irrigation_program_morning_last_run").state == "unknown"


async def test_run_now_queues_zones_in_order(hass, daemon):
    """Run now starts the first zone and queues the rest."""
    entry = await setup_with_program(hass, daemon)
    await hass.services.async_call("button", "press", {"entity_id": RUN_NOW}, blocking=True)
    await hass.async_block_till_done()
    assert daemon.sent() == ["ZONE=1 TIME=120"]
    status = hass.states.get("sensor.irrigation_status")
    assert status.attributes["program"] == "Morning"
    assert status.attributes["queue"] == [{"zone": 3, "seconds": 60}]
    assert program_of(entry).data["running_since"]
    assert hass.states.get(PROGRAM_SWITCH).attributes["running"] is True
    assert hass.states.get("sensor.irrigation_program_morning_last_run").state != "unknown"


async def test_program_ends_when_its_zones_are_done(hass, daemon):
    """Once Stop all clears its zones, the program no longer counts as running."""
    entry = await setup_with_program(hass, daemon)
    await hass.services.async_call("button", "press", {"entity_id": RUN_NOW}, blocking=True)
    await hass.services.async_call("irrigation", "stop_all", {}, blocking=True)
    await settle(hass)
    assert program_of(entry).data["running_since"] is None
    assert hass.states.get(PROGRAM_SWITCH).attributes["running"] is False


async def test_run_program_action(hass, daemon):
    """irrigation.run_program on the switch runs it even with its schedule off."""
    await setup_with_program(hass, daemon, enabled=False)
    await hass.services.async_call(
        "irrigation", "run_program", {"entity_id": PROGRAM_SWITCH}, blocking=True
    )
    assert daemon.sent() == ["ZONE=1 TIME=120"]


async def test_scheduler_starts_at_start_time(hass, daemon):
    """At a start time on a watering day, the program starts by itself."""
    entry = await setup_with_program(hass, daemon)
    scheduler = hass.data[DOMAIN][entry.entry_id]["scheduler"]
    await scheduler._async_tick(datetime(2026, 11, 8, 6, 0, tzinfo=ZoneInfo(hass.config.time_zone)))
    await hass.async_block_till_done()
    assert daemon.sent() == ["ZONE=1 TIME=120"]


async def test_scheduler_ignores_other_times_and_disabled(hass, daemon):
    """Nothing starts at other times, or while the schedule is off."""
    entry = await setup_with_program(hass, daemon)
    scheduler = hass.data[DOMAIN][entry.entry_id]["scheduler"]
    tz = ZoneInfo(hass.config.time_zone)
    await scheduler._async_tick(datetime(2026, 11, 8, 6, 1, tzinfo=tz))
    await hass.services.async_call("switch", "turn_off", {"entity_id": PROGRAM_SWITCH}, blocking=True)
    assert program_of(entry).data["enabled"] is False
    await scheduler._async_tick(datetime(2026, 11, 8, 6, 0, tzinfo=tz))
    await hass.async_block_till_done()
    assert daemon.sent() == []
    assert hass.states.get("sensor.irrigation_program_morning_next_run").state == "unknown"


async def test_scheduler_doesnt_double_start(hass, daemon):
    """A start time while the program is still running doesn't queue it again."""
    entry = await setup_with_program(hass, daemon, start_times=["06:00", "06:01"])
    scheduler = hass.data[DOMAIN][entry.entry_id]["scheduler"]
    tz = ZoneInfo(hass.config.time_zone)
    await scheduler._async_tick(datetime(2026, 11, 8, 6, 0, tzinfo=tz))
    await scheduler._async_tick(datetime(2026, 11, 8, 6, 1, tzinfo=tz))
    queue = hass.data[DOMAIN][entry.entry_id]["queue"]
    assert [run.zone for run in queue.runs()] == [1, 3]


async def test_turning_schedule_off_doesnt_stop_running_zone(hass, daemon):
    """Changing a program updates the entry but doesn't reload or close valves."""
    await setup_with_program(hass, daemon)
    await hass.services.async_call("button", "press", {"entity_id": RUN_NOW}, blocking=True)
    await hass.services.async_call("switch", "turn_off", {"entity_id": PROGRAM_SWITCH}, blocking=True)
    await hass.async_block_till_done()
    assert "ZONE=1 TIME=0" not in daemon.sent()
    assert hass.states.get("valve.irrigation_zone_1").state == "open"


async def test_restart_mid_program_notifies(hass, daemon):
    """A program left running by a restart is reported and cleared."""
    entry = await setup_with_program(hass, daemon, running_since="2026-11-08T06:00:00+00:00")
    assert program_of(entry).data["running_since"] is None
    notifications = hass.data["persistent_notification"]
    assert any("Morning" in n["message"] for n in notifications.values())


# -- the Add program flow ----------------------------------------------------------


FORM = {
    "name": "Back lawn",
    "start_1": "05:30:00",
    "days": "weekdays",
    "weekdays": ["mon", "thu"],
    "interval": 2,
    "zone_1_minutes": 10,
    "zone_2_minutes": 0,
    "zone_3_minutes": 5,
    "zone_4_minutes": 0,
}


async def start_add_program(hass, entry):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "program"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result


async def test_add_program(hass, loaded, daemon):
    """Adding a program stores it and sets up its entities."""
    result = await start_add_program(hass, loaded)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], FORM)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    sub = program_of(loaded)
    assert sub.title == "Back lawn"
    assert sub.data["start_times"] == ["05:30"]
    assert sub.data["weekdays"] == ["mon", "thu"]
    assert sub.data["zone_minutes"] == {"1": 10, "3": 5}
    assert sub.data["enabled"] is True
    assert hass.states.get("switch.irrigation_program_back_lawn").state == "on"


@pytest.mark.parametrize(
    ("change", "errors"),
    [
        ({"start_1": None}, {"start_1": "no_start_time"}),
        ({"zone_1_minutes": 0, "zone_3_minutes": 0}, {"base": "no_zones"}),
        ({"weekdays": []}, {"weekdays": "no_weekdays"}),
    ],
)
async def test_add_program_errors(hass, loaded, daemon, change, errors):
    """A program needs a start time, a zone, and a weekday when weekdays are chosen."""
    form = {key: value for key, value in {**FORM, **change}.items() if value is not None}
    result = await start_add_program(hass, loaded)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], form)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == errors


async def test_edit_program_keeps_state(hass, daemon):
    """Editing a program keeps whether it's on and when it last ran."""
    entry = await setup_with_program(hass, daemon, enabled=False, last_run="2026-11-07T06:00:00+00:00")
    sub = program_of(entry)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "program"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id},
    )
    assert result["type"] is FlowResultType.FORM
    form = {key: value for key, value in FORM.items() if key != "name"}
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], form)
    assert result["type"] is FlowResultType.ABORT
    data = program_of(entry).data
    assert data["start_times"] == ["05:30"]
    assert data["enabled"] is False
    assert data["last_run"] == "2026-11-07T06:00:00+00:00"


async def test_remove_program(hass, daemon):
    """Deleting a program removes its entities."""
    entry = await setup_with_program(hass, daemon)
    sub = program_of(entry)
    assert hass.config_entries.async_remove_subentry(entry, sub.subentry_id)
    await hass.async_block_till_done()
    assert hass.states.get(PROGRAM_SWITCH) is None or hass.states.get(PROGRAM_SWITCH).state == "unavailable"
    assert hass.data[DOMAIN][entry.entry_id]["program_ids"] == set()
