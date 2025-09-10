"""
__init__.py                                                                                        // Irrigation integration bootstrap

Sets up the Irrigation integration (config-entry only).                                            //
This tells Home Assistant that the integration cannot be configured in YAML,                      //
only via the UI (Config Flow).                                                                    //
"""

from homeassistant.config_entries import ConfigEntry                                               # For handling config entries
from homeassistant.core import HomeAssistant                                                      # Core HA object
from homeassistant.helpers.typing import ConfigType                                                # Type hints for config
from homeassistant.helpers import config_validation as cv                                          # Validation helpers

DOMAIN = "irrigation"                                                                              # Integration domain string

# ------------------------------ CONFIG SCHEMA ---------------------------------------------------
# This integration is *config-entry only* (UI setup), no YAML support.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


# ------------------------------ SETUP FROM YAML -------------------------------------------------
async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """YAML setup (not supported, provided for compatibility)."""                                 #
    hass.data.setdefault(DOMAIN, {})                                                              # Ensure storage dict
    return True                                                                                   # Always return True


# ------------------------------ SETUP ENTRY -----------------------------------------------------
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up irrigation integration from a config entry."""                                      #
    hass.data.setdefault(DOMAIN, {})                                                              # Ensure storage dict
    hass.data[DOMAIN][entry.entry_id] = entry.data                                                # Save entry data

    # Forward to switch platform (creates zone switches + sensors)
    await hass.config_entries.async_forward_entry_setups(entry, ["switch"])                       # HA 2023.5+ API
    return True                                                                                   # Success


# ------------------------------ UNLOAD ENTRY ----------------------------------------------------
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""                                                                  #
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch"])               # Remove entities
    if unload_ok:                                                                                 #
        hass.data[DOMAIN].pop(entry.entry_id)                                                     # Remove from storage
    return unload_ok                                                                              # Return success/failure
