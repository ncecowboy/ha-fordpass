"""Vehicle Tracker Sensor."""
import logging

from homeassistant.components.device_tracker import SourceType, TrackerEntity

from . import FordPassEntity
from .const import COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add the Entities from the config."""
    entry = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]

    # Check if the car supports GPS
    metrics = entry.data.get("metrics", {})
    if metrics.get("position") is not None:
        async_add_entities([CarTracker(entry, "gps")], True)
    else:
        _LOGGER.debug("Vehicle does not support GPS")


class CarTracker(FordPassEntity, TrackerEntity):
    """Defines the vehicle GPS tracker entity."""

    def __init__(self, coordinator, sensor):
        """Initialize."""
        super().__init__(
            device_id="fordpass_tracker",
            name="fordpass_tracker",
            coordinator=coordinator,
        )
        self._attr_extra = {}
        self.sensor = sensor
        self.coordinator = coordinator
        self.data = coordinator.data.get("metrics", {})
        # Required for HA 2022.7+
        self.coordinator_context = object()

    @property
    def latitude(self):
        """Return latitude."""
        position = self.coordinator.data.get("metrics", {}).get("position", {})
        return float(position.get("value", {}).get("location", {}).get("lat", 0))

    @property
    def longitude(self):
        """Return longitude."""
        position = self.coordinator.data.get("metrics", {}).get("position", {})
        return float(position.get("value", {}).get("location", {}).get("lon", 0))

    @property
    def source_type(self):
        """Set source type to GPS."""
        return SourceType.GPS

    @property
    def name(self):
        """Return device tracker entity name."""
        return "fordpass_tracker"

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        atts = {}
        position = self.coordinator.data.get("metrics", {}).get("position", {})
        location = position.get("value", {}).get("location", {})
        if "alt" in location:
            atts["Altitude"] = location["alt"]
        position_value = position.get("value", {})
        if "gpsCoordinateMethod" in position_value:
            atts["gpsCoordinateMethod"] = position_value["gpsCoordinateMethod"]
        if "gpsDimension" in position_value:
            atts["gpsDimension"] = position_value["gpsDimension"]
        return atts

    @property
    def icon(self):
        """Return device tracker icon."""
        return "mdi:radar"
