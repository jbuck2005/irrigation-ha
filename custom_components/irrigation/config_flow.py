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
            # Save user configuration including optional token
            entry_data = {
                "name": user_input.get(CONF_NAME, "Irrigation Controller"),
                "host": user_input[CONF_HOST],
                "port": int(user_input[CONF_PORT]),
                "zones": int(user_input.get("zones", DEFAULT_ZONES)),
                "default_duration": int(user_input.get("default_duration", DEFAULT_DURATION)),
                "token": user_input.get(CONF_TOKEN, "changeme-very-secret-token"),
            }
            return self.async_create_entry(title=entry_data["name"], data=entry_data)

        # Form schema for user input
        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default="Irrigation Controller"): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required("zones", default=DEFAULT_ZONES): int,
                vol.Required("default_duration", default=DEFAULT_DURATION): int,
                vol.Optional(CONF_TOKEN, default="changeme-very-secret-token"): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_import(self, user_input):
        """Import a config entry from configuration.yaml."""
        return await self.async_step_user(user_input)


class IrrigationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Irrigation."""

    def __init__(self, config_entry):
        """Initialize options flow with a reference to the config entry."""
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
                vol.Required(
                    "default_duration", default=data.get("default_duration", DEFAULT_DURATION)
                ): int,
                vol.Optional(CONF_TOKEN, default=data.get("token", "changeme-very-secret-token")): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)