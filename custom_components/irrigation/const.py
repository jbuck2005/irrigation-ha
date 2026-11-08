"""Constants for the Irrigation integration."""

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_NAME, CONF_TOKEN

DOMAIN = "irrigation"

# Configuration keys
CONF_TOKEN = "token"
CONF_ZONES = "zones"
CONF_DEFAULT_DURATION = "default_duration"
CONF_ZONE_DURATIONS = "zone_durations"
CONF_CONTROLLER_NUMBER = "controller_number"
CONF_MASTER_ZONE = "master_zone"
CONF_MASTER_SWITCH = "master_switch"
CONF_MASTER_LEAD = "master_lead"
# Set once irrigationd has answered over TLS: never send the token in plain text again
CONF_TLS = "tls"

# Defaults
DEFAULT_PORT = 4242
DEFAULT_ZONES = 4
DEFAULT_DURATION = 300
MAX_MASTER_LEAD = 10

# irrigationd drives at most this many zones
MAX_ZONES = 14


def device_info(entry) -> dict:
    """Return the device for a controller, named as it was at setup."""
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.title,
        "manufacturer": "Custom",
        "model": "Irrigation Zone Controller",
    }


def entity_id_prefix(entry) -> str:
    """Return the entity ID prefix: irrigation, then irrigation_2 and so on."""
    number = entry.data.get(CONF_CONTROLLER_NUMBER, 1)
    return "irrigation" if number == 1 else f"irrigation_{number}"


def program_device_info(entry, subentry) -> dict:
    """Return the device for one program, listed under its controller."""
    return {
        "identifiers": {(DOMAIN, f"{entry.entry_id}_{subentry.subentry_id}")},
        "name": subentry.title,
        "manufacturer": "Custom",
        "model": "Irrigation Program",
        "via_device": (DOMAIN, entry.entry_id),
    }


def program_entity_id(entry, subentry, domain: str, suffix: str) -> str:
    """Suggest an entity ID such as switch.irrigation_program_morning_lawns."""
    from homeassistant.util import slugify

    name = slugify(subentry.title) or subentry.subentry_id.lower()
    return f"{domain}.{entity_id_prefix(entry)}_program_{name}{suffix}"
