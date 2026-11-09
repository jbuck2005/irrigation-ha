"""Watering programs: when they run, and starting them through the run queue.

Each program is a config subentry of its controller. Its data holds:
- start_times: "HH:MM" strings, up to four
- days: every_day, weekdays, interval, odd or even
- weekdays: ["mon", ...] when days is weekdays
- interval: days between runs when days is interval, counted from `anchor`
- zone_minutes: {"1": 10, ...}, zones in number order; 0 or missing skips a zone
- enabled, last_run (ISO time) and running_since (set while it runs)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .runqueue import StoppedError

_LOGGER = logging.getLogger(__name__)

SUBENTRY_PROGRAM = "program"

DAYS_EVERY = "every_day"
DAYS_WEEKDAYS = "weekdays"
DAYS_INTERVAL = "interval"
DAYS_ODD = "odd"
DAYS_EVEN = "even"
DAY_MODES = [DAYS_EVERY, DAYS_WEEKDAYS, DAYS_INTERVAL, DAYS_ODD, DAYS_EVEN]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

MAX_START_TIMES = 4
MAX_ZONE_MINUTES = 120
# How far ahead the next run is looked for
LOOKAHEAD_DAYS = 62


def runs_on(program: dict, day: date) -> bool:
    """Return true if `program` waters on `day`."""
    mode = program.get("days", DAYS_EVERY)
    if mode == DAYS_WEEKDAYS:
        return WEEKDAYS[day.weekday()] in program.get("weekdays", [])
    if mode == DAYS_INTERVAL:
        anchor = date.fromisoformat(program.get("anchor", day.isoformat()))
        interval = max(1, int(program.get("interval", 1)))
        return (day - anchor).days % interval == 0
    if mode == DAYS_ODD:
        return day.day % 2 == 1
    if mode == DAYS_EVEN:
        return day.day % 2 == 0
    return True


def start_times(program: dict) -> list[tuple[int, int]]:
    """Return the program's start times as sorted (hour, minute) pairs."""
    times = set()
    for value in program.get("start_times", []):
        hour, minute = value.split(":")[:2]
        times.add((int(hour), int(minute)))
    return sorted(times)


def due_minutes(now: datetime) -> set[int]:
    """Return the minutes of the day, as hour * 60 + minute, that start at `now`.

    Normally just now's. When clocks go forward, the skipped times are due at
    the first minute after the gap, so a start inside it still runs that day.
    """
    current = now.hour * 60 + now.minute
    before = dt_util.as_local(dt_util.as_utc(now) - timedelta(minutes=1))
    previous = before.hour * 60 + before.minute
    if before.date() == now.date() and previous < current - 1:
        return set(range(previous + 1, current + 1))
    return {current}


def next_run(program: dict, after: datetime) -> datetime | None:
    """Return the first start strictly after `after`, in its time zone, or None."""
    times = start_times(program)
    if not times:
        return None
    for offset in range(LOOKAHEAD_DAYS):
        day = (after + timedelta(days=offset)).date()
        if not runs_on(program, day):
            continue
        for hour, minute in times:
            start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=after.tzinfo)
            if start > after:
                return start
    return None


def zone_runs(program: dict, master_zone: int = 0) -> list[tuple[int, int]]:
    """Return (zone, seconds) for each zone the program waters, in zone order."""
    runs = []
    for zone, minutes in sorted(program.get("zone_minutes", {}).items(), key=lambda i: int(i[0])):
        if int(zone) != master_zone and minutes and int(minutes) > 0:
            runs.append((int(zone), int(minutes) * 60))
    return runs


class Scheduler:
    """Start a controller's programs at their start times."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, queue) -> None:
        """Initialize the scheduler; call async_start to begin."""
        self.hass = hass
        self.entry = entry
        self.queue = queue
        self._listeners: list[Callable[[], None]] = []
        # Programs being queued right now, so a second tap can't slip in before the first zone is queued
        self._starting: set[str] = set()

    def programs(self) -> list[ConfigSubentry]:
        """Return the controller's program subentries."""
        return [
            sub for sub in self.entry.subentries.values() if sub.subentry_type == SUBENTRY_PROGRAM
        ]

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call `listener` each minute and whenever a program starts or ends."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def async_start(self) -> None:
        """Report programs a restart interrupted, then check every minute."""
        for sub in self.programs():
            if sub.data.get("running_since"):
                persistent_notification.async_create(
                    self.hass,
                    f"The program **{sub.title}** was still running when Home Assistant "
                    "restarted, so its remaining zones were skipped.",
                    title="Irrigation program interrupted",
                    notification_id=f"irrigation_interrupted_{sub.subentry_id}",
                )
                self._update(sub, running_since=None)
        self.entry.async_on_unload(
            async_track_time_change(self.hass, self._async_tick, second=0)
        )
        self.entry.async_on_unload(self.queue.add_listener(self._queue_changed))

    def is_running(self, subentry_id: str) -> bool:
        """Return true while any of the program's zones is running or waiting."""
        return any(run.program == subentry_id for run in self.queue.runs())

    async def _async_tick(self, now: datetime) -> None:
        now = dt_util.as_local(now).replace(second=0, microsecond=0)
        due = due_minutes(now)
        for sub in self.programs():
            program = sub.data
            if not program.get("enabled", True):
                continue
            matched = [t for t in start_times(program) if t[0] * 60 + t[1] in due]
            if not matched or not runs_on(program, now.date()):
                continue
            # When clocks go back and an hour repeats, or a clock steps back,
            # the same scheduled run mustn't start twice
            key = f"{now.date().isoformat()} {matched[-1][0]:02d}:{matched[-1][1]:02d}"
            if program.get("last_start_key") == key:
                continue
            self._update(sub, last_start_key=key)
            if self.is_running(sub.subentry_id):
                _LOGGER.warning("Not starting %s: it's still running from its last start", sub.title)
                continue
            try:
                await self.async_run(sub)
            except HomeAssistantError as err:
                _LOGGER.warning("Program %s didn't start: %s", sub.title, err)
        self._changed()

    async def async_run(self, sub: ConfigSubentry) -> None:
        """Queue every zone of the program now, whatever its schedule."""
        if sub.subentry_id in self._starting or self.is_running(sub.subentry_id):
            raise HomeAssistantError(f"The program {sub.title} is already running")
        runs = zone_runs(sub.data, self.queue.master_zone)
        if not runs:
            raise HomeAssistantError(f"The program {sub.title} has no zones with a run time")
        self._starting.add(sub.subentry_id)
        try:
            await self._async_queue_runs(sub, runs)
        finally:
            self._starting.discard(sub.subentry_id)

    async def _async_queue_runs(self, sub: ConfigSubentry, runs: list[tuple[int, int]]) -> None:
        self._update(sub, running_since=dt_util.utcnow().isoformat(), last_run=dt_util.utcnow().isoformat())
        started = 0
        for zone, seconds in runs:
            try:
                await self.queue.async_enqueue(zone, seconds, sub.subentry_id)
                started += 1
            except StoppedError as err:
                # Stop all ends the whole program, not just the zone it caught
                _LOGGER.info("Program %s stopped: %s", sub.title, err)
                break
            except HomeAssistantError as err:
                # Only the first zone can fail here; later ones are skipped by the queue itself
                _LOGGER.warning("Program %s: zone %s didn't start: %s", sub.title, zone, err)
        if not self.is_running(sub.subentry_id):
            self._update(sub, running_since=None)
        self._changed()

    @callback
    def _queue_changed(self) -> None:
        # A program has ended once none of its zones is running or waiting
        for sub in self.programs():
            if sub.data.get("running_since") and not self.is_running(sub.subentry_id):
                self._update(sub, running_since=None)
                self._changed()

    def _update(self, sub: ConfigSubentry, **changes) -> None:
        # Subentries are replaced on every update, so start from the current one
        sub = self.entry.subentries.get(sub.subentry_id)
        if sub is None:
            return
        self.hass.config_entries.async_update_subentry(self.entry, sub, data={**sub.data, **changes})

    def set_enabled(self, sub: ConfigSubentry, enabled: bool) -> None:
        """Turn a program's schedule on or off."""
        self._update(sub, enabled=enabled)
        self._changed()
