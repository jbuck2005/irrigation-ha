"""
__init__.py
Irrigation integration bootstrap.

- Declares CONFIG_SCHEMA as config_entry_only so hassfest knows this integration
  is configured via the UI only.
- Sets up the integration by storing config entry data in hass.data and
  forwarding platform setup to the `valve`, `number`, `sensor` and `button` platforms.
- Gives each controller a run queue, so zones run one at a time, and
  registers `irrigation.stop_all`.
- Serves the sidebar panel and dashboard card from the `frontend` folder.
"""

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import CONF_MASTER_LEAD, CONF_MASTER_SWITCH, CONF_MASTER_ZONE
from .runqueue import RunQueue
from .status import STATUS_INTERVAL, IrrigationdClient, StatusPoller

DOMAIN = "irrigation"

FRONTEND_URL = "/irrigation_frontend"
PANEL_PATH = "irrigation"
PLATFORMS = ["valve", "number", "sensor", "button"]

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

    async def stop_all(call: ServiceCall) -> None:
        """Clear every controller's queue and close all its zones."""
        for data in list(hass.data[DOMAIN].values()):
            await data["queue"].async_stop_all()

    hass.services.async_register(DOMAIN, "stop_all", stop_all)
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
        "client": IrrigationdClient(hass, entry),
        "entities": [],
        "number_entities": [],
    }
    queue = RunQueue(
        hass,
        entry.entry_id,
        master_zone=entry.data.get(CONF_MASTER_ZONE, 0),
        master_switch=entry.data.get(CONF_MASTER_SWITCH),
        master_lead=entry.data.get(CONF_MASTER_LEAD, 0),
    )
    hass.data[DOMAIN][entry.entry_id]["queue"] = queue

    @callback
    def _queue_changed() -> None:
        # Valves show whether they're queued, so refresh them with the queue
        for entity in hass.data[DOMAIN].get(entry.entry_id, {}).get("entities", []):
            if entity.hass is not None and entity.entity_id:
                entity.async_write_ha_state()

    entry.async_on_unload(queue.add_listener(_queue_changed))

    # Forward setup to the valve and number platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Read the real zone state now, so a run that outlasted a restart shows up
    poller = StatusPoller(hass, entry.entry_id, hass.data[DOMAIN][entry.entry_id]["client"])
    hass.data[DOMAIN][entry.entry_id]["status"] = poller
    entry.async_on_unload(async_track_time_interval(hass, poller.async_poll, STATUS_INTERVAL))
    hass.async_create_task(poller.async_poll())
    # A pump left on by a crash or a failed turn-off would run against closed
    # valves, so the master switch starts off, once the switch has loaded
    failsafe = []

    @callback
    def _master_failsafe(_hass: HomeAssistant) -> None:
        failsafe.append(queue.async_master_failsafe())

    @callback
    def _stop_failsafe() -> None:
        for stop in failsafe:
            stop()

    entry.async_on_unload(async_at_started(hass, _master_failsafe))
    entry.async_on_unload(_stop_failsafe)

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
    # Closed is the safe state, so unloading or reloading stops every zone
    await hass.data[DOMAIN][entry.entry_id]["queue"].async_shutdown()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the panel once the last controller is deleted."""
    if not hass.data[DOMAIN]:
        frontend.async_remove_panel(hass, PANEL_PATH)
