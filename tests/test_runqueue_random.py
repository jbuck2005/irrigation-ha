"""Randomized tests of the run queue: starts, Stops, Skips and Stop all at random times.

The hand-written tests in test_runqueue.py each check one timing someone
thought of. These fire random sequences of actions, with irrigationd taking a
random time to answer each command, and check rules that must hold whatever
the timing:

- irrigationd never has two zones (other than the master) open at once
- a zone whose last action was Stop ends up closed
- after Stop all, every zone and the master valve end up closed and nothing is queued

Each seed picks the actions and their timing. The replies' order also depends
on threads, so a failure prints its seed and the commands irrigationd saw.
Set IRRIGATION_RANDOM_RUNS to run more seeds, for example 500 before a release.
"""

import asyncio
import os
import random
import re
import threading
import time
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irrigation.const import DOMAIN

from .conftest import ENTRY_DATA
from .fake_irrigationd import COMMAND

RUNS = int(os.environ.get("IRRIGATION_RANDOM_RUNS", "40"))
ZONES = (1, 2, 3)
MASTER = 4
# (master_zone, master_lead) for each layout tried
LAYOUTS = [(None, 0), (MASTER, 0), (MASTER, 0.2), (MASTER, 0.4)]


@pytest.fixture(autouse=True)
def short_gap():
    """A short gap between zones, so a run has room for actions to land in it."""
    with patch("custom_components.irrigation.runqueue.ZONE_GAP", 0.05):
        yield


def valve(zone):
    return f"valve.irrigation_zone_{zone}"


class Recorder:
    """Wrap the fake irrigationd: answer slowly, and check the rules on every command."""

    def __init__(self, daemon, rng, master):
        self.daemon = daemon
        self.master = master
        self.lock = threading.Lock()
        self.violations = []
        self.real = daemon.handle
        # Each command gets its delay from these lists, so the delays follow the seed.
        # Starts are often slow and stops often quick, so a Stop can overtake a start.
        self.start_delays = [rng.choice((0, 0.02, 0.1, 0.3)) for _ in range(400)]
        self.stop_delays = [rng.choice((0, 0, 0.01, 0.1)) for _ in range(400)]
        self.count = 0
        # When each zone's run ends, as irrigationd closes a zone once its time is up
        self.ends = {}
        daemon.handle = self.handle

    def is_open(self, zone):
        return bool(self.daemon.zones[zone]) and time.monotonic() < self.ends.get(zone, 0)

    def handle(self, command, authenticated=False):
        # The short test gap and lead make the master's run time a fraction; round it up
        command = re.sub(r"TIME=(\d+)\.\d+", lambda m: f"TIME={int(m[1]) + 1}", command)
        with self.lock:
            delays = self.stop_delays if command.split(" TOKEN=")[0].endswith("TIME=0") else self.start_delays
            delay = delays[self.count % len(delays)]
            self.count += 1
        time.sleep(delay)
        with self.lock:
            reply = self.real(command, authenticated)
            if (match := COMMAND.match(command)) and reply.startswith("OK"):
                self.ends[int(match[1])] = time.monotonic() + int(match[2])
            open_zones = [z for z in ZONES if self.is_open(z)]
            if len(open_zones) > 1:
                self.violations.append(f"zones {open_zones} open together after {command!r}")
            return reply


async def call(hass, domain, service, data=None):
    try:
        await hass.services.async_call(domain, service, data or {}, blocking=True)
    except HomeAssistantError:
        # Refused starts are expected; the rules are checked on irrigationd's side
        pass


async def settle(hass, seconds=0.5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        await asyncio.sleep(0.02)
        await hass.async_block_till_done()


def actions_for(rng):
    """Pick a list of actions, often several on the same zone close together."""
    actions = []
    zone = rng.choice(ZONES)
    for _ in range(rng.randint(4, 14)):
        kind = rng.choice(("start", "start", "start", "run", "stop", "stop", "stop", "skip", "stop_all"))
        if rng.random() < 0.4:
            zone = rng.choice(ZONES)
        if kind == "run":
            zones = tuple(sorted({zone, *rng.sample(ZONES, rng.randint(1, 2))}))
            actions.append((kind, zones if len(zones) > 1 else (1, 2)))
        elif kind in ("start", "stop"):
            actions.append((kind, (zone,)))
        else:
            actions.append((kind, ()))
    return actions


async def perform(hass, kind, zones):
    if kind == "start":
        await call(hass, "valve", "open_valve", {"entity_id": valve(zones[0])})
    elif kind == "run":
        await call(hass, "irrigation", "run", {"entity_id": [valve(z) for z in zones], "duration": 300})
    elif kind == "stop":
        await call(hass, "valve", "close_valve", {"entity_id": valve(zones[0])})
    elif kind == "skip":
        await call(hass, "button", "press", {"entity_id": "button.irrigation_skip"})
    else:
        await call(hass, "irrigation", "stop_all")


@pytest.mark.parametrize("seed", range(RUNS))
async def test_random_actions_keep_the_rules(hass, daemon, seed):
    """Whatever the order and timing, the queue keeps to the rules above."""
    rng = random.Random(seed)
    master, lead = LAYOUTS[seed % len(LAYOUTS)]
    extra = {"master_zone": master, "master_lead": lead} if master else {}
    # Some zones end by themselves after a second, so actions also land between zones
    durations = {str(z): rng.choice((1, 1, 300)) for z in ZONES}
    data = {**ENTRY_DATA, **extra, "zone_durations": {**ENTRY_DATA["zone_durations"], **durations}}
    entry = MockConfigEntry(domain=DOMAIN, title="Test Controller", data=data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    queue = hass.data[DOMAIN][entry.entry_id]["queue"]
    recorder = Recorder(daemon, rng, master)

    actions = actions_for(rng)
    tasks = []
    for kind, zones in actions:
        tasks.append(hass.async_create_task(perform(hass, kind, zones)))
        await asyncio.sleep(rng.choice((0, 0.01, 0.05, 0.1, 0.3)))
    async with asyncio.timeout(10):
        await asyncio.gather(*tasks)
    await settle(hass)

    def report():
        return f"seed {seed}, master {master} lead {lead}, durations {durations}, actions {actions}\nsent {daemon.sent()}"

    # A zone whose last action was Stop ends up closed. A Stop all after it counts as one too.
    for zone in ZONES:
        last = None
        for kind, zones in actions:
            if kind == "stop_all" or zone in zones and kind in ("start", "run", "stop"):
                last = kind
        if last in ("stop", "stop_all"):
            assert not recorder.is_open(zone), f"zone {zone} left open after its Stop\n{report()}"

    # Stop all leaves everything closed and nothing queued
    async with asyncio.timeout(10):
        await call(hass, "irrigation", "stop_all")
    await settle(hass, 0.3)
    assert recorder.violations == [], report()
    assert not any(recorder.is_open(z) for z in (*ZONES, MASTER)), f"open after Stop all\n{report()}"
    assert not queue.running and not queue.waiting, report()
