"""
__init__.py                                                                                        // Irrigation integration bootstrap

Handles setup and teardown of the irrigation integration.                                         //
Forwards config entries to the `switch` platform.                                                 //
"""

from homeassistant.config_entries import ConfigEntry                                              # Config entry API
from homeassistant.core import HomeAssistant                                                     # HA core object
from homeassistant.helpers.typing import ConfigType                                              # Type hints

DOMAIN = "irrigation"                                                                             # Integration domain string


# ------------------------------ Setup from YAML -------------------------------------------------

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:                           # Called at HA startup
    """YAML setup (not used, provided for compatibility)."""                                      #
    hass.data.setdefault(DOMAIN, {})                                                              # Ensure storage dict
    return True                                                                                   # Success


# ------------------------------ Setup from Config Entry -----------------------------------------

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:                     # Called when integration added via UI
    """Set up irrigation integration from a config entry."""                                      #
    hass.data.setdefault(DOMAIN, {})                                                              # Ensure storage dict
    hass.data[DOMAIN][entry.entry_id] = entry.data                                                # Save entry data

    # Forward to the switch platform
    await hass.config_entries.async_forward_entry_setups(entry, ["switch"])                       # Load switch entities
    return True                                                                                   # Success


# ------------------------------ Unload Config Entry ---------------------------------------------

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:                    # Called when integration removed
    """Unload a config entry."""                                                                  #
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch"])               # Unload switch platform
    if unload_ok:                                                                                 #
        hass.data[DOMAIN].pop(entry.entry_id)                                                     # Remove from storage
    return unload_ok                                                                              # Success/failure