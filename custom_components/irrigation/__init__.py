"""
__init__.py
Irrigation integration bootstrap.
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

DOMAIN = "irrigation"
PLATFORMS = ["switch", "sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the irrigation integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    # This dictionary will hold the switch entities so sensors can find them
    hass.data[DOMAIN][entry.entry_id] = {"switches": {}}

    # Forward setup to switch and sensor platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Handler for the run_zone service
    async def handle_run_zone(call):
        zone = call.data.get("zone")
        duration = call.data.get("duration", entry.data.get("default_duration"))
        
        switches = hass.data[DOMAIN][entry.entry_id]["switches"]
        if zone in switches:
            await switches[zone].async_turn_on(duration=duration)

    # Handler for the stop_zone service
    async def handle_stop_zone(call):
        zone = call.data.get("zone")
        switches = hass.data[DOMAIN][entry.entry_id]["switches"]
        if zone in switches:
            await switches[zone].async_turn_off()

    hass.services.async_register(DOMAIN, "run_zone", handle_run_zone)
    hass.services.async_register(DOMAIN, "stop_zone", handle_stop_zone)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok