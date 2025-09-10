"""
Home Assistant switch platform for the irrigation controller.
---------------------------------------------------------------------------------
This integration connects to irrigationd over TCP (default port 4242).
Each irrigation zone is exposed as a switch entity.

Features:
- Turn zone ON: sends "ZONE=<n> TIME=<seconds>" to irrigationd.
- Turn zone OFF: sends "ZONE=<n> TIME=0" (patched irrigationd supports immediate stop).
- Tracks remaining runtime with countdown timer.
- Provides attributes: remaining_seconds, duration_seconds, progress_percent.
---------------------------------------------------------------------------------
"""

import logging
import socket
import asyncio
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 4242
BUFFER_SIZE = 1024


class IrrigationZoneSwitch(SwitchEntity):
    def __init__(self, hass: HomeAssistant, host: str, port: int, zone: int, duration: int):
        self.hass = hass
        self._host = host
        self._port = port
        self._zone = zone
        self._default_duration = duration
        self._is_on = False
        self._remaining = 0
        self._duration = duration

    @property
    def name(self):
        """Return the name of the entity."""
        return f"Irrigation Zone {self._zone}"

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._is_on

    @property
    def extra_state_attributes(self):
        """Return extra attributes for progress tracking."""
        progress = 0
        if self._duration > 0:
            progress = int((self._remaining / self._duration) * 100)
        return {
            "remaining_seconds": self._remaining,
            "duration_seconds": self._duration,
            "progress_percent": progress,
        }

    def _send_command(self, command: str) -> str:
        """Send a command to irrigationd over TCP and return the response."""
        try:
            with socket.create_connection((self._host, self._port), timeout=5) as sock:
                sock.sendall(command.encode("utf-8") + b"\n")
                data = sock.recv(BUFFER_SIZE)
                return data.decode("utf-8").strip()
        except Exception as e:
            _LOGGER.error("Error sending command to irrigationd %s:%s -> %s", self._host, self._port, e)
            return f"ERR {e}"

    async def async_turn_on(self, **kwargs):
        """Turn the irrigation zone ON for the configured duration."""
        duration = kwargs.get("duration", self._default_duration)
        command = f"ZONE={self._zone} TIME={duration}"
        response = await self.hass.async_add_executor_job(self._send_command, command)
        if response.strip() == "OK":
            self._is_on = True
            self._remaining = duration
            self._duration = duration
            self.async_write_ha_state()
            # Start countdown updater
            self.hass.loop.create_task(self._countdown())
        else:
            _LOGGER.error("Failed to turn on Zone %s: %s", self._zone, response)

    async def async_turn_off(self, **kwargs):
        """Turn the irrigation zone OFF immediately (TIME=0)."""
        command = f"ZONE={self._zone} TIME=0"
        response = await self.hass.async_add_executor_job(self._send_command, command)
        if response.strip() == "OK":
            self._is_on = False
            self._remaining = 0
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to turn off Zone %s: %s", self._zone, response)

    async def _countdown(self):
        """Decrement remaining seconds until zone turns off."""
        while self._is_on and self._remaining > 0:
            await asyncio.sleep(1)
            self._remaining -= 1
            self.async_write_ha_state()
        if self._remaining <= 0:
            self._is_on = False
            self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up irrigation zones from a config entry."""
    host = entry.data.get("host", "127.0.0.1")
    port = entry.data.get("port", DEFAULT_PORT)
    zones = entry.data.get("zones", 4)
    duration = entry.data.get("default_duration", 300)

    entities = []
    for zone in range(1, zones + 1):
        entities.append(IrrigationZoneSwitch(hass, host, port, zone, duration))

    async_add_entities(entities)
