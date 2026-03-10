"""FordPass Switch Entities."""
import logging

from homeassistant.components.switch import SwitchEntity

from . import FordPassEntity
from .const import COORDINATOR, DOMAIN, SWITCHES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Add the Switch from the config."""
    entry = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]

    for key, value in SWITCHES.items():
        sw = Switch(entry, key, config_entry.options)
        # Only add guard entity if supported by the car
        if key == "guardmode":
            guard_status = sw.coordinator.data.get("guardstatus")
            if guard_status and guard_status.get("returnCode") == 200:
                async_add_entities([sw], False)
            else:
                _LOGGER.debug("Guard mode not supported on this vehicle")
        else:
            async_add_entities([sw], False)


class Switch(FordPassEntity, SwitchEntity):
    """Define the Switch for turning ignition off/on."""

    def __init__(self, coordinator, switch, options):
        """Initialize."""
        super().__init__(
            device_id="fordpass_" + switch,
            name="fordpass_" + switch + "_Switch",
            coordinator=coordinator,
        )
        self.switch = switch
        self.coordinator = coordinator
        self.data = coordinator.data.get("metrics", {})
        # Required for HA 2022.7+
        self.coordinator_context = object()

    async def async_turn_on(self, **kwargs):
        """Handle switch on."""
        if self.switch == "ignition":
            await self.coordinator.vehicle.start()
            await self.coordinator.async_request_refresh()
        elif self.switch == "guardmode":
            await self.coordinator.vehicle.enable_guard()
            await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Handle switch off."""
        if self.switch == "ignition":
            await self.coordinator.vehicle.stop()
            await self.coordinator.async_request_refresh()
        elif self.switch == "guardmode":
            await self.coordinator.vehicle.disable_guard()
            await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def name(self):
        """Return switch name."""
        return "fordpass_" + self.switch + "_Switch"

    @property
    def is_on(self):
        """Check status of switch - considers both ignition and remote start status."""
        if self.switch == "ignition":
            if self.coordinator.data.get("metrics") is None:
                return None

            # Check ignition status first
            ignition_status = None
            ignition_data = self.coordinator.data["metrics"].get("ignitionStatus")
            if ignition_data is not None:
                ignition_status = ignition_data["value"]
                _LOGGER.debug("Ignition status: %s", ignition_status)

            # Check remote start status using countdown timer
            remote_start_active = False
            if "remoteStartCountdownTimer" in self.coordinator.data["metrics"]:
                countdown_timer = self.coordinator.data["metrics"][
                    "remoteStartCountdownTimer"
                ].get("value", 0)
                if countdown_timer and countdown_timer > 0:
                    remote_start_active = True
                    _LOGGER.debug("Remote start active, countdown: %s", countdown_timer)

            # Vehicle is "on" if either ignition is on OR remote start is active
            if remote_start_active:
                _LOGGER.debug("Vehicle is ON via remote start")
                return True
            elif ignition_status in ["ON", "RUN", "START", "ACCESSORY"]:
                _LOGGER.debug("Vehicle is ON via ignition")
                return True
            elif ignition_status == "OFF":
                _LOGGER.debug("Vehicle is OFF")
                return False
            elif ignition_status is None:
                _LOGGER.debug(
                    "No ignition status, using remote start: %s", remote_start_active
                )
                return remote_start_active
            else:
                _LOGGER.warning(
                    "Unknown ignition status: %s, using remote start: %s",
                    ignition_status,
                    remote_start_active,
                )
                return remote_start_active

        elif self.switch == "guardmode":
            guardstatus = self.coordinator.data.get("guardstatus", {})
            _LOGGER.debug("Guard status: %s", guardstatus)
            if guardstatus.get("returnCode") == 200:
                session = guardstatus.get("session", {})
                if "gmStatus" in session:
                    if session["gmStatus"] == "enable":
                        return True
                    elif session["gmStatus"] == "disable":
                        return False
                return False
            return False

        return False

    @property
    def icon(self):
        """Return icon for switch."""
        return SWITCHES[self.switch]["icon"]
