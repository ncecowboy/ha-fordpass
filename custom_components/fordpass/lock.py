"""Represents the primary lock of the vehicle."""
import logging

from homeassistant.components.lock import LockEntity

from . import FordPassEntity
from .const import COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add the lock from the config."""
    entry = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]

    lock = Lock(entry)
    door_lock_status = entry.data.get("metrics", {}).get("doorLockStatus")
    if door_lock_status and door_lock_status[0].get("value") != "ERROR":
        async_add_entities([lock], False)
    else:
        _LOGGER.debug("Ford model doesn't support remote locking")


class Lock(FordPassEntity, LockEntity):
    """Defines the vehicle's lock."""

    def __init__(self, coordinator):
        """Initialize."""
        super().__init__(
            device_id="fordpass_doorlock",
            name="fordpass_doorlock",
            coordinator=coordinator,
        )
        self.coordinator = coordinator
        self.data = coordinator.data.get("metrics", {})
        # Required for HA 2022.7+
        self.coordinator_context = object()

    async def async_lock(self, **kwargs):
        """Lock the vehicle."""
        self._attr_is_locking = True
        self.async_write_ha_state()
        _LOGGER.debug("Locking %s", self.coordinator.vin)
        status = await self.coordinator.vehicle.lock()
        _LOGGER.debug("Lock result: %s", status)
        await self.coordinator.async_request_refresh()
        self._attr_is_locking = False
        self.async_write_ha_state()

    async def async_unlock(self, **kwargs):
        """Unlock the vehicle."""
        _LOGGER.debug("Unlocking %s", self.coordinator.vin)
        self._attr_is_unlocking = True
        self.async_write_ha_state()
        status = await self.coordinator.vehicle.unlock()
        _LOGGER.debug("Unlock result: %s", status)
        await self.coordinator.async_request_refresh()
        self._attr_is_unlocking = False
        self.async_write_ha_state()

    @property
    def is_locked(self):
        """Determine if the lock is locked."""
        metrics = self.coordinator.data.get("metrics")
        if metrics is None:
            return None
        door_lock_status = metrics.get("doorLockStatus")
        if door_lock_status is None:
            return None
        return door_lock_status[0]["value"] == "LOCKED"

    @property
    def icon(self):
        """Return MDI icon."""
        return "mdi:car-door-lock"

    @property
    def name(self):
        """Return name."""
        return "fordpass_doorlock"
