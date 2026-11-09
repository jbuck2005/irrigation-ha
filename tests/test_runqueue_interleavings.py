"""Every order in which irrigationd can see the run queue's commands, for short scripts of actions.

test_runqueue_random.py tries random timings. This test is exhaustive instead,
for a small world: each command to irrigationd is held until the test lets it
through, so the test decides the order irrigationd handles them, as two
connections racing over the network would. The queue's own waits (the gap
between zones, the master valve's lead time) are held the same way. A
depth-first search then tries every choice at every step: let through any
one waiting command or wait, or do the next action. Each path is replayed from a fresh start, and once nothing more
can happen the rules below are checked.

Rules, for every path:
1. irrigationd never has two zones (other than the master) open at once.
2. When everything has settled, irrigationd's open zones are exactly the
   queue's running zone: nothing runs that the queue doesn't know about.
3. With a master zone, the master is open exactly while a zone is.
4. A zone is only closed by something that should close it: a Stop of that
   zone, Stop all, or its time ending (or Skip) while it ran, after the
   command that opened it.
5. A zone whose last action was a start, with nothing after it that could end
   it, ends up running or queued: no start is lost.
6. After Stop all, or unloading, nothing is open or queued.
7. Every action finishes.

Set IRRIGATION_INTERLEAVINGS=full to try every script of three actions, which
takes several minutes; the default tries every script of two plus the longer
ones listed in SCRIPTS.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import itertools
import os
import threading
import time
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irrigation.const import DOMAIN
from custom_components.irrigation.status import IrrigationdClient
from custom_components.irrigation.valve import IrrigationZoneValve

from .conftest import ENTRY_DATA
from .fake_irrigationd import COMMAND

FULL = os.environ.get("IRRIGATION_INTERLEAVINGS") == "full"
MASTER = 4
ZONES = (1, 2, 3)
# Paths tried for one script before giving up on finding more
MAX_PATHS = 4000

ACTIONS = [
    ("start", 1), ("start", 2), ("stop", 1), ("stop", 2),
    ("run", (1, 2)), ("end",), ("skip",), ("stop_all",), ("cancel",), ("unload",),
]
# Longer scripts, each a race worth trying every order of
SCRIPTS = [
    # Stop the running zone just as its time ends and the next one starts
    [("start", 1), ("start", 2), ("stop", 1), ("end",)],
    # Start a zone again just as its time ends
    [("start", 1), ("end",), ("start", 1)],
    # Stop then start the same zone, both on their way at once
    [("start", 1), ("stop", 2), ("start", 2)],
    [("stop", 1), ("start", 1), ("start", 2)],
    # An automation restarted while its zone opens
    [("start", 1), ("cancel",), ("start", 2)],
    [("run", (1, 2)), ("cancel",), ("end",)],
    [("start", 1), ("start", 2), ("end",), ("cancel",)],
    # Stop all, cancelled halfway
    [("start", 1), ("start", 2), ("stop_all",), ("cancel",)],
    # Stop all racing a queue moving on
    [("start", 1), ("start", 2), ("end",), ("stop_all",)],
    [("start", 1), ("start", 2), ("stop", 2), ("end",)],
    [("run", (1, 2)), ("stop", 1), ("start", 1)],
    [("start", 1), ("start", 2), ("unload",)],
    [("start", 1), ("skip",), ("start", 2), ("stop", 2)],
]


def valve(zone):
    return f"valve.irrigation_zone_{zone}"


@dataclass
class Held:
    """A command irrigationd hasn't handled yet."""

    command: str
    key: tuple
    seq: int
    go: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)


class Gate:
    """Wrap the fake irrigationd: hold each command until it's let through, and check rules 1 and 4."""

    def __init__(self, daemon, master):
        self.daemon = daemon
        self.master = master
        self.real = daemon.handle
        self.lock = threading.Lock()
        self.reset()
        daemon.handle = self.handle

    def reset(self):
        with self.lock:
            self.holding = False
            self.held: list[Held] = []
            self.counts: dict[str, int] = {}
            self.submitted = 0
            self.arrived = 0
            self.handled = 0
            self.seq = 0
            # zone -> seq of the command that opened it
            self.opened_by: dict[int, int] = {}
            # zone -> seqs of the actions allowed to close it
            self.permits: dict[int, list[int]] = {z: [] for z in self.daemon.zones}
            self.violations: list[str] = []
            # command -> seqs of when Home Assistant asked for it, oldest first
            self.asked: dict[str, list[int]] = {}
            self.daemon.commands.clear()
            for zone in self.daemon.zones:
                self.daemon.zones[zone] = 0

    def ask(self, command):
        """Note that Home Assistant has asked for `command`."""
        with self.lock:
            self.seq += 1
            self.asked.setdefault(command, []).append(self.seq)

    def tick(self):
        with self.lock:
            self.seq += 1
            return self.seq

    def permit(self, zones):
        seq = self.tick()
        with self.lock:
            for zone in zones:
                self.permits[zone].append(seq)

    async def sleep(self, seconds):
        """Stand in for the run queue's asyncio.sleep: a wait the test lets end."""
        with self.lock:
            holding = self.holding
        if not holding:
            return await asyncio.sleep(0)
        with self.lock:
            self.submitted += 1
            self.arrived += 1
            self.seq += 1
            bare = f"wait {seconds}"
            nth = self.counts.get(bare, 0)
            self.counts[bare] = nth + 1
            held = Held(bare, (bare, nth), self.seq)
            self.held.append(held)
        try:
            while not held.go.is_set():
                await asyncio.sleep(0.001)
        finally:
            with self.lock:
                self.handled += 1
                if held in self.held:
                    self.held.remove(held)
            held.done.set()

    def open_zones(self):
        return {z for z in ZONES if self.daemon.zones[z]}

    def handle(self, command, authenticated=False):
        bare = command.split(" TOKEN=")[0]
        with self.lock:
            self.arrived += 1
            self.seq += 1
            nth = self.counts.get(bare, 0)
            self.counts[bare] = nth + 1
            # Rule 4 counts from when the command was asked for, not when it arrived
            asked = self.asked.get(bare)
            held = Held(bare, (bare, nth), asked.pop(0) if asked else self.seq)
            if self.holding:
                self.held.append(held)
            else:
                held.go.set()
        held.go.wait(30)
        with self.lock:
            before = dict(self.daemon.zones)
            reply = self.real(command, authenticated)
            if (match := COMMAND.match(bare)) and reply.startswith("OK"):
                zone, seconds = int(match[1]), int(match[2])
                if seconds and not before[zone]:
                    self.opened_by[zone] = held.seq
                elif not seconds and before[zone] and zone != self.master:
                    opened = self.opened_by.get(zone, 0)
                    if not any(p > opened for p in self.permits[zone]):
                        self.violations.append(f"zone {zone} closed by {bare!r} with nothing asking for it")
            if len(self.open_zones()) > 1:
                self.violations.append(f"zones {sorted(self.open_zones())} open together after {bare!r}")
            self.handled += 1
            if held in self.held:
                self.held.remove(held)
        held.done.set()
        return reply


async def call(hass, domain, service, data=None):
    """Call a service; return false if it was refused, which the caller is told about."""
    try:
        await hass.services.async_call(domain, service, data or {}, blocking=True)
    except HomeAssistantError:
        return False
    return True


class World:
    """One controller, the gate, and the bookkeeping for one path."""

    def __init__(self, hass, daemon, entry, master):
        self.hass = hass
        self.entry = entry
        self.master = master
        self.gate = Gate(daemon, master)
        self.unloads: set[asyncio.Task] = set()

    @property
    def queue(self):
        data = self.hass.data[DOMAIN].get(self.entry.entry_id)
        return data["queue"] if data else None

    async def quiet(self):
        """Wait until nothing can happen without a held command being let through."""
        stable = 0
        last = None
        for _ in range(4000):
            await asyncio.sleep(0)
            await asyncio.sleep(0.002)
            gate = self.gate
            entry = self.hass.config_entries.async_get_entry(self.entry.entry_id)
            with gate.lock:
                now = (
                    gate.submitted, gate.arrived, gate.handled, len(gate.held),
                    entry.state, len(asyncio.all_tasks()),
                )
                settled = gate.submitted == gate.arrived and gate.handled + len(gate.held) == gate.arrived
            if settled and now == last:
                stable += 1
                if stable >= 5:
                    return
            else:
                stable = 0
            last = now
        raise AssertionError("never settled")

    async def act(self, action, tasks):
        kind = action[0]
        hass = self.hass
        if kind == "start":
            coro = call(hass, "valve", "open_valve", {"entity_id": valve(action[1])})
        elif kind == "run":
            coro = call(hass, "irrigation", "run", {"entity_id": [valve(z) for z in action[1]], "duration": 300})
        elif kind == "stop":
            self.gate.permit([action[1]])
            coro = call(hass, "valve", "close_valve", {"entity_id": valve(action[1])})
        elif kind == "skip":
            queue = self.queue
            if queue is not None and queue.current is not None:
                self.gate.permit([queue.current.zone])
            coro = call(hass, "button", "press", {"entity_id": "button.irrigation_skip"})
        elif kind == "end":
            # The running zone's time is up: the same as the worker's wait timing out
            queue = self.queue
            if queue is not None and queue.current is not None:
                self.gate.permit([queue.current.zone])
                queue._advance.set()
            return
        elif kind == "stop_all":
            self.gate.permit(ZONES)
            coro = call(hass, "irrigation", "stop_all")
        elif kind == "unload":
            self.gate.permit(ZONES)
            task = hass.async_create_task(hass.config_entries.async_unload(self.entry.entry_id), eager_start=False)
            self.unloads.add(task)
            tasks.append(task)
            return task
        elif kind == "cancel":
            # Like an automation restarted, or a script stopped, partway through
            # its action. Unloading is Home Assistant's own, so it isn't cancelled.
            for task in reversed(tasks):
                if not task.done() and task not in self.unloads:
                    task.cancel()
                    break
            return
        task = hass.async_create_task(coro, eager_start=False)
        tasks.append(task)
        return task


def choices(world, script, step):
    out = []
    if step < len(script):
        out.append(("act", step))
    with world.gate.lock:
        keys = sorted(h.key for h in world.gate.held)
    out.extend(("go", key) for key in keys)
    return out


async def replay(world, script, path):
    """Play `path` from a fresh start; return the choices open at its end."""
    hass, gate = world.hass, world.gate
    if world.queue is None:
        assert await hass.config_entries.async_setup(world.entry.entry_id)
        await hass.async_block_till_done()
    gate.reset()
    with gate.lock:
        gate.holding = True
    tasks: list[asyncio.Task] = []
    step = 0
    world.last_actions = []
    for choice in path:
        if choice[0] == "act":
            action = script[choice[1]]
            seq = gate.tick()
            world.last_actions.append((action, seq, await world.act(action, tasks)))
            step += 1
        else:
            with gate.lock:
                held = next((h for h in gate.held if h.key == choice[1]), None)
            assert held is not None, f"replay went another way at {choice}: {[h.key for h in gate.held]}\npath {path}\nsent {gate.daemon.sent()}"
            held.go.set()
            while not held.done.is_set():
                await asyncio.sleep(0.001)
        await world.quiet()
    world.tasks = tasks
    return choices(world, script, step)


def describe(world, script, path):
    return f"script {script}, master {world.master}\npath {path}\nsent {world.gate.daemon.sent()}"


async def check(world, script, path):
    """Check the rules once nothing more can happen on this path."""
    hass, gate = world.hass, world.gate
    where = describe(world, script, path)
    for task in world.tasks:
        assert task.done(), f"an action never finished\n{where}"
    assert gate.violations == [], f"{gate.violations}\n{where}"
    queue = world.queue
    open_zones = gate.open_zones()
    master_open = bool(world.master and gate.daemon.zones[world.master])
    if queue is None:
        assert not open_zones and not master_open, f"open after unloading: {open_zones}\n{where}"
        return
    current = queue.current.zone if queue.current is not None else None
    expected = {current} if current is not None else set()
    assert open_zones == expected, (
        f"irrigationd has {sorted(open_zones)} open, the queue runs {current}\n{where}"
    )
    if world.master:
        assert master_open == (current is not None), (
            f"master {'open' if master_open else 'closed'} while the queue runs {current}\n{where}"
        )
    waiting = {run.zone for run in queue.runs()}
    actions = [a for a, _, _ in world.last_actions]
    if actions and actions[-1][0] == "stop_all":
        assert not open_zones and not master_open and not queue.waiting and not queue.running, (
            f"left after Stop all: open {open_zones}, waiting {list(queue.waiting)}\n{where}"
        )
    for zone in ZONES:
        last = None
        for action, _, task in world.last_actions:
            kind = action[0]
            if kind in ("start", "stop") and action[1] == zone or kind == "run" and zone in action[1]:
                last = kind
                # A start refused with an error isn't lost: the caller was told
                if kind != "stop" and (task.cancelled() or task.result() is False):
                    last = "refused"
            elif kind in ("stop_all", "unload"):
                last = kind
            elif kind in ("end", "skip") and last in ("start", "run"):
                last = "ended"
            elif kind == "cancel" and last in ("start", "run"):
                last = "cancelled"
        if last == "stop":
            assert zone not in open_zones and zone not in waiting, f"zone {zone} left after its Stop\n{where}"
        if last in ("start", "run"):
            assert zone in open_zones or zone in waiting, f"zone {zone}'s start was lost\n{where}"



class GatedAsyncio:
    """The asyncio module, with sleep replaced by the gate's."""

    def __init__(self, gate):
        self.sleep = gate.sleep

    def __getattr__(self, name):
        return getattr(asyncio, name)


async def explore(hass, daemon, script, master):
    # A one second lead, so starting a zone has a wait in it like the gap does
    extra = {"master_zone": master, "master_lead": 1} if master else {}
    entry = MockConfigEntry(domain=DOMAIN, title="Test Controller", data={**ENTRY_DATA, **extra})
    entry.add_to_hass(hass)
    world = World(hass, daemon, entry, master)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    original = IrrigationdClient.async_send

    async def counted(client, command):
        with world.gate.lock:
            world.gate.submitted += 1
        return await original(client, command)

    real_send_command = IrrigationZoneValve._send_command

    async def asked(valve, command):
        world.gate.ask(command)
        return await real_send_command(valve, command)

    with (
        patch.object(IrrigationdClient, "async_send", counted),
        patch.object(IrrigationZoneValve, "_send_command", asked),
        patch("custom_components.irrigation.runqueue.asyncio", GatedAsyncio(world.gate)),
    ):
        try:
            return await search(world, script)
        finally:
            # Let any held command go, so a failed path leaves no thread waiting
            with world.gate.lock:
                world.gate.holding = False
                for held in world.gate.held:
                    held.go.set()


async def search(world, script):
    """Try every path of `script`; return how many there were."""
    hass, entry = world.hass, world.entry
    paths = 0
    stack = [[]]
    while stack:
        path = stack.pop()
        options = await replay(world, script, path)
        if not options:
            await check(world, script, path)
            paths += 1
            assert paths < MAX_PATHS, f"too many paths for {script}"
        else:
            for option in reversed(options):
                stack.append([*path, option])
        # Let everything through and start the next path from scratch
        with world.gate.lock:
            world.gate.holding = False
            for held in world.gate.held:
                held.go.set()
        async with asyncio.timeout(30):
            await asyncio.gather(*world.tasks, return_exceptions=True)
        await world.quiet()
        if world.queue is not None:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
    return paths


def scripts():
    found = [list(s) for s in itertools.product(ACTIONS, repeat=3 if FULL else 2)]
    return found + [s for s in SCRIPTS if s not in found]


@pytest.mark.parametrize("master", [None, MASTER], ids=["no-master", "master-zone"])
@pytest.mark.parametrize("script", scripts(), ids=lambda s: "-".join("".join(map(str, a)) for a in s))
async def test_every_order_keeps_the_rules(hass, daemon, script, master):
    """Whatever order irrigationd handles the commands in, the rules hold."""
    # A script starting with nothing running can only be a no-op for some actions
    assert await explore(hass, daemon, script, master) > 0
