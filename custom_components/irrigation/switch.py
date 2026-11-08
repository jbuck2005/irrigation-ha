"""A switch per program that turns its schedule on and off."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.helpers import entity_platform

from .const import DOMAIN, program_device_info, program_entity_id


class ProgramSwitch(SwitchEntity):
    """On while the program runs at its start times. Run now works either way."""

    _attr_should_poll = False
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry, subentry, scheduler):
        self._entry = entry
        self._subentry_id = subentry.subentry_id
        self._scheduler = scheduler
        self.entity_id = program_entity_id(entry, subentry, "switch", "")
        self._attr_unique_id = f"{entry.entry_id}_{subentry.subentry_id}_enabled"
        self._attr_name = f"{subentry.title} Schedule"
        self._attr_device_info = program_device_info(entry, subentry)

    @property
    def _subentry(self):
        return self._entry.subentries[self._subentry_id]

    @property
    def is_on(self) -> bool:
        return bool(self._subentry.data.get("enabled", True))

    @property
    def extra_state_attributes(self):
        data = self._subentry.data
        return {
            "running": self._scheduler.is_running(self._subentry_id),
            "start_times": data.get("start_times", []),
            "days": data.get("days"),
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._scheduler.add_listener(self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        self._scheduler.set_enabled(self._subentry, True)

    async def async_turn_off(self, **kwargs) -> None:
        self._scheduler.set_enabled(self._subentry, False)

    async def async_run_program(self) -> None:
        """Run the program now, whether or not its schedule is on."""
        await self._scheduler.async_run(self._subentry)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up a schedule switch for each program."""
    scheduler = hass.data[DOMAIN][entry.entry_id]["scheduler"]
    for subentry in scheduler.programs():
        async_add_entities(
            [ProgramSwitch(entry, subentry, scheduler)], config_subentry_id=subentry.subentry_id
        )
    entity_platform.async_get_current_platform().async_register_entity_service(
        "run_program", {}, "async_run_program"
    )
