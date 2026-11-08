"""Run one zone at a time per controller, in order, with an optional master valve."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
import logging
import time

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Seconds between closing one zone and opening the next, so two never overlap
ZONE_GAP = 1


@dataclass
class QueuedRun:
    """One zone waiting to run, or running."""

    zone: int
    seconds: int
    # The program subentry that queued it, or None for a manual start
    program: str | None = None


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
        self.current_ends = 0.0
        self._task: asyncio.Task | None = None
        self._advance = asyncio.Event()
        # Held while deciding whether to start or queue, and while the first zone opens
        self._lock = asyncio.Lock()
        self._stopping = False
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
        """Return true while a queued zone is running."""
        return self.current is not None

    def _valve(self, zone: int):
        for entity in self.hass.data[DOMAIN][self._entry_id]["entities"]:
            if entity._zone == zone:
                return entity
        raise HomeAssistantError(f"Zone {zone} isn't set up on this controller")

    # -- commands ----------------------------------------------------------

    def runs(self):
        """Return the running zone, if any, and every waiting one."""
        return ([self.current] if self.current else []) + list(self.waiting)

    async def async_enqueue(self, zone: int, seconds: int, program: str | None = None) -> None:
        """Run `zone` for `seconds` now if idle, otherwise after the zones ahead of it."""
        if zone == self.master_zone:
            raise HomeAssistantError(
                f"Zone {zone} is the master valve, so it opens with the other zones"
            )
        self._valve(zone)
        run = QueuedRun(zone, seconds, program)
        # One action on several zones calls this for each at the same time, so
        # the idle check and the first zone's start must happen as one step
        async with self._lock:
            if self._task is not None:
                # A newer manual start for a waiting zone replaces the older one
                if program is None:
                    self.remove(zone, manual_only=True)
                self.waiting.append(run)
                self._changed()
                return

            # Idle: start it here, so a refusal fails the action that asked for it
            self._stopping = False
            await self._open(run)
            self._task = self.hass.async_create_background_task(
                self._worker(run), f"irrigation run queue {self._entry_id}"
            )

    def remove(self, zone: int, manual_only: bool = False) -> bool:
        """Drop waiting runs of `zone`; return true if there were any."""
        before = len(self.waiting)
        self.waiting = deque(
            run
            for run in self.waiting
            if run.zone != zone or (manual_only and run.program is not None)
        )
        if len(self.waiting) != before:
            self._changed()
            return True
        return False

    def skip(self) -> None:
        """End the running zone early and go on to the next one."""
        if self.current is not None:
            self._advance.set()

    async def async_stop_all(self) -> None:
        """Clear the queue and close every zone and the master valve."""
        self._stopping = True
        self.waiting.clear()
        # Wait for a zone that's being started right now, so it gets stopped too
        async with self._lock:
            pass
        self._advance.set()
        task = self._task
        if task is not None:
            await asyncio.shield(task)
        # Also close zones started outside the queue, such as from irrigationd's CLI
        for entity in self.hass.data[DOMAIN][self._entry_id]["entities"]:
            if not entity.is_closed:
                await self._quietly(entity.async_send_stop())
        await self._master_off()
        self._changed()

    # -- running -------------------------------------------------------------

    async def _worker(self, run: QueuedRun | None) -> None:
        """Wait out the running zone, then start each waiting zone in turn."""
        try:
            while run is not None:
                try:
                    await asyncio.wait_for(
                        self._advance.wait(), max(0, self.current_ends - time.monotonic())
                    )
                except TimeoutError:
                    pass
                await self._close(run)
                run = None
                while self.waiting and not self._stopping:
                    candidate = self.waiting.popleft()
                    await asyncio.sleep(ZONE_GAP)
                    try:
                        await self._open(candidate)
                    except HomeAssistantError as err:
                        # Like the blueprint: a refused zone doesn't stop the ones after it
                        _LOGGER.warning("Skipping zone %s: %s", candidate.zone, err)
                        continue
                    run = candidate
                    break
        finally:
            self.current = None
            self._task = None
            await self._master_off()
            self._changed()

    async def _open(self, run: QueuedRun) -> None:
        """Open the master valve, wait the lead time, then open the zone."""
        valve = self._valve(run.zone)
        await self._master_on(run.seconds)
        if self.master_lead and (self.master_zone or self.master_switch):
            await asyncio.sleep(self.master_lead)
        try:
            await valve.async_send_run(run.seconds)
        except HomeAssistantError:
            await self._master_off()
            raise
        # Cleared here, not in the worker, so a Skip pressed before the worker runs still counts
        self._advance.clear()
        self.current = run
        self.current_ends = time.monotonic() + run.seconds
        self._changed()

    async def _close(self, run: QueuedRun) -> None:
        """Close the zone that just ran and the master valve."""
        await self._quietly(self._valve(run.zone).async_send_stop())
        await self._master_off()
        self.current = None
        self._changed()

    async def _master_on(self, seconds: int) -> None:
        if self.master_zone:
            # Opened per zone, so it never reaches irrigationd's 2 hour limit
            await self._valve(self.master_zone).async_send_run(
                min(7200, seconds + self.master_lead + ZONE_GAP)
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
            if valve is not None and not valve.is_closed:
                await self._quietly(valve.async_send_stop())
        if self.master_switch:
            await self._quietly(
                self.hass.services.async_call(
                    self.master_switch.split(".")[0], "turn_off",
                    {"entity_id": self.master_switch}, blocking=True,
                )
            )

    @staticmethod
    async def _quietly(coro) -> None:
        """Run a stop, logging rather than raising if it fails."""
        try:
            await coro
        except Exception as err:  # noqa: BLE001 - a failed stop must not end the queue
            _LOGGER.warning("Couldn't close a valve: %s", err)

    async def async_shutdown(self) -> None:
        """Stop everything when the controller is unloaded."""
        if self._task is not None or self.waiting:
            await self.async_stop_all()
