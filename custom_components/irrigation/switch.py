"""
switch.py                                                                                          // Switch + Sensor entities for Irrigation integration

This module exposes irrigation zones as Home Assistant switch entities.                           //
It works with the `irrigationctl` command-line tool to control the `irrigationd` daemon.           //

Features:                                                                                         // - Configurable number of zones (from config_flow)
                                                                                                  // - Configurable default run duration (seconds)
                                                                                                  // - Each zone represented as SwitchEntity
                                                                                                  // - Countdown timer with remaining time tracking
                                                                                                  // - Paired SensorEntity per zone for progress bars
                                                                                                  // - Master "All Zones Off" switch (ZONE=0)
                                                                                                  // - Global schedule sensor summarizing active zones
"""

import logging                                                                                    # Python logging for HA logbook
import subprocess                                                                                 # For calling irrigationctl
import asyncio                                                                                   # For countdown timers

from homeassistant.components.switch import SwitchEntity                                          # Base class for switches
from homeassistant.components.sensor import SensorEntity                                          # Base class for sensors
from homeassistant.config_entries import ConfigEntry                                              # For config flow entries
from homeassistant.core import HomeAssistant                                                     # Main HA core class

from . import DOMAIN                                                                              # Integration domain string

_LOGGER = logging.getLogger(__name__)                                                             # Logger instance


# ------------------------------ Helper to call irrigationctl ------------------------------------

def _run_irrigationctl(zone: int, time: int):                                                     # Run irrigationctl with ZONE and TIME
    """Invoke irrigationctl subprocess for given zone and time."""                                #
    cmd = ["/usr/local/bin/irrigationctl", f"ZONE={zone} TIME={time}"]                            # Build command
    try:                                                                                          #
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)                    # Execute with timeout
        if result.returncode != 0:                                                                # Non-zero exit = failure
            _LOGGER.error("irrigationctl failed: %s", result.stderr.strip())                      # Log error
            return False                                                                          # Indicate failure
        _LOGGER.debug("irrigationctl OK: %s", result.stdout.strip())                              # Log success
        return True                                                                               # Indicate success
    except Exception as e:                                                                        # Catch runtime errors
        _LOGGER.exception("Exception calling irrigationctl: %s", e)                               # Log traceback
        return False                                                                              # Indicate failure


# ------------------------------ Platform setup --------------------------------------------------

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):   # Called by HA when integration is set up
    """Set up irrigation entities from config entry."""                                           #
    zones = config_entry.data.get("zones", 14)                                                    # Number of zones (default 14)
    default_duration = config_entry.data.get("default_duration", 300)                             # Default duration in seconds

    entities = []                                                                                 # Collect entities

    # Create zone switches + their paired sensors
    for zone in range(1, zones + 1):                                                              # Loop over zone numbers
        zone_switch = IrrigationZone(hass, zone, default_duration)                                # Create zone switch
        zone_sensor = IrrigationZoneSensor(zone_switch)                                           # Create zone sensor
        zone_switch._linked_sensor = zone_sensor                                                  # Cross-link sensor to switch
        entities.append(zone_switch)                                                              # Add switch
        entities.append(zone_sensor)                                                              # Add sensor

    # Add master switch (all zones off)
    entities.append(IrrigationAllZones(hass, entities))                                           #

    # Add global schedule sensor
    entities.append(IrrigationScheduleSensor(entities))                                           #

    async_add_entities(entities, update_before_add=False)                                         # Register with HA


# ------------------------------ Zone Switch -----------------------------------------------------

class IrrigationZone(SwitchEntity):                                                               # Represents one irrigation zone as a switch
    """Switch entity for a single irrigation zone with countdown tracking."""                     #

    def __init__(self, hass: HomeAssistant, zone: int, default_duration: int):                    #
        self.hass = hass                                                                          # Store HA instance
        self._zone = zone                                                                         # Zone number (1..N)
        self._default_duration = default_duration                                                 # Default run duration (seconds)
        self._attr_name = f"Irrigation Zone {zone}"                                               # Friendly name in HA
        self._attr_unique_id = f"irrigation_zone_{zone}"                                          # Unique ID for HA registry
        self._is_on = False                                                                       # Current on/off state
        self._remaining = 0                                                                       # Seconds remaining
        self._duration = default_duration                                                         # Duration for current run
        self._cancel_task = None                                                                  # Countdown task handle
        self._linked_sensor = None                                                                # Linked sensor entity

    @property
    def is_on(self) -> bool:                                                                      # Required by SwitchEntity
        return self._is_on                                                                        # Return current on/off state

    @property
    def extra_state_attributes(self):                                                             # Extra attributes for UI
        return {                                                                                  #
            "remaining_seconds": self._remaining,                                                 # Remaining runtime
            "duration": self._duration                                                            # Total duration of last run
        }

    def turn_on(self, **kwargs):                                                                  # Called when HA turns switch on
        duration = kwargs.get("duration", self._default_duration)                                 # Use passed or default duration
        if _run_irrigationctl(self._zone, duration):                                              # Call irrigationctl
            self._is_on = True                                                                    # Mark ON
            self._remaining = duration                                                            # Set countdown
            self._duration = duration                                                             #

            if self._cancel_task:                                                                 # Cancel any old countdown
                self._cancel_task.cancel()                                                        #
            self._cancel_task = self.hass.loop.create_task(self._countdown())                     # Start new countdown

            self.schedule_update_ha_state()                                                       # Refresh HA state
            if self._linked_sensor:                                                               # Also refresh sensor
                self._linked_sensor.schedule_update_ha_state()

    def turn_off(self, **kwargs):                                                                 # Called when HA turns switch off
        if _run_irrigationctl(self._zone, 1):                                                     # Send TIME=1 to stop zone
            self._is_on = False                                                                   # Mark OFF
            self._remaining = 0                                                                   # Clear countdown
            if self._cancel_task:                                                                 # Cancel countdown task
                self._cancel_task.cancel()                                                        #
                self._cancel_task = None                                                          #
            self.schedule_update_ha_state()                                                       # Refresh HA state
            if self._linked_sensor:                                                               # Refresh linked sensor
                self._linked_sensor.schedule_update_ha_state()

    async def _countdown(self):                                                                   # Async countdown loop
        try:                                                                                      #
            while self._remaining > 0:                                                            # While time left
                await asyncio.sleep(1)                                                            # Wait 1 second
                self._remaining -= 1                                                              # Decrement counter
                if self._remaining % 5 == 0 or self._remaining == 0:                               # Update HA every 5s or final tick
                    self.schedule_update_ha_state()                                               #
                    if self._linked_sensor:                                                       #
                        self._linked_sensor.schedule_update_ha_state()
            self._is_on = False                                                                   # Countdown ended → mark OFF
            self.schedule_update_ha_state()                                                       #
            if self._linked_sensor:                                                               # Refresh sensor
                self._linked_sensor.schedule_update_ha_state()
        except asyncio.CancelledError:                                                            # Task cancelled early
            pass                                                                                  #
        finally:                                                                                  #
            self._cancel_task = None                                                              # Clear task handle


# ------------------------------ Zone Sensor -----------------------------------------------------

class IrrigationZoneSensor(SensorEntity):                                                         # Sensor shows countdown per zone
    """Sensor entity for a zone's remaining time and progress."""                                 #

    def __init__(self, zone_switch: IrrigationZone):                                              #
        self._zone_switch = zone_switch                                                           # Link back to switch
        self._attr_name = f"{zone_switch._attr_name} Remaining"                                   # Friendly name
        self._attr_unique_id = f"{zone_switch._attr_unique_id}_remaining"                         # Unique ID

    @property
    def native_unit_of_measurement(self):                                                         #
        return "s"                                                                                # Remaining seconds

    @property
    def native_value(self):                                                                       #
        return self._zone_switch._remaining                                                       # Current countdown

    @property
    def extra_state_attributes(self):                                                             #
        dur = self._zone_switch._duration                                                         # Duration of this run
        rem = self._zone_switch._remaining                                                        # Seconds remaining
        pct = (rem / dur * 100) if dur > 0 else 0                                                 # Progress %
        return {                                                                                  #
            "duration": dur,                                                                      #
            "remaining": rem,                                                                     #
            "progress_percent": round(pct, 1)                                                     #
        }


# ------------------------------ Master Switch ---------------------------------------------------

class IrrigationAllZones(SwitchEntity):                                                           # Master switch → clears all zones
    """Momentary switch to shut off all irrigation zones."""                                      #

    def __init__(self, hass: HomeAssistant, entities):                                            #
        self.hass = hass                                                                          #
        self._entities = [e for e in entities if isinstance(e, IrrigationZone)]                   # Keep only zone switches
        self._attr_name = "Irrigation All Zones"                                                  # Friendly name
        self._attr_unique_id = "irrigation_all_zones"                                             # Unique ID
        self._is_on = False                                                                       # Current state

    @property
    def is_on(self) -> bool:                                                                      #
        return self._is_on                                                                        #

    def turn_on(self, **kwargs):                                                                  #
        if _run_irrigationctl(0, 1):                                                              # Send ZONE=0 to clear all
            for z in self._entities:                                                              # Reset each zone locally
                z._is_on = False                                                                  #
                z._remaining = 0                                                                  #
                if z._cancel_task:                                                                #
                    z._cancel_task.cancel()                                                       #
                    z._cancel_task = None                                                         #
                z.schedule_update_ha_state()                                                      #
                if z._linked_sensor:                                                              #
                    z._linked_sensor.schedule_update_ha_state()
            self._is_on = True                                                                    # Mark ON (momentary)
            self.schedule_update_ha_state()                                                       #
            self.hass.loop.create_task(self._auto_reset())                                        # Reset after 1s

    def turn_off(self, **kwargs):                                                                 #
        self._is_on = False                                                                       #
        self.schedule_update_ha_state()                                                           #

    async def _auto_reset(self):                                                                  #
        await asyncio.sleep(1)                                                                    #
        self._is_on = False                                                                       # Reset state
        self.schedule_update_ha_state()                                                           # Update HA


# ------------------------------ Global Schedule Sensor ------------------------------------------

class IrrigationScheduleSensor(SensorEntity):                                                     # Summarizes active zones
    """Global sensor showing number of active zones + their times."""                             #

    def __init__(self, entities):                                                                 #
        self._zones = [e for e in entities if isinstance(e, IrrigationZone)]                      # Track all zone switches
        self._attr_name = "Irrigation Active Schedule"                                            # Friendly name
        self._attr_unique_id = "irrigation_schedule"                                              # Unique ID

    @property
    def native_unit_of_measurement(self):                                                         #
        return "zones"                                                                            # Number of zones

    @property
    def native_value(self):                                                                       #
        return sum(1 for z in self._zones if z.is_on)                                             # Count active zones

    @property
    def extra_state_attributes(self):                                                             #
        active = [                                                                                #
            {"zone": z._zone, "remaining": z._remaining}                                          #
            for z in self._zones if z.is_on                                                       #
        ]                                                                                         #
        return {                                                                                  #
            "active_zones": active,                                                               #
            "total_active": len(active)                                                           #
        }
