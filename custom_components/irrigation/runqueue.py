"""Run one zone at a time per controller, in order, with an optional master valve."""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
import logging
import time

from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN
from .status import COMMAND_DEADLINE, parse_status, safe_reply

_LOGGER = logging.getLogger(__name__)

# Seconds between closing one zone and opening the next, so two never overlap
ZONE_GAP = 1


class StoppedError(HomeAssistantError):
    """A start was refused because Stop all was pressed after it was asked for."""


class ZoneStoppedError(HomeAssistantError):
    """A start was refused because its zone was stopped after it was asked for."""


@dataclass
class QueuedRun:
    """One zone waiting to run, or running."""

    zone: int
    seconds: int
    # The program subentry that queued it, or None for a manual start
    program: str | None = None
    # How many Stop alls, and Stops of this zone, there had been when it was
    # asked for. A Stop after that calls it off; see RunQueue._refusal.
    stops: int = 0
    zone_stops: int = 0


class RunQueue:
    """Run a controller's zones one after another.

    Every start from Home Assistant goes through here: Start in the panel,
    valve.open_valve, irrigation.run, and later programs. If nothing is
    running, the zone starts straight away and any refusal fails the caller.
    Otherwise it waits its turn.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        master_zone: int = 0,
        master_switch: str | None = None,
        master_lead: int = 0,
    ) -> None:
        """Initialize an empty queue."""
        self.hass = hass
        self._entry_id = entry_id
        self.master_zone = master_zone
        self.master_switch = master_switch or None
        self.master_lead = master_lead
        self.waiting: deque[QueuedRun] = deque()
        self.current: QueuedRun | None = None
        # The zone being started: in the gap before it, or waiting for the master valve
        self.starting: QueuedRun | None = None
        self.current_ends = 0.0
        self._task: asyncio.Task | None = None
        self._advance = asyncio.Event()
        # Held while deciding whether to start or queue, and while the first zone opens
        self._lock = asyncio.Lock()
        # Every Stop all, and every Stop of each zone, is counted. A run notes
        # the counts when it's asked for, and _refusal compares them before
        # each step that could open a valve, so a Stop always wins over a
        # start asked for before it, wherever the start has got to.
        self._stops = 0
        self._stops_running = 0
        self._zone_stops: Counter[int] = Counter()
        # Set once the controller is unloading, so nothing new can start
        self._closed = False
        # Stop alls still running, which unloading waits for
        self._stop_tasks: set[asyncio.Task] = set()
        self._listeners: list[Callable[[], None]] = []

    # -- state for entities ------------------------------------------------

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call `listener` whenever the queue changes; return a remover."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    @property
    def running(self) -> bool:
        """Return true while a zone runs, including the pause before the next one."""
        return self.current is not None or self._task is not None

    def _valve(self, zone: int):
        for entity in self.hass.data[DOMAIN][self._entry_id]["entities"]:
            if entity._zone == zone:
                return entity
        raise HomeAssistantError(f"Zone {zone} isn't set up on this controller")

    # -- commands ----------------------------------------------------------

    def runs(self):
        """Return the running zone, if any, the one being started, and every waiting one."""
        return (
            ([self.current] if self.current else [])
            + ([self.starting] if self.starting and self._refusal(self.starting) is None else [])
            + list(self.waiting)
        )

    async def async_enqueue(self, zone: int, seconds: int, program: str | None = None) -> None:
        """Run `zone` for `seconds` now if idle, otherwise after the zones ahead of it."""
        if zone == self.master_zone:
            raise HomeAssistantError(
                f"Zone {zone} is the master valve, so it opens with the other zones"
            )
        self._valve(zone)
        run = QueuedRun(zone, seconds, program, self._stops, self._zone_stops[zone])
        await self._to_the_end(self._async_enqueue(run))

    async def _to_the_end(self, coro, tasks: set[asyncio.Task] | None = None) -> None:
        """Run `coro` in its own task, so it finishes even if the caller is cancelled.

        A caller can be cancelled at any await, such as an automation restarted
        or a script stopped while its zone opens. Stopping a start halfway would
        leave the master valve or pump on with nothing to turn it off, and a Stop
        all halfway would leave zones open, so both always run to the end.
        """
        task = self.hass.async_create_task(coro, f"irrigation run queue {self._entry_id} step")
        # Read the result even when no one waits for it any more, so it isn't logged as lost
        task.add_done_callback(lambda done: done.cancelled() or done.exception())
        if tasks is not None:
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        await asyncio.shield(task)

    async def _async_enqueue(self, run: QueuedRun) -> None:
        zone, program = run.zone, run.program
        # One action on several zones calls this for each at the same time, so
        # the idle check and the first zone's start must happen as one step
        async with self._lock:
            # A start that waited here while Stop all, or a Stop of its zone,
            # was pressed mustn't go ahead once it gets the lock
            self._check(run)
            if self._task is not None:
                if program is None:
                    # Starting the zone that's already running, or being started,
                    # does nothing, so a repeated open_valve can't water it twice
                    if any(
                        active is not None and active.zone == zone and self._refusal(active) is None
                        for active in (self.current, self.starting)
                    ):
                        _LOGGER.info("Zone %s is already running", zone)
                        return
                    # A newer manual start for a waiting zone replaces the older one
                    self.remove(zone, manual_only=True)
                self.waiting.append(run)
                self._changed()
                return

            # Idle: start it here, so a refusal fails the action that asked for it
            await self._open(run)
            self._task = self.hass.async_create_background_task(
                self._worker(run), f"irrigation run queue {self._entry_id}"
            )

    def remove(self, zone: int, manual_only: bool = False) -> bool:
        """Drop waiting runs of `zone`; return true if there were any.

        Unless `manual_only`, this is a Stop of the zone: every start of it asked
        for until now is called off, wherever it has got to.
        """
        before = len(self.waiting)
        if not manual_only:
            starting = self.starting
            if starting is not None and starting.zone == zone and self._refusal(starting) is None:
                before += 1
            self._zone_stops[zone] += 1
        self.waiting = deque(
            run
            for run in self.waiting
            if run.zone != zone or (manual_only and run.program is not None)
        )
        if len(self.waiting) != before:
            self._changed()
            return True
        return False

    def skip(self, run: QueuedRun | None = None) -> None:
        """End the running zone early and go on to the next one.

        With `run`, only if that run is still the one running: a Stop that took
        a while mustn't end the zone that started after it.
        """
        if self.current is not None and (run is None or self.current is run):
            self._advance.set()

    async def async_stop_all(self) -> None:
        """Clear the queue and close every zone and the master valve."""
        self._stops += 1
        self._stops_running += 1
        await self._to_the_end(self._async_stop_all(), self._stop_tasks)

    async def _async_stop_all(self) -> None:
        try:
            await self._stop_everything()
        finally:
            self._stops_running -= 1

    async def _stop_everything(self) -> None:
        self.waiting.clear()
        # Wait for a zone that's being started right now, so it gets stopped too
        async with self._lock:
            pass
        self._advance.set()
        task = self._task
        if task is not None:
            await asyncio.shield(task)
        # A start that arrived while stopping mustn't run later
        self.waiting.clear()
        # Also close zones started outside the queue, such as from irrigationd's CLI
        entities = self.hass.data[DOMAIN][self._entry_id]["entities"]
        for entity in entities:
            if not entity.is_closed:
                await self._quietly(entity.async_send_stop())
        await self._close_unseen(entities)
        await self._master_off()
        self._changed()

    async def _close_unseen(self, entities) -> None:
        """Close zones irrigationd has open that Home Assistant doesn't know about yet.

        Home Assistant learns of a zone started elsewhere only at the next poll,
        up to 15 seconds later, or longer while polls fail or just after a restart.
        """
        client = self.hass.data[DOMAIN][self._entry_id]["client"]
        try:
            zones = parse_status(await client.async_send("STATUS"))
        except Exception as err:  # noqa: BLE001 - irrigationd can't be reached, so the stops above are all that can be done
            _LOGGER.warning("Couldn't check irrigationd for open zones: %s", safe_reply(str(err)))
            return
        for entity in entities:
            # A reply that can't be read, such as from an older irrigationd, closes every zone
            if zones is None or zones.get(entity._zone, (False, 0))[0]:
                await self._quietly(entity.async_send_stop())

    # -- running -------------------------------------------------------------

    async def _worker(self, run: QueuedRun | None) -> None:
        """Wait out the running zone, then start each waiting zone in turn."""
        finished = False
        try:
            while run is not None:
                # A Stop may have come while this zone was opening
                if self._refusal(run) is None:
                    try:
                        await asyncio.wait_for(
                            self._advance.wait(), max(0, self.current_ends - time.monotonic())
                        )
                    except TimeoutError:
                        pass
                await self._close(run)
                run = None
                while self.waiting:
                    candidate = self.waiting.popleft()
                    self.starting = candidate
                    try:
                        await asyncio.sleep(ZONE_GAP)
                    finally:
                        self.starting = None
                    if self._refusal(candidate) is not None:
                        continue
                    try:
                        await self._open(candidate)
                    except Exception as err:  # noqa: BLE001 - one bad zone mustn't strand the rest
                        # Like the blueprint: a refused zone doesn't stop the ones after it
                        _LOGGER.warning("Skipping zone %s: %s", candidate.zone, err)
                        continue
                    run = candidate
                    break
            finished = True
        finally:
            self.current = None
            self._task = None
            # On the way out the master is already closed: _close closed it and
            # nothing has opened it since. Closing it again here would race a
            # zone started the moment the queue went idle, and could close its
            # master. Only an error or cancellation leaves it to close here.
            if not finished:
                await self._master_off()
            self._changed()

    async def _open(self, run: QueuedRun) -> None:
        """Open the master valve, wait the lead time, then open the zone."""
        valve = self._valve(run.zone)
        self.starting = run
        try:
            self._check(run)
            await self._master_on(run.seconds)
            if self.master_lead and (self.master_zone or self.master_switch):
                await asyncio.sleep(self.master_lead)
            self._check(run)
            try:
                await valve.async_send_run(run.seconds)
            except Exception:
                # The reply may have been lost after irrigationd opened it
                await self._quietly(valve.async_send_stop())
                raise
            if self._refusal(run) is not None:
                # Stopped while the start was on its way: the Stop may have
                # reached irrigationd first, so close the zone again
                await self._quietly(valve.async_send_stop())
                self._check(run)
        except Exception:
            # Whichever step failed, such as the master switch after the master
            # zone opened, nothing is left open without a zone to feed
            await self._master_off()
            raise
        finally:
            self.starting = None
        # Cleared here, not in the worker, so a Skip pressed before the worker runs still counts
        self._advance.clear()
        self.current = run
        self.current_ends = time.monotonic() + run.seconds
        self._changed()

    def _refusal(self, run: QueuedRun) -> HomeAssistantError | None:
        """Return why `run` mustn't open its zone now, or None if it may.

        This is the one place that decides. Every step that could open a valve
        asks it first, and asks again once irrigationd has answered a start.
        """
        if self._closed:
            return StoppedError(f"Zone {run.zone} wasn't started: the controller is unloading")
        if run.stops != self._stops or self._stops_running:
            return StoppedError(f"Zone {run.zone} wasn't started: Stop all was pressed")
        if run.zone_stops != self._zone_stops[run.zone]:
            return ZoneStoppedError(f"Zone {run.zone} wasn't started: it was stopped")
        return None

    def _check(self, run: QueuedRun) -> None:
        """Raise if `run` mustn't open its zone now."""
        if (refused := self._refusal(run)) is not None:
            raise refused

    async def _close(self, run: QueuedRun) -> None:
        """Close the zone that just ran and the master valve."""
        # Not running from here on, so a start of the same zone while it closes
        # is queued to run again, rather than taken for the run that's ending
        self.current = None
        await self._quietly(self._valve(run.zone).async_send_stop())
        await self._master_off()
        self._changed()

    async def _master_on(self, seconds: int) -> None:
        if self.master_zone:
            # Opened per zone, so it never reaches irrigationd's 2-hour limit. It
            # outlasts the zone by the gap and by the longest the zone's start can
            # take to reach irrigationd, so its own timer never closes it first.
            # Home Assistant closes it as soon as the zone is done anyway.
            await self._valve(self.master_zone).async_send_run(
                min(7200, seconds + self.master_lead + ZONE_GAP + COMMAND_DEADLINE)
            )
        if self.master_switch:
            await self.hass.services.async_call(
                self.master_switch.split(".")[0], "turn_on",
                {"entity_id": self.master_switch}, blocking=True,
            )

    async def _master_off(self) -> None:
        if self.master_zone:
            try:
                valve = self._valve(self.master_zone)
            except HomeAssistantError:
                valve = None
            # Sent even if it looks closed: a start whose reply was lost can
            # leave it open without Home Assistant knowing, and a stop is safe to repeat
            if valve is not None:
                await self._quietly(valve.async_send_stop())
        if self.master_switch:
            await self._master_switch_off()

    # -- master switch fail-safe ---------------------------------------------
    #
    # irrigationd closes its own zones when their time ends, even if Home
    # Assistant has stopped. A master switch, often a pump, has no such timer,
    # so a pump left on would run against closed valves. These make sure it
    # ends up off, and say so loudly when it can't be turned off.

    @property
    def _stuck_issue(self) -> str:
        return f"master_switch_stuck_{self._entry_id}"

    async def _master_switch_off(self) -> None:
        """Turn the master switch off, raising a Repairs issue if that fails."""
        switch = self.master_switch
        try:
            await self.hass.services.async_call(
                switch.split(".")[0], "turn_off", {"entity_id": switch}, blocking=True
            )
        except Exception as err:  # noqa: BLE001 - a failed stop must not end the queue
            _LOGGER.error("Couldn't turn off the master switch %s: %s", switch, err)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._stuck_issue,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="master_switch_stuck",
                translation_placeholders={"switch": switch},
            )
            return
        ir.async_delete_issue(self.hass, DOMAIN, self._stuck_issue)

    @callback
    def async_master_failsafe(self) -> Callable[[], None]:
        """Turn the master switch off now that Home Assistant has started.

        Nothing is queued after a start or reload, so no zone needs it. If the
        switch isn't available yet, such as a device still connecting, it's
        turned off as soon as it is. Returns a function that stops waiting.
        """
        switch = self.master_switch
        if not switch:
            return lambda: None

        def ready(state) -> bool:
            return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

        @callback
        def turn_off_if_on(state) -> None:
            # A zone being started has turned it on, or is about to
            if state.state != STATE_OFF and not self.running and not self._lock.locked():
                _LOGGER.warning("Turning off the master switch %s, which was left on", switch)
                self.hass.async_create_task(self._master_switch_off())

        current = self.hass.states.get(switch)
        if ready(current):
            turn_off_if_on(current)
            return lambda: None

        unsub: Callable[[], None] | None = None

        @callback
        def changed(event: Event[EventStateChangedData]) -> None:
            nonlocal unsub
            new = event.data["new_state"]
            if not ready(new):
                return
            if unsub is not None:
                unsub()
                unsub = None
            turn_off_if_on(new)

        unsub = async_track_state_change_event(self.hass, [switch], changed)

        def stop() -> None:
            nonlocal unsub
            if unsub is not None:
                unsub()
                unsub = None

        return stop

    @staticmethod
    async def _quietly(coro) -> None:
        """Run a stop, logging rather than raising if it fails."""
        try:
            await coro
        except Exception as err:  # noqa: BLE001 - a failed stop must not end the queue
            _LOGGER.warning("Couldn't close a valve: %s", err)

    async def async_shutdown(self) -> None:
        """Stop everything when the controller is unloaded."""
        self._closed = True
        # A first zone that's being started holds the lock, with no task yet
        if self._task is not None or self.waiting or self._lock.locked():
            await self.async_stop_all()
        # A Stop all pressed just before must finish while the zones are still here
        if self._stop_tasks:
            await asyncio.wait(set(self._stop_tasks))
