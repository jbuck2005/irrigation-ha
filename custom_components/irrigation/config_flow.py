"""Config flow for Irrigation integration."""
import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_NAME
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from homeassistant.util import dt as dt_util

from .program import (
    DAY_MODES,
    DAYS_INTERVAL,
    DAYS_WEEKDAYS,
    MAX_START_TIMES,
    MAX_ZONE_MINUTES,
    SUBENTRY_PROGRAM,
    WEEKDAYS,
)
from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_ZONES,
    DEFAULT_DURATION,
    CONF_TOKEN,
    CONF_ZONES,
    CONF_DEFAULT_DURATION,
    CONF_ZONE_DURATIONS,
    CONF_CONTROLLER_NUMBER,
    CONF_MASTER_LEAD,
    CONF_MASTER_SWITCH,
    CONF_MASTER_ZONE,
    MAX_MASTER_LEAD,
    MAX_ZONES,
)


# irrigationd refuses commands without its token, so an empty one can never work.
TOKEN_SCHEMA = vol.All(str, vol.Length(min=1))
HOST_SCHEMA = vol.All(str, vol.Length(min=1))
PORT_SCHEMA = vol.All(int, vol.Range(min=1, max=65535))
ZONES_SCHEMA = vol.All(int, vol.Range(min=1, max=MAX_ZONES))
# 0 is irrigationd's stop command and it refuses more than 2 hours
DURATION_SCHEMA = vol.All(int, vol.Range(min=10, max=7200))
# Commands are one line of space-separated fields, so a space, tab or newline
# in the token or host would split the command or start a second one.
UNSAFE_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")


MASTER_ZONE_SCHEMA = vol.All(int, vol.Range(min=0, max=MAX_ZONES))
MASTER_LEAD_SCHEMA = vol.All(int, vol.Range(min=0, max=MAX_MASTER_LEAD))
SWITCH = EntitySelector(EntitySelectorConfig(domain=["switch", "input_boolean"]))


def check_fields(user_input) -> dict:
    """Return form errors for a host or token that would break the command line."""
    errors = {}
    if user_input.get(CONF_MASTER_ZONE, 0) > user_input.get(CONF_ZONES, MAX_ZONES):
        errors[CONF_MASTER_ZONE] = "invalid_master_zone"
    if UNSAFE_CHARS.search(user_input.get(CONF_HOST, "")):
        errors[CONF_HOST] = "invalid_host"
    if UNSAFE_CHARS.search(user_input.get(CONF_TOKEN) or ""):
        errors[CONF_TOKEN] = "invalid_token"
    return errors
# Hidden, so the stored token never reaches the browser
PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class IrrigationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Irrigation."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Show the Configure button."""
        return IrrigationOptionsFlowHandler(config_entry)

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry):
        """Show the Add program button."""
        return {SUBENTRY_PROGRAM: ProgramSubentryFlow}

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user provides connection details."""
        errors = {}
        if user_input is not None:
            errors = check_fields(user_input)
        if user_input is not None and not errors:
            # Initialize zone_durations dictionary with default duration for each zone
            num_zones = int(user_input.get(CONF_ZONES, DEFAULT_ZONES))
            default_duration = int(user_input.get(CONF_DEFAULT_DURATION, DEFAULT_DURATION))
            zone_durations = {str(zone): default_duration for zone in range(1, num_zones + 1)}
            
            # Take the lowest number no other controller is using
            used = {
                entry.data.get(CONF_CONTROLLER_NUMBER, 1)
                for entry in self._async_current_entries()
            }
            controller_number = next(n for n in range(1, len(used) + 2) if n not in used)

            # Save user configuration, including the required token
            entry_data = {
                "name": user_input.get(CONF_NAME, "Irrigation Controller"),
                "host": user_input[CONF_HOST],
                "port": int(user_input[CONF_PORT]),
                CONF_ZONES: num_zones,
                CONF_DEFAULT_DURATION: default_duration,
                CONF_ZONE_DURATIONS: zone_durations,
                "token": user_input[CONF_TOKEN],
                CONF_CONTROLLER_NUMBER: controller_number,
            }
            return self.async_create_entry(title=entry_data["name"], data=entry_data)

        # Form schema for user input
        schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default="Irrigation Controller"): str,
                vol.Required(CONF_HOST): HOST_SCHEMA,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): PORT_SCHEMA,
                vol.Required(CONF_ZONES, default=DEFAULT_ZONES): ZONES_SCHEMA,
                vol.Required(CONF_DEFAULT_DURATION, default=DEFAULT_DURATION): DURATION_SCHEMA,
                vol.Required(CONF_TOKEN): vol.All(PASSWORD, TOKEN_SCHEMA),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class IrrigationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for Irrigation."""

    def __init__(self, config_entry):
        """Initialize options flow with a reference to the config entry."""
        # Newer Home Assistant versions set config_entry themselves and refuse
        # to let a flow assign it, so keep the entry under another name.
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is not None:
            errors = check_fields(user_input)
        if user_input is not None and not errors:
            # Extract zone-specific durations from user_input
            num_zones = user_input.get(CONF_ZONES, self._entry.data.get(CONF_ZONES, DEFAULT_ZONES))
            zone_durations = {}
            
            for zone in range(1, num_zones + 1):
                zone_key = f"zone_{zone}_duration"
                if zone_key in user_input:
                    zone_durations[str(zone)] = user_input.pop(zone_key)
            
            # Add zone_durations to the data
            user_input[CONF_ZONE_DURATIONS] = zone_durations

            # A blank token keeps the stored one
            if not user_input.get(CONF_TOKEN):
                user_input.pop(CONF_TOKEN, None)
            # A cleared switch field is left out of the form's answer
            user_input.setdefault(CONF_MASTER_SWITCH, None)
            
            # Update the config entry with new data
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, **user_input}
            )
            
            # Reload the entry to apply changes
            await self.hass.config_entries.async_reload(self._entry.entry_id)
            
            return self.async_create_entry(title="", data={})

        data = self._entry.data
        
        # Get current zone durations or initialize if missing
        zone_durations = data.get(CONF_ZONE_DURATIONS, {})
        num_zones = data.get(CONF_ZONES, DEFAULT_ZONES)
        
        # Create schema with per-zone duration fields
        schema_dict = {
            vol.Required(CONF_HOST, default=data.get("host", "127.0.0.1")): HOST_SCHEMA,
            vol.Required(CONF_PORT, default=data.get("port", DEFAULT_PORT)): PORT_SCHEMA,
            vol.Required(CONF_ZONES, default=num_zones): ZONES_SCHEMA,
            vol.Required(CONF_DEFAULT_DURATION, default=data.get(CONF_DEFAULT_DURATION, DEFAULT_DURATION)): DURATION_SCHEMA,
            vol.Optional(CONF_TOKEN): PASSWORD,
            vol.Required(CONF_MASTER_ZONE, default=data.get(CONF_MASTER_ZONE, 0)): MASTER_ZONE_SCHEMA,
            vol.Required(CONF_MASTER_LEAD, default=data.get(CONF_MASTER_LEAD, 0)): MASTER_LEAD_SCHEMA,
        }
        master_switch = data.get(CONF_MASTER_SWITCH)
        if master_switch:
            schema_dict[vol.Optional(CONF_MASTER_SWITCH, default=master_switch)] = SWITCH
        else:
            schema_dict[vol.Optional(CONF_MASTER_SWITCH)] = SWITCH
        
        # Add per-zone duration fields
        for zone in range(1, num_zones + 1):
            zone_key = str(zone)
            default_val = zone_durations.get(zone_key, data.get(CONF_DEFAULT_DURATION, DEFAULT_DURATION))
            schema_dict[vol.Optional(f"zone_{zone}_duration", default=default_val)] = DURATION_SCHEMA
        
        schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


def program_schema(defaults: dict, zones: int, master_zone: int, new: bool) -> vol.Schema:
    """Return the form for adding or editing a program."""
    schema = {}
    if new:
        schema[vol.Required("name", default=defaults.get("name", ""))] = str
    times = defaults.get("start_times", [])
    for index in range(MAX_START_TIMES):
        key = f"start_{index + 1}"
        if index < len(times):
            schema[vol.Optional(key, default=times[index])] = TimeSelector()
        else:
            schema[vol.Optional(key)] = TimeSelector()
    schema[vol.Required("days", default=defaults.get("days") or DAY_MODES[0])] = SelectSelector(
        SelectSelectorConfig(options=DAY_MODES, translation_key="days", mode=SelectSelectorMode.LIST)
    )
    schema[vol.Optional("weekdays", default=defaults.get("weekdays", []))] = SelectSelector(
        SelectSelectorConfig(options=WEEKDAYS, translation_key="weekdays", multiple=True)
    )
    schema[vol.Optional("interval", default=defaults.get("interval", 2))] = NumberSelector(
        NumberSelectorConfig(min=2, max=30, step=1, mode=NumberSelectorMode.BOX)
    )
    minutes = defaults.get("zone_minutes", {})
    for zone in range(1, zones + 1):
        if zone == master_zone:
            continue
        schema[vol.Optional(f"zone_{zone}_minutes", default=minutes.get(str(zone), 0))] = (
            NumberSelector(
                NumberSelectorConfig(
                    min=0, max=MAX_ZONE_MINUTES, step=1, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            )
        )
    return vol.Schema(schema)


def program_data(user_input: dict, zones: int) -> tuple[dict, dict]:
    """Turn the form's answers into program data, and return any errors."""
    errors = {}
    times = sorted(
        {user_input[f"start_{i + 1}"][:5] for i in range(MAX_START_TIMES) if user_input.get(f"start_{i + 1}")}
    )
    if not times:
        errors["start_1"] = "no_start_time"
    zone_minutes = {
        str(zone): int(user_input.get(f"zone_{zone}_minutes", 0) or 0) for zone in range(1, zones + 1)
    }
    zone_minutes = {zone: minutes for zone, minutes in zone_minutes.items() if minutes > 0}
    if not zone_minutes:
        errors["base"] = "no_zones"
    days = user_input.get("days", DAY_MODES[0])
    weekdays = [day for day in WEEKDAYS if day in user_input.get("weekdays", [])]
    if days == DAYS_WEEKDAYS and not weekdays:
        errors["weekdays"] = "no_weekdays"
    data = {
        "start_times": times,
        "days": days,
        "weekdays": weekdays,
        "interval": int(user_input.get("interval", 2) or 2),
        "zone_minutes": zone_minutes,
    }
    return data, errors


class ProgramSubentryFlow(config_entries.ConfigSubentryFlow):
    """Add or edit a watering program."""

    def _zones(self) -> tuple[int, int]:
        entry = self._get_entry()
        return entry.data.get(CONF_ZONES, DEFAULT_ZONES), entry.data.get(CONF_MASTER_ZONE, 0)

    async def async_step_user(self, user_input=None):
        """Add a program."""
        zones, master_zone = self._zones()
        errors = {}
        if user_input is not None:
            data, errors = program_data(user_input, zones)
            name = user_input.get("name", "").strip()
            if not name:
                errors["name"] = "no_name"
            if not errors:
                today = dt_util.now().date().isoformat()
                data.update(enabled=True, anchor=today, last_run=None, running_since=None)
                return self.async_create_entry(title=name, data=data)
        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=program_schema(_form_defaults(defaults), zones, master_zone, new=True),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Edit a program. Its name, history and on/off state are kept."""
        subentry = self._get_reconfigure_subentry()
        zones, master_zone = self._zones()
        errors = {}
        if user_input is not None:
            data, errors = program_data(user_input, zones)
            if not errors:
                anchor = subentry.data.get("anchor")
                if data["days"] == DAYS_INTERVAL and (
                    data["interval"] != subentry.data.get("interval")
                    or subentry.data.get("days") != DAYS_INTERVAL
                ):
                    # A new interval counts from today
                    anchor = dt_util.now().date().isoformat()
                return self.async_update_and_abort(
                    self._get_entry(), subentry, data={**subentry.data, **data, "anchor": anchor}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=program_schema(
                _form_defaults(user_input) if user_input else dict(subentry.data),
                zones, master_zone, new=False,
            ),
            errors=errors,
        )


def _form_defaults(user_input: dict) -> dict:
    """Turn submitted answers back into defaults, so a form with errors keeps them."""
    if not user_input:
        return {}
    return {
        "name": user_input.get("name", ""),
        "start_times": [
            user_input[f"start_{i + 1}"] for i in range(MAX_START_TIMES) if user_input.get(f"start_{i + 1}")
        ],
        "days": user_input.get("days"),
        "weekdays": user_input.get("weekdays", []),
        "interval": user_input.get("interval", 2),
        "zone_minutes": {
            key.split("_")[1]: value for key, value in user_input.items()
            if key.startswith("zone_") and key.endswith("_minutes")
        },
    }
