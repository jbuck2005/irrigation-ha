"""
__init__.py                                                                                       
Irrigation integration bootstrap.                                                                 
                                                                                                 
- Declares CONFIG_SCHEMA as config_entry_only so hassfest knows this integration                  
  is configured via the UI only.                                                                 
- Sets up the integration by storing config entry data in hass.data and                        
  forwarding platform setup to the `switch` platform.                                           
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

DOMAIN = "irrigation"

# Integration is configured only through Config Entries (UI)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (called when Home Assistant starts)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the irrigation integration from a config entry (UI).

    The entry.data is expected to include:
      - host: irrigationd host (string)
      - port: irrigationd port (int)
      - zones: number of zones to expose (int)
      - default_duration: default run time per zone in seconds (int)
    """
    hass.data.setdefault(DOMAIN, {})
    # Store the entry data for the switch platform to consume
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Forward setup to the switch platform (creates switch entities)
    await hass.config_entries.async_forward_entry_setups(entry, ["switch"])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and its platforms."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
