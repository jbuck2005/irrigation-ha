import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN

class IrrigationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        return self.async_create_entry(title='Irrigation Controller', data={})
