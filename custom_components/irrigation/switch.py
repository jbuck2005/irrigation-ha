"""
switch.py
Home Assistant switch platform for the Irrigation Controller integration.

This file implements a native TCP client so the integration does not depend on
an external `irrigationctl` binary inside the Home Assistant environment.

Features:
- Connects directly to irrigationd over TCP (host/port from config entry)
- Exposes each zone as a SwitchEntity
- Tracks remaining runtime with a per-zone countdown
- Provides progress percentage in extra attributes for UI/progress bars
- Clean ASCII-only source (no box-drawing characters)
"""

import logging
import socket
import asyncio
from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """
    Set up irrigation switches from a config entry.

    The config entry is expected to contain:
      - host: str (irrigationd host)
      - port: int (irrigationd TCP port)
      - zones: int (number of zones)
      - default_duration: int (seconds)
    """
    host = entry.data.get("host", "127.0.0.1")
    port = int(entry.data.get("port", 4242))
    zones = int(entry.data.get("zones", 14))
    default_duration = int(entry.data.get("default_duration", 300))

    entities = []
    for zone in range(1, zones + 1):
        entities.append(IrrigationZoneSwitch(hass, entry.entry_id, host, port, zone, default_duration))

    async_add_entities(entities, update_before_add=True)


class IrrigationZoneSwitch(SwitchEntity):
    """
    Representation of a single irrigation zone as a switch.

    - Turning on sends "ZONE=X TIME=Y" to irrigationd and starts a countdown.
    - Turning off sends "ZONE=X TIME=0" to stop the zone early.
    - Attributes expose remaining seconds, duration and progress_percent.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str, host: str, port: int, zone: int, default_duration: int):
        """Initialize the irrigation zone switch."""
        self.hass = hass
        self._entry_id = entry_id
        self._host = host
        self._port = int(port)
        self._zone = int(zone)
        self._default_duration = int(default_duration)
        self._is_on = False
        self._remaining = 0
        self._duration = self._default_duration
        self._unsub_timer = None

        # Entities API attributes (friendly name / unique id)
        self._attr_name = f"Irrigation Zone {self._zone}"
        self._attr_unique_id = f"irrigation_zone_{self._zone}"

    @property
    def name(self):
        """Return the name of the entity."""
        return self._attr_name

    @property
    def unique_id(self):
        """Return the unique id of the entity."""
        return self._attr_unique_id

    @property
    def is_on(self):
        """Return True if zone is active."""
        return self._is_on

    @property
    def extra_state_attributes(self):
        """Return additional attributes for the zone."""
        pct = 0.0
        if self._duration > 0:
            pct = (self._remaining / self._duration) * 100.0
        return {
            "zone": self._zone,
            "remaining_seconds": int(self._remaining),
            "duration_seconds": int(self._duration),
            "progress_percent": round(pct, 1),
            "host": self._host,
            "port": self._port,
        }

    async def async_turn_on(self, **kwargs):
        """
        Turn the irrigation zone on for a duration (seconds).

        Accepts `duration` in kwargs (integer seconds). Falls back to the default
        duration from configuration when not provided.
        """
        duration = int(kwargs.get("duration", self._default_duration))
        command = f"ZONE={self._zone} TIME={duration}"
        response = await self.hass.async_add_executor_job(self._send_command, command)

        if response is None:
            _LOGGER.error("No response from irrigationd when starting zone %s", self._zone)
            return

        # Expecting "OK" on success
        if response.strip().upper() == "OK":
            self._is_on = True
            self._duration = duration
            self._remaining = duration
            self._start_countdown()
            self.async_write_ha_state()
            _LOGGER.debug("Started zone %s for %ss (host=%s port=%s)", self._zone, duration, self._host, self._port)
        else:
            _LOGGER.error("irrigationd returned error when starting zone %s: %s", self._zone, response)

    async def async_turn_off(self, **kwargs):
        """Turn the irrigation zone off immediately."""
        command = f"ZONE={self._zone} TIME=0"
        response = await self.hass.async_add_executor_job(self._send_command, command)

        if response is None:
            _LOGGER.error("No response from irrigationd when stopping zone %s", self._zone)
            return

        if response.strip().upper() == "OK":
            self._is_on = False
            self._remaining = 0
            self._duration = self._default_duration
            self._cancel_countdown()
            self.async_write_ha_state()
            _LOGGER.debug("Stopped zone %s (host=%s port=%s)", self._zone, self._host, self._port)
        else:
            _LOGGER.error("irrigationd returned error when stopping zone %s: %s", self._zone, response)

    def _send_command(self, command: str):
        """
        Synchronous TCP send/receive used via hass.async_add_executor_job.

        Returns the response string (without newline) or None on error.
        """
        try:
            with socket.create_connection((self._host, self._port), timeout=5) as sock:
                # send command and read a single-line response
                sock.sendall(command.encode("utf-8") + b"\\n")
                data = sock.recv(1024)
                if not data:
                    return None
                return data.decode("utf-8", errors="ignore").strip()
        except Exception as exc:
            _LOGGER.error("Error sending command to irrigationd %s:%s -> %s", self._host, self._port, exc)
            return None

    def _start_countdown(self):
        """Start a repeating callback every second to decrement remaining."""
        # Cancel any existing timer
        if self._unsub_timer is not None:
            try:
                self._unsub_timer()
            except Exception:
                pass
            self._unsub_timer = None

        async def _tick(now):
            # This runs in the event loop (async)
            if self._remaining > 0:
                self._remaining -= 1
                # Update HA every second while active
                self.async_write_ha_state()
            if self._remaining <= 0:
                # Countdown finished; mark off and cancel timer
                self._is_on = False
                self._cancel_countdown()
                self.async_write_ha_state()

        # Register the async tick callback every second
        self._unsub_timer = async_track_time_interval(self.hass, _tick, timedelta(seconds=1))

    def _cancel_countdown(self):
        """Cancel the repeating countdown callback if present."""
        if self._unsub_timer is not None:
            try:
                self._unsub_timer()
            except Exception:
                pass
            self._unsub_timer = None
