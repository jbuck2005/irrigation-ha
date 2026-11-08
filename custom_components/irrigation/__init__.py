"""
__init__.py
Irrigation integration bootstrap.

- Declares CONFIG_SCHEMA as config_entry_only so hassfest knows this integration
  is configured via the UI only.
- Sets up the integration by storing config entry data in hass.data and
  forwarding platform setup to the `valve` and `number` platforms.
- Serves the sidebar panel and dashboard card from the `frontend` folder.
"""

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import DEFAULT_PORT
from .status import STATUS_INTERVAL, StatusPoller

DOMAIN = "irrigation"

FRONTEND_URL = "/irrigation_frontend"
PANEL_PATH = "irrigation"
PLATFORMS = ["valve", "number"]

# Integration is configured only through Config Entries (UI)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (called when Home Assistant starts)."""
    hass.data.setdefault(DOMAIN, {})
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(Path(__file__).parent / "frontend"), False)]
    )
    # Load the module on every page so the card works on any dashboard
    frontend.add_extra_js_url(hass, await _async_module_url(hass))
    return True


async def _async_module_url(hass: HomeAssistant) -> str:
    """Return the module URL, versioned so an update replaces cached copies."""
    integration = await async_get_integration(hass, DOMAIN)
    return f"{FRONTEND_URL}/irrigation-panel.js?v={integration.version}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the irrigation integration from a config entry (UI)."""

    hass.data.setdefault(DOMAIN, {})
    # Store config and entities in a structured dict
    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
        "entities": [],
        "number_entities": [],
    }

    # Forward setup to the valve and number platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Read the real zone state now, so a run that outlasted a restart shows up
    poller = StatusPoller(
        hass,
        entry.entry_id,
        entry.data.get("host", "127.0.0.1"),
        entry.data.get("port", DEFAULT_PORT),
        entry.data.get("token"),
    )
    hass.data[DOMAIN][entry.entry_id]["status"] = poller
    entry.async_on_unload(async_track_time_interval(hass, poller.async_poll, STATUS_INTERVAL))
    hass.async_create_task(poller.async_poll())

    if PANEL_PATH not in hass.data.get(frontend.DATA_PANELS, {}):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_PATH,
            webcomponent_name="irrigation-panel",
            sidebar_title="Irrigation",
            sidebar_icon="mdi:sprinkler-variant",
            module_url=await _async_module_url(hass),
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and its platforms."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the panel once the last controller is deleted."""
    if not hass.data[DOMAIN]:
        frontend.async_remove_panel(hass, PANEL_PATH)
