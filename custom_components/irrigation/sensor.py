"""Sensors that show what a controller's run queue is doing."""

from __future__ import annotations

import time

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from datetime import datetime

from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, device_info, entity_id_prefix, program_device_info, program_entity_id
from .program import next_run

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"


class _QueueSensor(SensorEntity):
    """Base for sensors that update whenever the run queue changes."""

    _attr_should_poll = False

    def __init__(self, entry, queue, key: str, name: str):
        self._queue = queue
        self._entry_id = entry.entry_id
        self.entity_id = f"sensor.{entity_id_prefix(entry)}_{key}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._queue.add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()


class QueueStatusSensor(_QueueSensor):
    """Idle or running, with the running zone and what's waiting."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_IDLE, STATUS_RUNNING]
    _attr_translation_key = "status"
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, entry, queue):
        super().__init__(entry, queue, "status", "Irrigation Status")

    @property
    def native_value(self):
        return STATUS_RUNNING if self._queue.running else STATUS_IDLE

    @property
    def extra_state_attributes(self):
        current = self._queue.current
        return {
            "current_zone": current.zone if current else None,
            "ends_in": max(0, round(self._queue.current_ends - time.monotonic())) if current else 0,
            "queue": [{"zone": run.zone, "seconds": run.seconds} for run in self._queue.waiting],
            "program": self._program_name(current),
        }


    def _program_name(self, run):
        if run is None or run.program is None:
            return None
        sub = self.hass.config_entries.async_get_entry(self._entry_id).subentries.get(run.program)
        return sub.title if sub else None


class QueueLengthSensor(_QueueSensor):
    """How many zone runs are waiting their turn."""

    _attr_icon = "mdi:format-list-numbered"
    _attr_native_unit_of_measurement = "runs"

    def __init__(self, entry, queue):
        super().__init__(entry, queue, "queued_runs", "Irrigation Queued Runs")

    @property
    def native_value(self):
        return len(self._queue.waiting)

    @property
    def extra_state_attributes(self):
        return {"queued_seconds": sum(run.seconds for run in self._queue.waiting)}


class _ProgramTimeSensor(SensorEntity):
    """Base for a program's next and last run times."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry, subentry, scheduler, key: str, label: str):
        self._entry = entry
        self._subentry_id = subentry.subentry_id
        self._scheduler = scheduler
        self.entity_id = program_entity_id(entry, subentry, "sensor", f"_{key}")
        self._attr_unique_id = f"{entry.entry_id}_{subentry.subentry_id}_{key}"
        self._attr_name = f"{subentry.title} {label}"
        self._attr_device_info = program_device_info(entry, subentry)

    @property
    def _data(self):
        return self._entry.subentries[self._subentry_id].data

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._scheduler.add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()


class ProgramNextRunSensor(_ProgramTimeSensor):
    """When the program next starts, or unknown while its schedule is off."""

    _attr_icon = "mdi:calendar-arrow-right"

    def __init__(self, entry, subentry, scheduler):
        super().__init__(entry, subentry, scheduler, "next_run", "Next Run")

    @property
    def native_value(self) -> datetime | None:
        if not self._data.get("enabled", True):
            return None
        return next_run(self._data, dt_util.now())


class ProgramLastRunSensor(_ProgramTimeSensor):
    """When the program last started."""

    _attr_icon = "mdi:calendar-check"

    def __init__(self, entry, subentry, scheduler):
        super().__init__(entry, subentry, scheduler, "last_run", "Last Run")

    @property
    def native_value(self) -> datetime | None:
        value = self._data.get("last_run")
        return dt_util.parse_datetime(value) if value else None


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the run queue sensors and each program's run times."""
    queue = hass.data[DOMAIN][entry.entry_id]["queue"]
    scheduler = hass.data[DOMAIN][entry.entry_id]["scheduler"]
    async_add_entities([QueueStatusSensor(entry, queue), QueueLengthSensor(entry, queue)])
    for subentry in scheduler.programs():
        async_add_entities(
            [
                ProgramNextRunSensor(entry, subentry, scheduler),
                ProgramLastRunSensor(entry, subentry, scheduler),
            ],
            config_subentry_id=subentry.subentry_id,
        )
