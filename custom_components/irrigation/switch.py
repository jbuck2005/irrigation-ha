"""Platform for irrigation switches."""

import logging
import socket
import asyncio

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant

from .const import DEFAULT_PORT, DEFAULT_ZONES, DEFAULT_DURATION, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

BUFFER_SIZE = 1024


class IrrigationZoneSwitch(SwitchEntity):
    """Representation of an irrigation zone as a switch entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        zone: int,
        duration: int,
        token: str = None,
    ):
        """Initialize the irrigation switch."""
        self.hass = hass
        self._host = host
        self._port = port
        self._zone = zone
        self._default_duration = duration
        self._is_on = False
        self._remaining = 0
        self._duration = duration
        self._token = token

    @property
    def name(self):
        """Return the name of the switch."""
        return f"Irrigation Zone {self._zone}"

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._is_on

    @property
    def extra_state_attributes(self):
        """Return extra attributes including remaining time and configured duration."""
        return {
            "remaining": self._remaining,
            "configured_duration": self._duration,
        }

    def _build_command(self, zone: int, seconds: int) -> str:
        """Build a single-line command string to send to irrigationd."""
        if self._token:
            return f"ZONE={zone} TIME={seconds} TOKEN={self._token}"
        return f"ZONE={zone} TIME={seconds}"

    def _send_command(self, command: str) -> str:
        """Send a command to irrigationd over TCP and return the response."""
        try:
            with socket.create_connection((self._host, self._port), timeout=5) as sock:
                sock.sendall(command.encode("utf-8") + b"\n")
                data = sock.recv(BUFFER_SIZE)
                return data.decode("utf-8").strip()
        except Exception as e:
            _LOGGER.error(
                "Error sending command to irrigationd %s:%s -> %s",
                self._host,
                self._port,
                e,
            )
            return f"ERR {e}"

    async def async_turn_on(self, **kwargs):
        """Turn the switch on for a duration (default or specified)."""
        duration = kwargs.get("duration", self._default_duration)
        command = self._build_command(self._zone, duration)
        response = await self.hass.async_add_executor_job(self._send_command, command)
        if response.startswith("OK"):
            self._is_on = True
            self._remaining = duration
            self._duration = duration
            self.async_write_ha_state()

            # Countdown updater
            async def _tick_remaining():
                while self._remaining > 0 and self._is_on:
                    await asyncio.sleep(1)
                    self._remaining -= 1
                    self.async_write_ha_state()

            self.hass.async_create_task(_tick_remaining())

            # Schedule auto-off after duration
            async def _auto_off(_now):
                self._is_on = False
                self._remaining = 0
                self.async_write_ha_state()

            self.hass.loop.call_later(
                duration, lambda: self.hass.async_create_task(_auto_off(None))
            )
        else:
            _LOGGER.warning("Failed to turn on zone %s: %s", self._zone, response)

    async def async_turn_off(self, **kwargs):
        """Turn the switch off immediately."""
        command = self._build_command(self._zone, 0)
        response = await self.hass.async_add_executor_job(self._send_command, command)
        if response.startswith("OK"):
            self._is_on = False
            self._remaining = 0
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to turn off zone %s: %s", self._zone, response)

    async def stop(self):
        """Helper to stop irrigation immediately (alias for turn_off)."""
        await self.async_turn_off()


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up irrigation switches from a config entry."""
    host = entry.data.get("host", "127.0.0.1")
    port = entry.data.get("port", DEFAULT_PORT)
    zones = entry.data.get("zones", DEFAULT_ZONES)
    duration = entry.data.get("default_duration", DEFAULT_DURATION)
    token = entry.data.get(CONF_TOKEN)

    entities = []
    for zone in range(1, zones + 1):
        entities.append(IrrigationZoneSwitch(hass, host, port, zone, duration, token))

    async_add_entities(entities)

    # Keep reference for service calls
    hass.data[DOMAIN][entry.entry_id]["entities"] = entities