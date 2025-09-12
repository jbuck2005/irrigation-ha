"""Config flow for Irrigation integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_NAME
from homeassistant.core import callback

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_ZONES,
    DEFAULT_DURATION,
    CONF_TOKEN,
)


class IrrigationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Irrigation. This is the 'Configure' menu."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            # Update the config entry with new data and reload the integration.
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=user_input
            )
            return self.async_create_entry(title="", data={})

        data = self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=data.get(CONF_HOST)): str,
                    vol.Required(CONF_PORT, default=data.get(CONF_PORT)): int,
                    vol.Required("zones", default=data.get("zones")): int,
                    vol.Required("default_duration", default=data.get("default_duration")): int,
                    vol.Required(CONF_TOKEN, default=data.get(CONF_TOKEN)): str,
                }
            ),
        )


class IrrigationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Irrigation. This is the initial setup."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """This function correctly links the initial setup to the 'Configure' menu."""
        return IrrigationOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the user setup step."""
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        # This schema has NO defaults, forcing the user to enter all information.
        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, description={"suggested_value": "Irrigation Controller"}): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, description={"suggested_value": DEFAULT_PORT}): int,
                vol.Required("zones", description={"suggested_value": DEFAULT_ZONES}): int,
                vol.Required("default_duration", description={"suggested_value": DEFAULT_DURATION}): int,
                vol.Required(CONF_TOKEN, description={"suggested_value": "changeme-very-secret-token"}): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema)