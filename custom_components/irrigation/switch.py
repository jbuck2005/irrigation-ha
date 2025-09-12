"""Platform for irrigation switches."""
import logging
import socket
import asyncio
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_ZONES,
    DEFAULT_DURATION,
    CONF_TOKEN,
)

_LOGGER = logging.getLogger(__name__)
BUFFER_SIZE = 1024

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up irrigation switches from a config entry."""
    host = entry.data.get("host")
    port = entry.data.get("port")
    zones = entry.data.get("zones")
    duration = entry.data.get("default_duration")
    token = entry.data.get(CONF_TOKEN)

    switches = [
        IrrigationZoneSwitch(hass, entry.entry_id, host, port, zone, duration, token)
        for zone in range(1, zones + 1)
    ]
    async_add_entities(switches)

    # Register service handlers
    async def handle_run_zone(call):
        zone_to_run = call.data.get("zone")
        run_duration = call.data.get("duration", duration)
        for switch in switches:
            if switch.zone == zone_to_run:
                await switch.async_turn_on(duration=run_duration)
                break

    async def handle_stop_zone(call):
        zone_to_stop = call.data.get("zone")
        for switch in switches:
            if switch.zone == zone_to_stop:
                await switch.async_turn_off()
                break

    hass.services.async_register(DOMAIN, "run_zone", handle_run_zone)
    hass.services.async_register(DOMAIN, "stop_zone", handle_stop_zone)


class IrrigationZoneSwitch(SwitchEntity):
    """Representation of an irrigation zone as a switch entity with a timer."""

    def __init__(self, hass, entry_id, host, port, zone, duration, token):
        self.hass = hass
        self._host = host
        self._port = port
        self.zone = zone
        self._default_duration = duration
        self._token = token
        
        self._is_on = False
        self._remaining = 0
        self._timer_task = None
        
        self._attr_name = f"Irrigation Zone {zone}"
        self._attr_unique_id = f"irrigation_{entry_id}_zone_{zone}"
        self._attr_icon = "mdi:sprinkler-variant"

    @property
    def is_on(self):
        """Return true if the switch is on."""
        return self._is_on

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {"remaining_seconds": self._remaining}

    async def _timer(self, duration):
        """Timer coroutine that updates the state."""
        self._remaining = duration
        while self._remaining > 0:
            self.async_write_ha_state()
            await asyncio.sleep(1)
            self._remaining -= 1
        
        self._is_on = False
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        duration = kwargs.get("duration", self._default_duration)
        command = f"ZONE={self.zone} TIME={duration}"
        if self._token:
            command += f" TOKEN={self._token}"

        response = await self.hass.async_add_executor_job(self._send_command, command)

        if "OK" in response:
            self._is_on = True
            if self._timer_task:
                self._timer_task.cancel()
            self._timer_task = self.hass.async_create_task(self._timer(duration))
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to turn on zone %d: %s", self.zone, response)

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
        
        command = f"ZONE={self.zone} TIME=0"
        if self._token:
            command += f" TOKEN={self._token}"

        response = await self.hass.async_add_executor_job(self._send_command, command)
        
        if "OK" in response:
            self._is_on = False
            self._remaining = 0
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to turn off zone %d: %s", self.zone, response)

    def _send_command(self, command):
        """Send a command to the irrigation daemon."""
        try:
            with socket.create_connection((self._host, self._port), timeout=5) as s:
                s.sendall(command.encode("utf-8") + b"\\n")
                return s.recv(BUFFER_SIZE).decode("utf-8").strip()
        except Exception as e:
            _LOGGER.error("Error communicating with irrigationd: %s", e)
            return f"ERR: {e}"