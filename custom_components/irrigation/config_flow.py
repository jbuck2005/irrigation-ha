import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

from . import DOMAIN

class IrrigationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        schema = vol.Schema({
            vol.Required(CONF_NAME, default="Irrigation Controller"): str,
            vol.Optional("zones", default=14): int,
            vol.Optional("default_duration", default=300): int,
        })
        return self.async_show_form(step_id="user", data_schema=schema)

class IrrigationOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        schema = vol.Schema({
            vol.Required("zones", default=self.config_entry.data.get("zones", 14)): int,
            vol.Required("default_duration", default=self.config_entry.data.get("default_duration", 60)): int,
        })
        return self.async_show_form(step_id="init", data_schema=schema)

@callback
def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    return IrrigationOptionsFlowHandler(config_entry)
