"""Sensors that show what a controller's run queue is doing."""

from __future__ import annotations

import time

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import callback

from .const import DOMAIN, device_info, entity_id_prefix

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"


class _QueueSensor(SensorEntity):
    """Base for sensors that update whenever the run queue changes."""

    _attr_should_poll = False

    def __init__(self, entry, queue, key: str, name: str):
        self._queue = queue
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
        }


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


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the run queue sensors."""
    queue = hass.data[DOMAIN][entry.entry_id]["queue"]
    async_add_entities([QueueStatusSensor(entry, queue), QueueLengthSensor(entry, queue)])
