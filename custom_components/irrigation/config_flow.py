"""
config_flow.py                                                                                   
Config flow for the Irrigation Controller integration.                                           
                                                                                                 
Provides a UI form when the user adds the integration which requests:                             
  - Name               (optional)                                                                
  - Host (IP)          (required)                                                                
  - Port               (required; default 4242)                                                  
  - Zones              (optional; default 14)                                                     
  - Default duration   (optional; default 300 seconds)                                            
                                                                                                 
Also implements an OptionsFlow so the user can later change host/port/zones/duration without      
removing and re-adding the integration.                                                            
"""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_HOST, CONF_PORT
from homeassistant.core import callback

from .const import DOMAIN

DEFAULT_PORT = 4242
DEFAULT_ZONES = 14
DEFAULT_DURATION = 300

class IrrigationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Irrigation integration."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step when the user adds the integration."""
        if user_input is not None:
            # Create the config entry with the provided data.
            # We store: name, host, port, zones, default_duration
            entry_data = {
                "name": user_input.get(CONF_NAME, "Irrigation Controller"),
                "host": user_input[CONF_HOST],
                "port": int(user_input[CONF_PORT]),
                "zones": int(user_input.get("zones", DEFAULT_ZONES)),
                "default_duration": int(user_input.get("default_duration", DEFAULT_DURATION)),
            }
            return self.async_create_entry(title=entry_data["name"], data=entry_data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default="Irrigation Controller"): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional("zones", default=DEFAULT_ZONES): int,
                vol.Optional("default_duration", default=DEFAULT_DURATION): int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)


class IrrigationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for an existing config entry (edit host/port/zones/duration)."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=data.get("host", "127.0.0.1")): str,
                vol.Required(CONF_PORT, default=data.get("port", DEFAULT_PORT)): int,
                vol.Required("zones", default=data.get("zones", DEFAULT_ZONES)): int,
                vol.Required("default_duration", default=data.get("default_duration", DEFAULT_DURATION)): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


@callback
def async_get_options_flow(entry):
    """Return the options flow handler for this config entry."""
    return IrrigationOptionsFlowHandler(entry)
