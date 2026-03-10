"""The FordPass integration."""
import asyncio
import logging
from datetime import timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_DISTANCE_UNIT,
    CONF_PRESSURE_UNIT,
    COORDINATOR,
    DEFAULT_DISTANCE_UNIT,
    DEFAULT_PRESSURE_UNIT,
    DEFAULT_REGION,
    DOMAIN,
    MANUFACTURER,
    REGION,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
    UPDATE_INTERVAL_DEFAULT,
    VEHICLE,
    VIN,
)
from .fordpass_new import Vehicle

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

PLATFORMS = ["lock", "sensor", "switch", "device_tracker"]
OPTIONS_LISTENER_KEY = "fordpass_options_listener"

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the FordPass component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up FordPass from a config entry."""
    user = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    vin = entry.data[VIN]

    if UPDATE_INTERVAL in entry.options:
        update_interval = entry.options[UPDATE_INTERVAL]
    else:
        update_interval = UPDATE_INTERVAL_DEFAULT
    _LOGGER.debug("Update interval: %s", update_interval)

    if REGION in entry.data.keys():
        region = entry.data[REGION]
    else:
        _LOGGER.debug("Region not found in config, using default")
        region = DEFAULT_REGION

    # Create token store for this user+region in HA storage
    token_store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}_{user}_{region}")

    coordinator = FordPassDataUpdateCoordinator(
        hass, user, password, vin, region, update_interval, token_store
    )

    await coordinator.async_refresh()  # Get initial data

    fordpass_options_listener = entry.add_update_listener(options_update_listener)

    if not entry.options:
        await async_update_options(hass, entry)

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR: coordinator,
        OPTIONS_LISTENER_KEY: fordpass_options_listener,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def async_refresh_status_service(service_call):
        """Handle refresh status for specific VIN or all vehicles."""
        target_vin = service_call.data.get("vin", "")

        if target_vin:
            _LOGGER.debug("Refreshing status for VIN: %s", target_vin)
            try:
                result = await coordinator.vehicle.request_update(target_vin)
                if result:
                    _LOGGER.debug("Refresh succeeded, updating coordinator data")
                    await asyncio.sleep(2)
                    await coordinator.async_request_refresh()
                else:
                    _LOGGER.warning("Refresh command failed for VIN: %s", target_vin)
            except Exception as err:
                _LOGGER.error("Error during refresh for VIN %s: %s", target_vin, err)
        else:
            # Refresh all vehicles for this account
            all_entries = hass.config_entries.async_entries(DOMAIN)
            current_username = entry.data[CONF_USERNAME]

            for config_entry in all_entries:
                if config_entry.data.get(CONF_USERNAME) == current_username:
                    entry_coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
                    _LOGGER.debug("Refreshing status for VIN: %s", entry_coordinator.vin)
                    try:
                        result = await entry_coordinator.vehicle.request_update()
                        if result:
                            _LOGGER.debug("Refresh succeeded")
                            await asyncio.sleep(2)
                            await entry_coordinator.async_request_refresh()
                        else:
                            _LOGGER.warning("Refresh command failed for VIN: %s", entry_coordinator.vin)
                    except Exception as err:
                        _LOGGER.error("Error during refresh for VIN %s: %s", entry_coordinator.vin, err)

    async def async_clear_tokens_service(service_call):
        """Clear tokens for this user account."""
        await coordinator.vehicle.clear_token()

    async def poll_api_service(service_call):
        """Poll API for this vehicle."""
        await coordinator.async_request_refresh()

    async def handle_reload(service):
        """Handle reload service call."""
        _LOGGER.debug("Reloading Integration")

        current_entries = hass.config_entries.async_entries(DOMAIN)
        reload_tasks = [
            hass.config_entries.async_reload(config_entry.entry_id)
            for config_entry in current_entries
        ]

        await asyncio.gather(*reload_tasks)

    if not hass.services.has_service(DOMAIN, "refresh_status"):
        hass.services.async_register(
            DOMAIN,
            "refresh_status",
            async_refresh_status_service,
        )
        hass.services.async_register(
            DOMAIN,
            "clear_tokens",
            async_clear_tokens_service,
        )
        hass.services.async_register(
            DOMAIN,
            "reload",
            handle_reload,
        )
        hass.services.async_register(
            DOMAIN,
            "poll_api",
            poll_api_service,
        )

    return True


async def async_update_options(hass, config_entry):
    """Update options entries on change."""
    options = {
        CONF_PRESSURE_UNIT: config_entry.data.get(
            CONF_PRESSURE_UNIT, DEFAULT_PRESSURE_UNIT
        )
    }
    options[CONF_DISTANCE_UNIT] = config_entry.data.get(
        CONF_DISTANCE_UNIT, DEFAULT_DISTANCE_UNIT
    )
    hass.config_entries.async_update_entry(config_entry, options=options)


async def options_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Options listener to refresh config entries on option change."""
    _LOGGER.debug("Options changed, reloading")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, {})
        listener = entry_data.get(OPTIONS_LISTENER_KEY)
        if listener is not None:
            listener()
        return True
    return False


class FordPassDataUpdateCoordinator(DataUpdateCoordinator):
    """DataUpdateCoordinator to handle fetching new data about the vehicle."""

    def __init__(self, hass, user, password, vin, region, update_interval, token_store):
        """Initialize the coordinator and set up the Vehicle object."""
        self._hass = hass
        self.vin = vin
        self.vehicle = Vehicle(user, password, vin, region, token_store, hass)
        self._available = True

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_update_data(self):
        """Fetch data from FordPass."""
        try:
            async with asyncio.timeout(30):
                data = await self.vehicle.status()

                # Temporarily removed due to Ford backend API changes
                # data["guardstatus"] = await self.vehicle.guardStatus()
                # data["messages"] = await self.vehicle.messages()

                data["vehicles"] = await self.vehicle.vehicles()
                _LOGGER.debug("Coordinator data: %s", data)

                if not self._available:
                    _LOGGER.info("Restored connection to FordPass for %s", self.vin)
                    self._available = True

                return data
        except Exception as ex:
            self._available = False
            _LOGGER.warning("Error communicating with FordPass for %s: %s", self.vin, ex)
            raise UpdateFailed(
                f"Error communicating with FordPass for {self.vin}"
            ) from ex


class FordPassEntity(CoordinatorEntity):
    """Defines a base FordPass entity."""

    def __init__(
        self, *, device_id: str, name: str, coordinator: FordPassDataUpdateCoordinator
    ):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._name = name

    @property
    def name(self):
        """Return the name of the entity."""
        return self._name

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return f"{self.coordinator.vin}-{self._device_id}"

    @property
    def device_info(self):
        """Return device information about this device."""
        if self._device_id is None:
            return None

        model = "unknown"
        if self.coordinator.data.get("vehicles") is not None:
            for vehicle in self.coordinator.data["vehicles"].get("vehicleProfile", []):
                if vehicle.get("VIN") == self.coordinator.vin:
                    model = f"{vehicle.get('year', '')} {vehicle.get('model', '')}".strip()

        return {
            "identifiers": {(DOMAIN, self.coordinator.vin)},
            "name": f"Ford {model}",
            "model": model,
            "manufacturer": MANUFACTURER,
        }
