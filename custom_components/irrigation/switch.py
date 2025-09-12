"""Platform for irrigation switches."""
import logging
import socket
import asyncio
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from .const import DEFAULT_PORT, DEFAULT_ZONES, DEFAULT_DURATION, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)
BUFFER_SIZE = 1024

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up irrigation switches from a config entry."""
    host = entry.data.get("host", "127.0.0.1")
    port = entry.data.get("port", DEFAULT_PORT)
    zones = entry.data.get("zones", DEFAULT_ZONES)
    duration = entry.data.get("default_duration", DEFAULT_DURATION)
    token = entry.data.get(CONF_TOKEN)

    switches = []
    for zone in range(1, zones + 1):
        switch = IrrigationZoneSwitch(hass, entry.entry_id, host, port, zone, duration, token)
        switches.append(switch)
        hass.data[DOMAIN][entry.entry_id]["switches"][zone] = switch
    
    async_add_entities(switches)


class IrrigationZoneSwitch(SwitchEntity):
    """Representation of an irrigation zone as a switch entity."""

    def __init__(self, hass, entry_id, host, port, zone, duration, token):
        self.hass = hass
        self._entry_id = entry_id
        self._host = host
        self._port = port
        self.zone = zone
        self._default_duration = duration
        self._is_on = False
        self.remaining = 0
        self._duration = duration
        self._token = token
        self._timer_task = None

    @property
    def name(self):
        return f"Irrigation Zone {self.zone}"
        
    @property
    def unique_id(self):
        return f"irrigation_{self._entry_id}_zone_{self.zone}_switch"

    @property
    def is_on(self):
        return self._is_on

    @property
    def extra_state_attributes(self):
        return {
            "configured_duration": self._duration,
            "remaining_seconds": self.remaining
        }

    def _build_command(self, zone, seconds):
        if self._token:
            return f"ZONE={zone} TIME={seconds} TOKEN={self._token}"
        return f"ZONE={zone} TIME={seconds}"

    def _send_command(self, command):
        try:
            with socket.create_connection((self._host, self._port), timeout=5) as sock:
                sock.sendall(command.encode("utf-8") + b"\\n")
                return sock.recv(BUFFER_SIZE).decode("utf-8").strip()
        except Exception as e:
            _LOGGER.error("Error sending command to irrigationd: %s", e)
            return f"ERR {e}"

    async def _timer(self, duration):
        self.remaining = duration
        while self.remaining > 0:
            self.async_write_ha_state()
            await asyncio.sleep(1)
            self.remaining -= 1
        
        self._is_on = False
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        duration = kwargs.get("duration", self._default_duration)
        command = self._build_command(self.zone, duration)
        response = await self.hass.async_add_executor_job(self._send_command, command)

        if response.startswith("OK"):
            self._is_on = True
            self._duration = duration
            
            if self._timer_task:
                self._timer_task.cancel()
            
            self._timer_task = self.hass.async_create_task(self._timer(duration))
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to turn on zone %s: %s", self.zone, response)

    async def async_turn_off(self, **kwargs):
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
            
        command = self._build_command(self.zone, 0)
        response = await self.hass.async_add_executor_job(self._send_command, command)

        if response.startswith("OK"):
            self._is_on = False
            self.remaining = 0
            self.async_write_ha_state()
        else:
            _LOGGER.warning("Failed to turn off zone %s: %s", self.zone, response)