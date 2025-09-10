"""
Home Assistant switch platform for the Irrigation Controller integration.                  
This version replaces subprocess calls to the `irrigationctl` binary with a native        
Python TCP client that talks directly to `irrigationd`.                                   
                                                                                          
Advantages of this approach:                                                              
- Removes dependency on external binaries inside Home Assistant.                          
- Works regardless of whether HA is containerized or in a venv.                           
- Uses the same protocol as `irrigationctl` (simple TCP send/receive).                    
"""

import logging
import socket
import asyncio
from datetime import timedelta
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up irrigation switches from a config entry.                                   
                                                                                          
    This method is called by Home Assistant when the integration is initialized. It       
    receives the configuration entry (with host, port, zones, and default duration),      
    creates the switch entities for each irrigation zone, and registers them with HA.     
    """
    host = entry.data["host"]                                                             # Host of irrigationd server
    port = entry.data["port"]                                                             # Port of irrigationd server
    zones = entry.data["zones"]                                                           # Number of irrigation zones
    default_duration = entry.data["default_duration"]                                     # Default runtime per zone

    switches = []
    for zone in range(1, zones + 1):
        switches.append(
            IrrigationZoneSwitch(entry, host, port, zone, default_duration)
        )
    async_add_entities(switches, True)


class IrrigationZoneSwitch(SwitchEntity):
    """Representation of a single irrigation zone as a switch.                           
                                                                                          
    Each zone is exposed as a separate switch entity in Home Assistant. Turning the       
    switch on sends a TCP command to `irrigationd` to activate the zone for a specified   
    duration. Turning it off sends a command to stop the zone. The entity also tracks     
    remaining runtime with a countdown timer, so HA can display progress.                 
    """

    def __init__(self, entry, host, port, zone, default_duration):
        """Initialize the irrigation zone switch.                                        
                                                                                          
        Args:                                                                             
            entry: Config entry containing host/port/zones/duration.                      
            host:  Hostname or IP address of irrigationd server.                          
            port:  TCP port where irrigationd is listening.                               
            zone:  Zone number for this switch.                                           
            default_duration: Default run time in seconds if none specified.              
        """
        self._entry = entry                                                               # Parent config entry
        self._host = host                                                                 # irrigationd host
        self._port = port                                                                 # irrigationd port
        self._zone = zone                                                                 # Zone number
        self._default_duration = default_duration                                         # Default runtime (seconds)
        self._is_on = False                                                               # Whether zone is active
        self._remaining = 0                                                               # Countdown remaining (sec)
        self._unsub_timer = None                                                          # Timer unsubscribe handle

    @property
    def name(self):
        """Return the name of the entity."""                                             
        return f"Irrigation Zone {self._zone}"

    @property
    def unique_id(self):
        """Return a unique ID for this entity."""                                        
        return f"irrigation_zone_{self._zone}"

    @property
    def is_on(self):
        """Return True if the switch is currently on."""                                 
        return self._is_on

    @property
    def extra_state_attributes(self):
        """Return custom attributes including remaining runtime.                         
                                                                                          
        Attributes:                                                                       
            remaining: Seconds left before the zone turns off automatically.              
            default_duration: Default run time if no duration is specified.               
            zone: Zone number for this entity.                                            
            host: irrigationd server host.                                                
            port: irrigationd server port.                                                
        """
        return {
            "remaining": self._remaining,
            "default_duration": self._default_duration,
            "zone": self._zone,
            "host": self._host,
            "port": self._port,
        }

    async def async_turn_on(self, **kwargs):
        """Turn the irrigation zone on.                                                  
                                                                                          
        Sends a TCP command to irrigationd requesting activation of this zone for         
        the specified duration. If no duration is provided, falls back to the default.    
        Starts a countdown timer to track remaining runtime in HA.                        
        """
        duration = kwargs.get("duration", self._default_duration)
        command = f"ZONE={self._zone} TIME={duration}"
        response = await self.hass.async_add_executor_job(
            self._send_command, command
        )
        if response == "OK":
            self._is_on = True
            self._remaining = duration
            self._start_timer()                                                           # Begin countdown updates
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to start zone %s: %s", self._zone, response)

    async def async_turn_off(self, **kwargs):
        """Turn the irrigation zone off.                                                 
                                                                                          
        Sends a TCP command to irrigationd requesting this zone to stop immediately.      
        Cancels the countdown timer and updates HA state.                                 
        """
        command = f"ZONE={self._zone} TIME=0"
        response = await self.hass.async_add_executor_job(
            self._send_command, command
        )
        if response == "OK":
            self._is_on = False
            self._remaining = 0
            self._cancel_timer()                                                          # Stop countdown updates
            self.async_write_ha_state()
        else:
            _LOGGER.error("Failed to stop zone %s: %s", self._zone, response)

    def _send_command(self, command):
        """Send a command to the irrigationd TCP server.                                 
                                                                                          
        This method opens a TCP socket to the configured host/port, sends the command,    
        and waits for a response. Returns the response string, or None if an error        
        occurred.                                                                          
        """
        try:
            with socket.create_connection((self._host, self._port), timeout=5) as sock:
                sock.sendall(command.encode("utf-8") + b"\n")
                response = sock.recv(1024).decode("utf-8").strip()
                return response
        except Exception as e:
            _LOGGER.error("Error sending command to irrigationd: %s", e)
            return None

    def _start_timer(self):
        """Start a countdown timer to track remaining runtime.                           
                                                                                          
        Registers a repeating callback every second to decrement the `remaining`          
        attribute and update HA state. When remaining reaches zero, turns the zone        
        off and cancels the timer.                                                        
        """
        if self._unsub_timer:
            self._unsub_timer()

        async def _tick(now):
            if self._remaining > 0:
                self._remaining -= 1
                self.async_write_ha_state()
            if self._remaining <= 0:
                self._is_on = False
                self._cancel_timer()
                self.async_write_ha_state()

        self._unsub_timer = async_track_time_interval(
            self.hass, _tick, timedelta(seconds=1)
        )

    def _cancel_timer(self):
        """Cancel the countdown timer.                                                   
                                                                                          
        Unsubscribes from the timer callback if active. Ensures HA stops updating          
        the countdown once the zone is off.                                               
        """
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None