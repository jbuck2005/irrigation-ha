"""Platform for irrigation zone duration number entities."""

import logging

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory

from .const import (
    DEFAULT_ZONES,
    DEFAULT_DURATION,
    CONF_ZONES,
    CONF_DEFAULT_DURATION,
    CONF_ZONE_DURATIONS,
    DOMAIN,
    device_info,
    entity_id_prefix,
)

_LOGGER = logging.getLogger(__name__)


class IrrigationZoneDuration(NumberEntity):
    """Representation of an irrigation zone duration configuration."""

    _attr_native_min_value = 10  # Minimum 10 seconds
    _attr_native_max_value = 7200  # Maximum 2 hours (7200 seconds)
    _attr_native_step = 10  # Step by 10 seconds
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:timer-cog-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        zone: int,
        initial_duration: int,
        id_prefix: str,
        device: dict,
    ):
        """Initialize the irrigation zone duration number entity."""
        self.hass = hass
        # Only suggests the ID for new entities, so existing installs keep theirs
        self.entity_id = f"number.{id_prefix}_zone_{zone}_default_duration"
        self._entry_id = entry_id
        self._zone = zone
        self._attr_native_value = initial_duration
        self._attr_name = f"Irrigation Zone {zone} Default Duration"
        self._attr_unique_id = f"{entry_id}_zone_{zone}_duration"
        self._attr_device_info = device

    @property
    def extra_state_attributes(self):
        """Return the zone number, which pairs this entity with its valve."""
        return {"zone": self._zone}

    async def async_set_native_value(self, value: float) -> None:
        """Update the zone's default duration."""
        new_duration = int(value)

        # Get the config entry
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if not entry:
            _LOGGER.error("Config entry not found for zone %s", self._zone)
            return

        # Update the zone_durations dictionary
        zone_durations = dict(entry.data.get(CONF_ZONE_DURATIONS, {}))
        zone_durations[str(self._zone)] = new_duration

        # Update the config entry
        self.hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ZONE_DURATIONS: zone_durations}
        )

        # Update the entity state
        self._attr_native_value = new_duration
        self.async_write_ha_state()

        # Update the corresponding valve entity's default duration
        if DOMAIN in self.hass.data and self._entry_id in self.hass.data[DOMAIN]:
            for entity in self.hass.data[DOMAIN][self._entry_id].get("entities", []):
                if hasattr(entity, "_zone") and entity._zone == self._zone:
                    entity._default_duration = new_duration
                    entity.async_write_ha_state()
                    _LOGGER.info(
                        "Updated zone %s default duration to %s seconds",
                        self._zone,
                        new_duration,
                    )
                    break


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up irrigation zone duration number entities from a config entry."""
    zones = entry.data.get(CONF_ZONES, DEFAULT_ZONES)
    default_duration = entry.data.get(CONF_DEFAULT_DURATION, DEFAULT_DURATION)
    zone_durations = entry.data.get(CONF_ZONE_DURATIONS, {})

    entities = []
    for zone in range(1, zones + 1):
        # Get zone-specific duration or fall back to global default
        zone_duration = zone_durations.get(str(zone), default_duration)
        entities.append(
            IrrigationZoneDuration(
                hass, entry.entry_id, zone, zone_duration, entity_id_prefix(entry), device_info(entry)
            )
        )

    async_add_entities(entities)

    # Keep reference for updates
    hass.data[DOMAIN][entry.entry_id]["number_entities"] = entities
