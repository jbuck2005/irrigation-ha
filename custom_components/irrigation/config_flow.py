"""Config flow for Irrigation integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_NAME
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_ZONES,
    DEFAULT_DURATION,
    CONF_TOKEN,
)


class IrrigationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Irrigation."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user provides connection details."""
        errors = {}
        if user_input is not None:
            # Save user configuration
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        # Form schema for user input. No defaults are provided here.
        # This makes all fields required for user input on the form.
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, description={"suggested_value": "Irrigation Controller"}): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, description={"suggested_value": DEFAULT_PORT}): int,
                vol.Required("zones", description={"suggested_value": DEFAULT_ZONES}): int,
                vol.Required("default_duration", description={"suggested_value": DEFAULT_DURATION}): int,
                vol.Required(CONF_TOKEN, description={"suggested_value": "changeme-very-secret-token"}): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_import(self, user_input):
        """Import a config entry from configuration.yaml."""
        return await self.async_step_user(user_input)


class IrrigationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Irrigation."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # The options flow still uses defaults, as this is for editing existing settings.
        data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=data.get("host", "127.0.0.1")): str,
                vol.Required(CONF_PORT, default=data.get("port", DEFAULT_PORT)): int,
                vol.Required("zones", default=data.get("zones", DEFAULT_ZONES)): int,
                vol.Required(
                    "default_duration", default=data.get("default_duration", DEFAULT_DURATION)
                ): int,
                vol.Required(CONF_TOKEN, default=data.get("token", "changeme-very-secret-token")): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)