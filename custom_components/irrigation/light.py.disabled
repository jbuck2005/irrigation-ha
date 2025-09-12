"""Platform for irrigation lights."""

import logging
import socket
import asyncio

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant

from .const import DEFAULT_PORT, DEFAULT_ZONES, DEFAULT_DURATION, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

BUFFER_SIZE = 1024


class IrrigationZoneLight(LightEntity):
    """Representation of an irrigation zone as a light entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        zone: int,
        duration: int,
        token: str = None,
    ):
        """Initialize the irrigation light."""
        self.hass = hass
        self._host = host
        self._port = port
        self._zone = zone
        self._default_duration = duration
        self._is_on = False
        self._remaining = 0
        self._duration = duration
        self._token = token
        self._brightness = 0

    @property
    def name(self):
        """Return the name of the light."""
        return f"Irrigation Zone {self._zone}"

    @property
    def is_on(self):
        """Return true if light is on."""
        return self._is_on

    @property
    def brightness(self):
        """Return the brightness of the light."""
        return self._brightness

    @property
    def color_mode(self) -> str:
        """Return the color mode of the light."""
        return ColorMode.BRIGHTNESS

    @property
    def supported_color_modes(self):
        """Flag supported color modes."""
        return {ColorMode.BRIGHTNESS}

    @property
    def extra_state_attributes(self):
        """Return extra attributes including remaining time and configured duration."""
        return {
            "remaining_seconds": self._remaining,
            "configured_duration_seconds": self._duration,
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
        """Turn the light on for a duration based on brightness."""
        brightness = kwargs.get(ATTR_BRIGHTNESS, 255)

        # Duration is a percentage of the default duration
        duration = int((brightness / 255) * self._default_duration)

        await self.async_turn_on_with_duration(duration)

    async def async_turn_on_with_duration(self, duration: int):
        """Turn the light on for a specific duration."""

        command = self._build_command(self._zone, duration)
        response = await self.hass.async_add_executor_job(self._send_command, command)
        if response.startswith("OK"):
            self._is_on = True
            self._remaining = duration
            self._duration = duration
            self._brightness = 255  # Start at full brightness
            self.async_write_ha_state()

            # Countdown updater
            async def _tick_remaining():
                while self._remaining > 0 and self._is_on:
                    await asyncio.sleep(1)
                    if self._is_on:  # check again in case it was turned off
                        self._remaining -= 1
                        if self._duration > 0:
                            self._brightness = int(
                                (self._remaining / self._duration) * 255
                            )
                        else:
                            self._brightness = 0
                        self.async_write_ha_state()

            self.hass.async_create_task(_tick_remaining())

            # Schedule auto-off after duration
            async def _auto_off(_now):
                if self._is_on:
                    self._is_on = False
                    self._remaining = 0
                    self._brightness = 0
                    self.async_write_ha_state()

            self.hass.loop.call_later(
                duration, lambda: self.hass.async_create_task(_auto_off(None))
            )
        else:
            _LOGGER.warning("Failed to turn on zone %s: %s", self._zone, response)

    async def async_turn_off(self, **kwargs):
        """Turn the light off immediately."""
        command = self._build_command(self._zone, 0)
        response = await self.hass.async_add_executor_job(self._send_command, command)
        if response.startswith("OK"):
            self._is_on = False
            self._remaining = 0
            self._brightness = 0
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to turn off zone %s: %s", self._zone, response)

    async def stop(self):
        """Helper to stop irrigation immediately (alias for turn_off)."""
        await self.async_turn_off()


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up irrigation lights from a config entry."""
    host = entry.data.get("host", "127.0.0.1")
    port = entry.data.get("port", DEFAULT_PORT)
    zones = entry.data.get("zones", DEFAULT_ZONES)
    duration = entry.data.get("default_duration", DEFAULT_DURATION)
    token = entry.data.get(CONF_TOKEN)

    entities = []
    for zone in range(1, zones + 1):
        entities.append(IrrigationZoneLight(hass, host, port, zone, duration, token))

    async_add_entities(entities)

    # Keep reference for service calls
    hass.data[DOMAIN][entry.entry_id]["entities"] = entities