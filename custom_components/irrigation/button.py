"""Buttons to stop everything or skip to the next zone."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN, device_info, entity_id_prefix


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


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the run queue buttons."""
    queue = hass.data[DOMAIN][entry.entry_id]["queue"]
    async_add_entities([StopAllButton(entry, queue), SkipButton(entry, queue)])
