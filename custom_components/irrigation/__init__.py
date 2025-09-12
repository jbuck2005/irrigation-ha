"""Irrigation integration bootstrap."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Home Assistant

from .const import DOMAIN

PLATFORMS = ["switch"]

async def async_setup_entry(hass: Home Assistant, entry: ConfigEntry) -> bool:
    """Set up the irrigation integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: Home Assistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)