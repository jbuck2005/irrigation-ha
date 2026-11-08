"""Buttons to stop everything or skip to the next zone."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN, device_info, entity_id_prefix, program_device_info, program_entity_id


class _QueueButton(ButtonEntity):
    def __init__(self, entry, queue, key: str, name: str, icon: str):
        self._queue = queue
        self.entity_id = f"button.{entity_id_prefix(entry)}_{key}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = device_info(entry)


class StopAllButton(_QueueButton):
    """Clear the queue and close every zone on this controller."""

    def __init__(self, entry, queue):
        super().__init__(entry, queue, "stop_all", "Irrigation Stop All", "mdi:stop-circle-outline")

    async def async_press(self) -> None:
        await self._queue.async_stop_all()


class SkipButton(_QueueButton):
    """End the running zone early and start the next one in the queue."""

    def __init__(self, entry, queue):
        super().__init__(entry, queue, "skip", "Irrigation Skip Zone", "mdi:skip-next-circle-outline")

    async def async_press(self) -> None:
        self._queue.skip()


class RunProgramButton(ButtonEntity):
    """Run a program now, whether or not its schedule is on."""

    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, entry, subentry, scheduler):
        self._entry = entry
        self._subentry_id = subentry.subentry_id
        self._scheduler = scheduler
        self.entity_id = program_entity_id(entry, subentry, "button", "_run_now")
        self._attr_unique_id = f"{entry.entry_id}_{subentry.subentry_id}_run_now"
        self._attr_name = f"{subentry.title} Run Now"
        self._attr_device_info = program_device_info(entry, subentry)

    async def async_press(self) -> None:
        await self._scheduler.async_run(self._entry.subentries[self._subentry_id])


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the run queue buttons and each program's Run now."""
    queue = hass.data[DOMAIN][entry.entry_id]["queue"]
    scheduler = hass.data[DOMAIN][entry.entry_id]["scheduler"]
    async_add_entities([StopAllButton(entry, queue), SkipButton(entry, queue)])
    for subentry in scheduler.programs():
        async_add_entities(
            [RunProgramButton(entry, subentry, scheduler)], config_subentry_id=subentry.subentry_id
        )
