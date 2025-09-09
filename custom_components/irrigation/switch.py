"""
switch.py -- Irrigation zone switches and sensors (with host/port support)
"""

import logging
import subprocess

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

def _run_irrigationctl(zone: int, time: int, host: str, port: int):
    cmd = ["/usr/local/bin/irrigationctl",
           f"--host={host}", f"--port={port}",
           f"ZONE={zone} TIME={time}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            _LOGGER.error("irrigationctl failed: %s", result.stderr.strip())
            return False
        return True
    except Exception as e:
        _LOGGER.exception("Error running irrigationctl: %s", e)
        return False

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    zones = config_entry.data.get("zones", 14)
    default_duration = config_entry.data.get("default_duration", 300)
    host = config_entry.data.get("host", "127.0.0.1")
    port = config_entry.data.get("port", 4242)

    entities = [IrrigationZone(zone, default_duration, host, port) for zone in range(1, zones+1)]
    async_add_entities(entities)

class IrrigationZone(SwitchEntity):
    def __init__(self, zone, default_duration, host, port):
        self._zone = zone
        self._default_duration = default_duration
        self._host = host
        self._port = port
        self._is_on = False

    @property
    def name(self):
        return f"Irrigation Zone {self._zone}"

    @property
    def unique_id(self):
        return f"irrigation_zone_{self._zone}"

    @property
    def is_on(self):
        return self._is_on

    def turn_on(self, **kwargs):
        duration = kwargs.get("duration", self._default_duration)
        if _run_irrigationctl(self._zone, duration, self._host, self._port):
            self._is_on = True
            self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        if _run_irrigationctl(self._zone, 1, self._host, self._port):
            self._is_on = False
            self.schedule_update_ha_state()
