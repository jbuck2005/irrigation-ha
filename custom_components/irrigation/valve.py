"""Platform for irrigation zone valves."""

import logging
import asyncio
import time

import voluptuous as vol

from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform

from .const import (
    DEFAULT_PORT,
    DEFAULT_ZONES,
    DEFAULT_DURATION,
    CONF_ZONES,
    CONF_DEFAULT_DURATION,
    CONF_ZONE_DURATIONS,
    DOMAIN,
    device_info,
    entity_id_prefix,
)
from .status import safe_reply

_LOGGER = logging.getLogger(__name__)

# How far the local countdown can drift before irrigationd's value replaces it
STATUS_TOLERANCE = 2


class IrrigationZoneValve(ValveEntity):
    """Representation of an irrigation zone as a valve entity."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_reports_position = False
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        host: str,
        port: int,
        zone: int,
        duration: int,
        id_prefix: str,
        device: dict,
    ):
        """Initialize the irrigation valve."""
        self.hass = hass
        # Only suggests the ID for new entities, so existing installs keep theirs
        self.entity_id = f"valve.{id_prefix}_zone_{zone}"
        self._entry_id = entry_id
        self._host = host
        self._port = port
        self._zone = zone
        self._default_duration = duration
        self._is_on = False
        self._remaining = 0
        self._duration = duration
        self._off_timer = None
        self._tick_task = None
        self._last_command = 0.0
        # The zone's last command, which the next one waits for; see _send_command
        self._last_send: asyncio.Task | None = None
        self._attr_device_info = device

    @property
    def available(self):
        """Return false when the zone's real state can't be read."""
        status = self.hass.data[DOMAIN][self._entry_id].get("status")
        return status is None or status.available

    @property
    def unique_id(self):
        """Return a unique ID for this valve."""
        return f"{self._entry_id}_zone_{self._zone}"

    @property
    def name(self):
        """Return the name of the valve."""
        return f"Irrigation Zone {self._zone}"

    @property
    def icon(self):
        """Return the icon for the valve."""
        return "mdi:sprinkler-variant" if self._is_on else "mdi:sprinkler"

    @property
    def is_closed(self):
        """Return true if the valve is closed."""
        return not self._is_on

    @property
    def capability_attributes(self):
        """Return the zone number, which stays set while unavailable."""
        return {"zone": self._zone}

    @property
    def extra_state_attributes(self):
        """Return extra attributes including remaining time and configured duration."""
        queue = self.hass.data[DOMAIN][self._entry_id].get("queue")
        return {
            "remaining": self._remaining,
            # The zone's default run time, and the length of the current or last run
            "configured_duration": self._default_duration,
            "run_duration": self._duration,
            # Waiting, or about to start, so the panel offers Stop rather than Start
            "queued": queue is not None
            and any(run.zone == self._zone for run in queue.runs() if run is not queue.current),
            "master": queue is not None and queue.master_zone == self._zone,
        }

    def _build_command(self, zone: int, seconds: int) -> str:
        """Build a single-line command, without the token, which the client adds if needed."""
        return f"ZONE={zone} TIME={seconds}"

    async def _send_command(self, command: str) -> str:
        """Send a command to irrigationd and return the response.

        Each command goes on its own connection, and two connections can reach
        irrigationd in either order, so a Stop then a start of the same zone
        could arrive start first and leave it closed. So a zone's commands go
        one at a time, each sent once the one before has been answered. The
        command is sent even if the caller is cancelled, so the order holds.
        """
        client = self.hass.data[DOMAIN][self._entry_id]["client"]
        previous = self._last_send

        async def send() -> str:
            if previous is not None:
                await asyncio.wait([previous])
            return await client.async_send(command)

        task = self.hass.async_create_task(send(), f"irrigation zone {self._zone} command")
        task.add_done_callback(lambda done: done.cancelled() or done.exception())
        self._last_send = task
        try:
            return await asyncio.shield(task)
        except Exception as e:  # noqa: BLE001 - reported to the user as a failed command
            _LOGGER.error(
                "Error sending command to irrigationd %s:%s -> %s",
                self._host,
                self._port,
                safe_reply(str(e)),
            )
            return safe_reply(f"ERR {e}")

    @property
    def _queue(self):
        return self.hass.data[DOMAIN][self._entry_id]["queue"]

    async def async_open_valve(self, **kwargs):
        """Run the zone for its default run time, after any zones already running."""
        await self.async_run()

    async def async_run(self, duration=None):
        """Run the zone for a duration (default or specified), through the run queue."""
        if duration is None:
            duration = self._default_duration
        await self._queue.async_enqueue(self._zone, duration)

    async def async_close_valve(self, **kwargs):
        """Close the valve now. If it was running from the queue, the next zone starts."""
        queue = self._queue
        # Noted before the stop is sent: by the time it's answered this zone's
        # time may have ended and the next zone started, which must keep running
        run = queue.current if queue.current is not None and queue.current.zone == self._zone else None
        queue.remove(self._zone)
        try:
            await self.async_send_stop()
        except asyncio.CancelledError:
            # The stop is still sent, so the run is over either way
            if run is not None:
                queue.skip(run)
            raise
        if run is not None:
            queue.skip(run)

    async def async_send_run(self, duration):
        """Tell irrigationd to run this zone now. Only the run queue calls this."""
        command = self._build_command(self._zone, duration)
        response = await self._send_command(command)
        self._last_command = time.monotonic()
        if response.startswith("OK"):
            # A run replaces any earlier one, so drop its timers first
            self._cancel_timers()
            self._duration = duration
            self._start_countdown(duration)
        else:
            raise HomeAssistantError(f"Zone {self._zone} didn't start: {safe_reply(response)}")

    async def async_send_stop(self):
        """Tell irrigationd to close this zone now."""
        command = self._build_command(self._zone, 0)
        response = await self._send_command(command)
        self._last_command = time.monotonic()
        if response.startswith("OK"):
            self._mark_closed()
        else:
            raise HomeAssistantError(f"Zone {self._zone} didn't stop: {safe_reply(response)}")

    def apply_status(self, is_on, seconds, started):
        """Follow irrigationd, unless a command has changed things since `started`."""
        if self._last_command >= started:
            return
        if is_on == self._is_on and abs(seconds - self._remaining) <= STATUS_TOLERANCE:
            return
        if not is_on:
            self._mark_closed()
            return
        self._cancel_timers()
        if not self._is_on or seconds > self._duration:
            self._duration = seconds
        # A valve that won't close reports 1 or 0, so it must not time out here
        if seconds > 1:
            self._start_countdown(seconds)
        else:
            self._is_on = True
            self._remaining = seconds
            self.async_write_ha_state()

    def _start_countdown(self, seconds):
        """Show the zone as open, counting down from `seconds`."""
        self._is_on = True
        self._remaining = seconds
        self.async_write_ha_state()

        # Countdown updater
        async def _tick_remaining():
            while self._remaining > 0 and self._is_on:
                await asyncio.sleep(1)
                self._remaining -= 1
                self.async_write_ha_state()

        # A background task, so a long run doesn't hold up startup or reloads
        self._tick_task = self.hass.async_create_background_task(
            _tick_remaining(), f"irrigation zone {self._zone} countdown"
        )

        # Schedule auto-off after the countdown
        self._off_timer = self.hass.loop.call_later(seconds, self._mark_closed)

    def _mark_closed(self):
        """Show the zone as closed."""
        self._cancel_timers()
        self._is_on = False
        self._remaining = 0
        self.async_write_ha_state()

    def _cancel_timers(self):
        """Cancel the auto-off timer and countdown of the current run."""
        if self._off_timer is not None:
            self._off_timer.cancel()
            self._off_timer = None
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None

    async def async_will_remove_from_hass(self):
        """Cancel timers when the entity is removed, such as on a reload."""
        self._cancel_timers()


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up irrigation valves from a config entry."""
    host = entry.data.get("host", "127.0.0.1")
    port = entry.data.get("port", DEFAULT_PORT)
    zones = entry.data.get(CONF_ZONES, DEFAULT_ZONES)
    default_duration = entry.data.get(CONF_DEFAULT_DURATION, DEFAULT_DURATION)
    zone_durations = entry.data.get(CONF_ZONE_DURATIONS, {})

    entities = []
    for zone in range(1, zones + 1):
        # Get zone-specific duration or fall back to global default
        zone_duration = zone_durations.get(str(zone), default_duration)
        entities.append(
            IrrigationZoneValve(
                hass, entry.entry_id, host, port, zone, zone_duration,
                entity_id_prefix(entry), device_info(entry),
            )
        )

    async_add_entities(entities)

    entity_platform.async_get_current_platform().async_register_entity_service(
        "run",
        {vol.Optional("duration"): vol.All(cv.positive_int, vol.Range(min=10, max=7200))},
        "async_run",
    )

    # Keep reference for service calls
    hass.data[DOMAIN][entry.entry_id]["entities"] = entities