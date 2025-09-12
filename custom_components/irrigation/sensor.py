"""Platform for irrigation sensors."""
import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up irrigation sensors from a config entry."""
    
    switches = hass.data[DOMAIN][entry.entry_id]["switches"]
    
    sensors = []
    for zone, switch in switches.items():
        sensors.append(IrrigationZoneSensor(switch))
        
    async_add_entities(sensors)

class IrrigationZoneSensor(SensorEntity):
    """Representation of an irrigation zone's remaining time."""

    def __init__(self, switch_entity):
        self._switch = switch_entity
        self.zone = switch_entity.zone
        self._attr_name = f"Irrigation Zone {self.zone} Remaining Time"
        self._attr_native_unit_of_measurement = "s"
        self._attr_icon = "mdi:timer-sand"
        self._attr_unique_id = f"irrigation_{switch_entity._entry_id}_zone_{self.zone}_sensor"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._switch.remaining
    
    @property
    def device_info(self):
        """Link the sensor to the same device as the switch."""
        return {
            "identifiers": {(DOMAIN, f"irrigation_zone_{self.zone}")},
            "name": f"Irrigation Zone {self.zone}",
            "manufacturer": "Irrigation-HA",
        }

    @property
    def available(self) -> bool:
        """Return True if the switch is available."""
        return self._switch.available