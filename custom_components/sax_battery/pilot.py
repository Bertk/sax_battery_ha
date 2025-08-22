"""SAX Battery pilot functionality."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_AUTO_PILOT_INTERVAL,
    CONF_ENABLE_SOLAR_CHARGING,
    CONF_MANUAL_CONTROL,
    CONF_MIN_SOC,
    CONF_PF_SENSOR,
    CONF_PILOT_FROM_HA,
    CONF_POWER_SENSOR,
    CONF_PRIORITY_DEVICES,
    DEFAULT_AUTO_PILOT_INTERVAL,
    DEFAULT_MIN_SOC,
    DOMAIN,
    MANUAL_CONTROL_SWITCH,
    PILOT_ITEMS,
    SAX_COMBINED_SOC,
    SOLAR_CHARGING_SWITCH,
)
from .coordinator import SAXBatteryCoordinator
from .enums import TypeConstants
from .items import SAXItem
from .models import SAXBatteryData
from .utils import determine_entity_category

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SAX Battery pilot entities."""
    integration_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators = integration_data["coordinators"]
    sax_data = integration_data["sax_data"]

    entities: list[SwitchEntity | NumberEntity] = []

    # Create pilot entities only for master battery
    master_battery_id = sax_data.master_battery_id
    if master_battery_id and master_battery_id in coordinators:
        coordinator = sax_data.coordinators[master_battery_id]
        pilot = SAXBatteryPilot(hass, sax_data, coordinator)

        # Store pilot instance in sax_data for access by other components
        # Add pilot attribute to SAXBatteryData model
        setattr(sax_data, "pilot", pilot)

        # Add power control entity if pilot from HA is enabled
        if config_entry.data.get(CONF_PILOT_FROM_HA, False):
            entities.append(
                SAXBatteryPilotPowerEntity(pilot, coordinator, master_battery_id)
            )

        # Create pilot control entities from PILOT_ITEMS using extend
        entities.extend(
            _create_pilot_entity(pilot, coordinator, pilot_item, master_battery_id)
            for pilot_item in PILOT_ITEMS
            if pilot_item.mtype == TypeConstants.SWITCH
        )

        # Start automatic pilot service if enabled
        if config_entry.data.get(CONF_PILOT_FROM_HA, False):
            await pilot.async_start()

    if entities:
        async_add_entities(entities, update_before_add=True)


def _create_pilot_entity(
    pilot: SAXBatteryPilot,
    coordinator: SAXBatteryCoordinator,
    pilot_item: SAXItem,
    battery_id: str,
) -> SwitchEntity:
    """Create appropriate pilot entity based on item name."""
    match pilot_item.name:
        case name if name == SOLAR_CHARGING_SWITCH:
            return SAXBatterySolarChargingSwitch(
                pilot, coordinator, pilot_item, battery_id
            )
        case name if name == MANUAL_CONTROL_SWITCH:
            return SAXBatteryManualControlSwitch(
                pilot, coordinator, pilot_item, battery_id
            )
        case _:
            # Default fallback for unknown switch types
            _LOGGER.warning("Unknown pilot switch type: %s", pilot_item.name)
            return SAXBatteryGenericPilotSwitch(
                pilot, coordinator, pilot_item, battery_id
            )


class SAXBatteryPilot:
    """SAX Battery pilot controller for master battery coordination."""

    def __init__(
        self,
        hass: HomeAssistant,
        sax_data: SAXBatteryData,
        coordinator: SAXBatteryCoordinator,
    ) -> None:
        """Initialize the pilot controller."""
        self.hass = hass
        self.sax_data = sax_data
        self.coordinator = coordinator
        self.entry = sax_data.entry
        self.battery_count = len(sax_data.coordinators)

        # Configuration values
        self._update_config_values()

        # Calculated values
        self.calculated_power = 0.0
        self.max_discharge_power = self.battery_count * 3600
        self.max_charge_power = self.battery_count * 4500

        # Track state
        self._remove_interval_update: Callable[[], None] | None = None
        self._remove_config_update: Callable[[], None] | None = None
        self._running = False

    def _update_config_values(self) -> None:
        """Update configuration values from entry data."""
        self.power_sensor_entity_id = self.entry.data.get(CONF_POWER_SENSOR)
        self.pf_sensor_entity_id = self.entry.data.get(CONF_PF_SENSOR)
        self.priority_devices = self.entry.data.get(CONF_PRIORITY_DEVICES, [])
        self.min_soc = self.entry.data.get(CONF_MIN_SOC, DEFAULT_MIN_SOC)
        self.update_interval = self.entry.data.get(
            CONF_AUTO_PILOT_INTERVAL, DEFAULT_AUTO_PILOT_INTERVAL
        )
        _LOGGER.debug(
            "Updated config values - min_soc: %s%%, update_interval: %ss",
            self.min_soc,
            self.update_interval,
        )

    async def async_start(self) -> None:
        """Start the pilot service."""
        if self._running:
            return

        self._running = True
        self._remove_interval_update = async_track_time_interval(
            self.hass, self._async_update_pilot, timedelta(seconds=self.update_interval)
        )

        # Add listener for config entry updates
        self._remove_config_update = self.entry.add_update_listener(
            self._async_config_updated
        )

        # Do initial calculation
        await self._async_update_pilot(None)

        _LOGGER.info(
            "SAX Battery pilot started with %ss interval", self.update_interval
        )

    async def _async_config_updated(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Handle config entry updates."""
        self.entry = entry
        self._update_config_values()
        # Apply new configuration immediately
        await self._async_update_pilot(None)
        _LOGGER.info("SAX Battery pilot configuration updated")

    async def async_stop(self) -> None:
        """Stop the pilot service."""
        if not self._running:
            return

        if self._remove_interval_update is not None:
            self._remove_interval_update()
            self._remove_interval_update = None

        if self._remove_config_update is not None:
            self._remove_config_update()
            self._remove_config_update = None

        self._running = False
        _LOGGER.info("SAX Battery pilot stopped")

    async def _async_update_pilot(self, now: Any = None) -> None:
        """Update the pilot calculations and send to battery."""
        try:
            # Check if in manual mode
            if self.entry.data.get(CONF_MANUAL_CONTROL, False):
                # Skip automatic calculations in manual mode
                _LOGGER.debug(
                    "Manual control mode active - Current power setting: %sW",
                    self.calculated_power,
                )

                # Check SOC constraints for the current manual power setting
                _LOGGER.debug(
                    "Checking SOC constraints for manual power: %sW",
                    self.calculated_power,
                )
                constrained_power = await self._apply_soc_constraints(
                    self.calculated_power
                )
                if constrained_power != self.calculated_power:
                    _LOGGER.info(
                        "Manual power needs adjustment from %sW to %sW due to SOC constraints",
                        self.calculated_power,
                        constrained_power,
                    )
                    # Update the power setting if constraints changed it
                    await self.send_power_command(constrained_power, 1.0)
                    self.calculated_power = constrained_power
                    _LOGGER.info(
                        "Manual power adjusted to %sW due to SOC constraints",
                        constrained_power,
                    )
                else:
                    _LOGGER.debug(
                        "No SOC constraint adjustments needed for manual power %sW",
                        self.calculated_power,
                    )
                return

            # Get current power sensor state
            if self.power_sensor_entity_id is None:
                _LOGGER.warning("Power sensor entity ID is not configured")
                return

            power_state = self.hass.states.get(self.power_sensor_entity_id)
            if power_state is None:
                _LOGGER.warning(
                    "Power sensor %s not found", self.power_sensor_entity_id
                )
                return

            if power_state.state in (None, "unknown", "unavailable"):
                _LOGGER.warning(
                    "Power sensor %s state is %s",
                    self.power_sensor_entity_id,
                    power_state.state,
                )
                return

            try:
                total_power = float(power_state.state)
            except (ValueError, TypeError) as err:
                _LOGGER.error(
                    "Could not convert power sensor state '%s' to float: %s",
                    power_state.state,
                    err,
                )
                return

            # Get current PF value
            if self.pf_sensor_entity_id is None:
                _LOGGER.warning("PF sensor entity ID is not configured")
                return

            pf_state = self.hass.states.get(self.pf_sensor_entity_id)
            if pf_state is None:
                _LOGGER.warning("PF sensor %s not found", self.pf_sensor_entity_id)
                return

            if pf_state.state in (None, "unknown", "unavailable"):
                _LOGGER.warning(
                    "PF sensor %s state is %s", self.pf_sensor_entity_id, pf_state.state
                )
                return

            try:
                power_factor = float(pf_state.state)
            except (ValueError, TypeError) as err:
                _LOGGER.error(
                    "Could not convert PF sensor state '%s' to float: %s",
                    pf_state.state,
                    err,
                )
                return

            # Get priority device power consumption
            priority_power = 0.0
            for device_id in self.priority_devices:
                device_state = self.hass.states.get(device_id)
                if device_state is not None:
                    try:
                        priority_power += float(device_state.state)
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            "Could not convert state of %s to number", device_id
                        )

            # Get current battery power
            battery_power_state = self.hass.states.get(
                "sensor.sax_battery_combined_power"
            )
            battery_power = 0.0
            if battery_power_state is not None:
                try:
                    if battery_power_state.state not in (
                        None,
                        "unknown",
                        "unavailable",
                    ):
                        battery_power = float(battery_power_state.state)
                    else:
                        _LOGGER.debug(
                            "Battery power state is %s", battery_power_state.state
                        )
                except (ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "Could not convert battery power '%s' to number: %s",
                        battery_power_state.state,
                        err,
                    )

            # Get current SOC for logging
            master_soc = await self._get_combined_soc()
            _LOGGER.debug("Current master SOC: %s%%", master_soc)

            # Calculate target power
            _LOGGER.debug(
                "Starting calculation with total_power=%s, priority_power=%s, battery_power=%s",
                total_power,
                priority_power,
                battery_power,
            )

            if priority_power > 50:
                _LOGGER.debug(
                    "Condition met: priority_power > 50 (%s > 50)", priority_power
                )
                net_power = 0.0
                _LOGGER.debug("Set net_power = 0")
            else:
                _LOGGER.debug(
                    "Condition met: priority_power <= 50 (%s <= 50)", priority_power
                )
                net_power = total_power - battery_power
                _LOGGER.debug(
                    "Calculated net_power = %s - %s = %s",
                    total_power,
                    battery_power,
                    net_power,
                )

            _LOGGER.debug("Final net_power value: %s", net_power)

            target_power = -net_power
            _LOGGER.debug("Final target_power value: %s", target_power)

            # Apply limits
            target_power = max(
                -self.max_discharge_power, min(self.max_charge_power, target_power)
            )

            # Apply SOC constraints
            _LOGGER.debug("Pre-constraint target power: %sW", target_power)
            target_power = await self._apply_soc_constraints(target_power)
            _LOGGER.debug("Post-constraint target power: %sW", target_power)

            # Update calculated power
            self.calculated_power = target_power

            # Send to battery if solar charging is enabled
            if self.get_solar_charging_enabled():
                await self.send_power_command(target_power, power_factor)
            else:
                await self.send_power_command(0, power_factor)

            _LOGGER.debug(
                "Updated battery pilot: target power = %sW, PF = %s",
                target_power,
                power_factor,
            )

        except (OSError, ValueError, TypeError) as err:
            _LOGGER.error("Error in battery pilot update: %s", err)

    async def _get_combined_soc(self) -> float:
        """Get combined SOC from coordinator data."""
        if not self.coordinator.data:
            return 0.0

        soc_value = self.coordinator.data.get(SAX_COMBINED_SOC, 0)
        try:
            return float(soc_value)
        except (ValueError, TypeError):
            return 0.0

    async def _apply_soc_constraints(self, power_value: float) -> float:
        """Apply SOC constraints to a power value."""
        # Get current battery SOC
        master_soc = await self._get_combined_soc()

        # Log the input values
        _LOGGER.debug(
            "Applying SOC constraints - Current SOC: %s%%, Min SOC: %s%%, Power: %sW",
            master_soc,
            self.min_soc,
            power_value,
        )

        # Apply constraints
        original_value = power_value

        # Don't discharge below min SOC
        if master_soc < self.min_soc and power_value > 0:
            power_value = 0
            _LOGGER.debug(
                "Battery SOC at minimum (%s%%), preventing discharge", master_soc
            )

        # Don't charge above 100%
        if master_soc >= 100 and power_value < 0:
            power_value = 0
            _LOGGER.debug("Battery SOC at maximum (100%), preventing charge")

        # Log if any change was made
        if original_value != power_value:
            _LOGGER.info(
                "SOC constraint applied: changed power from %sW to %sW",
                original_value,
                power_value,
            )
        else:
            _LOGGER.debug(
                "SOC constraint check: no change needed to power value %sW", power_value
            )

        return power_value

    async def send_power_command(self, power: float, power_factor: float) -> None:
        """Send power command to battery via Modbus."""
        try:
            # Use coordinator's write methods for power control
            power_item = self._get_modbus_item("sax_power_setpoint")
            pf_item = self._get_modbus_item("sax_power_factor_setpoint")

            if power_item is None or pf_item is None:
                _LOGGER.error("Power control modbus items not found")
                return

            # Convert power to integer for Modbus
            power_int = int(power) & 0xFFFF
            # Convert PF to integer (scale by 10 to preserve precision)
            pf_int = int(power_factor * 10) & 0xFFFF

            _LOGGER.debug(
                "Sending power command: Power=%s, PF=%s to slave %s",
                power_int,
                pf_int,
                power_item.battery_slave_id,
            )

            # Write power and power factor using coordinator methods
            power_success = await self.coordinator.async_write_int_value(
                power_item, power_int
            )
            pf_success = await self.coordinator.async_write_int_value(pf_item, pf_int)

            if power_success and pf_success:
                _LOGGER.debug("Successfully sent power command")
            else:
                _LOGGER.error("Failed to send power command")

        except (OSError, ValueError, TypeError) as err:
            _LOGGER.error("Failed to send power command: %s", err)

    async def set_manual_power(self, power_value: float) -> None:
        """Set a manual power value."""
        # Apply SOC constraints
        power_value = await self._apply_soc_constraints(power_value)

        # Send the power command with a default power factor of 1.0
        await self.send_power_command(power_value, 1.0)
        self.calculated_power = power_value
        _LOGGER.info("Manual power set to %sW", power_value)

    async def set_charge_power_limit(self, power_limit: int) -> bool:
        """Set maximum charge power limit across all batteries."""
        try:
            # This would need a corresponding SAXItem for charge power limit
            # For now, use the existing modbus item lookup
            charge_limit_item = self._get_modbus_item("sax_max_charge_power")
            if not charge_limit_item:
                _LOGGER.error("Charge power limit modbus item not found")
                return False

            success = await self.coordinator.async_write_int_value(
                charge_limit_item, power_limit
            )

            if success:
                _LOGGER.debug("Charge power limit set to %s W", power_limit)
                return True

            _LOGGER.error("Failed to set charge power limit to %s W", power_limit)
            return False  # noqa: TRY300

        except (OSError, ValueError, TypeError, AttributeError) as err:
            _LOGGER.error("Error setting charge power limit: %s", err)
            return False

    async def set_discharge_power_limit(self, power_limit: int) -> bool:
        """Set maximum discharge power limit across all batteries."""
        try:
            # This would need a corresponding SAXItem for discharge power limit
            discharge_limit_item = self._get_modbus_item("sax_max_discharge_power")
            if not discharge_limit_item:
                _LOGGER.error("Discharge power limit modbus item not found")
                return False

            success = await self.coordinator.async_write_int_value(
                discharge_limit_item, power_limit
            )

            if success:
                _LOGGER.debug("Discharge power limit set to %s W", power_limit)
                return True

            _LOGGER.error("Failed to set discharge power limit to %s W", power_limit)
            return False  # noqa: TRY300

        except (OSError, ValueError, TypeError, AttributeError) as err:
            _LOGGER.error("Error setting discharge power limit: %s", err)
            return False

    def _get_pilot_item(self, item_name: str) -> SAXItem | None:
        """Get pilot item by name from PILOT_ITEMS."""
        for item in PILOT_ITEMS:
            if item.name == item_name:
                return item
        return None

    def _get_modbus_item(self, item_name: str) -> Any | None:
        """Get modbus item by name for backwards compatibility."""
        # Get modbus items for master battery
        api_items = self.sax_data.get_modbus_items_for_battery(
            self.coordinator.battery_id
        )

        for item in api_items:
            if hasattr(item, "name") and item.name == item_name:
                return item

        return None

    def get_solar_charging_enabled(self) -> bool:
        """Get solar charging state."""
        return self.entry.data.get(CONF_ENABLE_SOLAR_CHARGING, True)

    @property
    def manual_control_enabled(self) -> bool | None:
        """Return current manual control state."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        return self.coordinator.data.get(MANUAL_CONTROL_SWITCH) == 1

    @property
    def current_charge_power_limit(self) -> int | None:
        """Return current charge power limit."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        return self.coordinator.data.get("sax_max_charge_power")

    @property
    def current_discharge_power_limit(self) -> int | None:
        """Return current discharge power limit."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        return self.coordinator.data.get("sax_max_discharge_power")


class SAXBatteryPilotPowerEntity(
    CoordinatorEntity[SAXBatteryCoordinator], NumberEntity
):
    """Entity showing current calculated pilot power."""

    def __init__(
        self,
        pilot: SAXBatteryPilot,
        coordinator: SAXBatteryCoordinator,
        battery_id: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._pilot = pilot
        self._battery_id = battery_id

        # Generate unique ID
        self._attr_unique_id = f"sax_{battery_id}_pilot_power"
        self._attr_name = (
            f"Sax {battery_id.replace('battery_', 'Battery ').title()} Pilot Power"
        )

        # Set number entity properties
        self._attr_native_min_value = -self._pilot.max_discharge_power
        self._attr_native_max_value = self._pilot.max_charge_power
        self._attr_native_step = 100
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_mode = NumberMode.BOX
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def device_info(self) -> Any:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    @property
    def native_value(self) -> float | None:
        """Return the current calculated power."""
        return (
            float(self._pilot.calculated_power)
            if self._pilot.calculated_power is not None
            else None
        )

    @property
    def icon(self) -> str | None:
        """Return the icon to use for the entity."""
        if self._pilot.calculated_power > 0:
            return "mdi:battery-charging"
        if self._pilot.calculated_power < 0:
            return "mdi:battery-minus"
        return "mdi:battery"

    async def async_set_native_value(self, value: float) -> None:
        """Handle manual override of calculated power."""
        await self._pilot.set_manual_power(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.last_update_success:
            return None

        return {
            "battery_id": self._battery_id,
            "solar_charging_enabled": self._pilot.get_solar_charging_enabled(),
            "manual_control_enabled": self._pilot.manual_control_enabled,
            "max_charge_power": self._pilot.max_charge_power,
            "max_discharge_power": self._pilot.max_discharge_power,
            "last_updated": self.coordinator.last_update_success_time,
        }


class SAXBatterySolarChargingSwitch(
    CoordinatorEntity[SAXBatteryCoordinator], SwitchEntity
):
    """Switch to control solar charging mode."""

    def __init__(
        self,
        pilot: SAXBatteryPilot,
        coordinator: SAXBatteryCoordinator,
        pilot_item: SAXItem,
        battery_id: str,
    ) -> None:
        """Initialize the solar charging switch."""
        super().__init__(coordinator)
        self._pilot = pilot
        self._pilot_item = pilot_item
        self._battery_id = battery_id

        # Generate unique ID using class name pattern
        item_name = self._pilot_item.name.removeprefix("sax_").replace("_switch", "")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from pilot item if available
        if self._pilot_item.entitydescription is not None:
            self.entity_description = self._pilot_item.entitydescription  # type: ignore[assignment]

        # Set name from entity description or fallback
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            base_name = self.entity_description.name
            # Remove "Sax " prefix if it exists
            base_name = base_name.removeprefix("Sax ")
        else:
            # Fallback name generation
            base_name = self._pilot_item.name.replace("_", " ").title()

        # Format battery display name
        battery_display = self._battery_id.replace("battery_", "Battery ").title()
        self._attr_name = f"Sax {battery_display} {base_name}"

        # Set icon and category
        self._attr_icon = "mdi:solar-power"
        self._attr_entity_category = determine_entity_category(pilot_item)

        # Override with entity description properties if available
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "icon")
            and self.entity_description.icon
        ):
            self._attr_icon = self.entity_description.icon

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            self._attr_entity_category = self.entity_description.entity_category

    @property
    def device_info(self) -> Any:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    @property
    def is_on(self) -> bool | None:
        """Return true if solar charging is enabled."""
        return self._pilot.get_solar_charging_enabled()

    @property
    def icon(self) -> str | None:
        """Return the icon to use for the switch."""
        return "mdi:solar-power" if self.is_on else "mdi:solar-power-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.last_update_success:
            return None

        return {
            "battery_id": self._battery_id,
            "manual_control_enabled": self._pilot.manual_control_enabled,
            "calculated_power": self._pilot.calculated_power,
            "last_updated": self.coordinator.last_update_success_time,
        }


class SAXBatteryManualControlSwitch(
    CoordinatorEntity[SAXBatteryCoordinator], SwitchEntity
):
    """Switch to enable/disable manual control functionality."""

    def __init__(
        self,
        pilot: SAXBatteryPilot,
        coordinator: SAXBatteryCoordinator,
        pilot_item: SAXItem,
        battery_id: str,
    ) -> None:
        """Initialize the manual control switch."""
        super().__init__(coordinator)
        self._pilot = pilot
        self._pilot_item = pilot_item
        self._battery_id = battery_id

        # Generate unique ID using class name pattern
        item_name = self._pilot_item.name.removeprefix("sax_").replace("_switch", "")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from pilot item if available
        if self._pilot_item.entitydescription is not None:
            self.entity_description = self._pilot_item.entitydescription  # type: ignore[assignment]

        # Set name from entity description or fallback
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            base_name = self.entity_description.name
            # Remove "Sax " prefix if it exists
            base_name = base_name.removeprefix("Sax ")
        else:
            # Fallback name generation
            base_name = self._pilot_item.name.replace("_", " ").title()

        # Format battery display name
        battery_display = self._battery_id.replace("battery_", "Battery ").title()
        self._attr_name = f"Sax {battery_display} {base_name}"

        # Set default icon and category
        self._attr_icon = "mdi:cog"
        self._attr_entity_category = EntityCategory.CONFIG

        # Override with entity description properties if available
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "icon")
            and self.entity_description.icon
        ):
            self._attr_icon = self.entity_description.icon

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            self._attr_entity_category = self.entity_description.entity_category

    @property
    def device_info(self) -> Any:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    @property
    def is_on(self) -> bool | None:
        """Return true if manual control is enabled."""
        return self._pilot.manual_control_enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.last_update_success:
            return None

        return {
            "battery_id": self._battery_id,
            "charge_power_limit": self._pilot.current_charge_power_limit,
            "discharge_power_limit": self._pilot.current_discharge_power_limit,
            "solar_charging_enabled": self._pilot.get_solar_charging_enabled(),
            "calculated_power": self._pilot.calculated_power,
            "last_updated": self.coordinator.last_update_success_time,
        }


class SAXBatteryGenericPilotSwitch(
    CoordinatorEntity[SAXBatteryCoordinator], SwitchEntity
):
    """Generic pilot switch for unknown switch types."""

    def __init__(
        self,
        pilot: SAXBatteryPilot,
        coordinator: SAXBatteryCoordinator,
        pilot_item: SAXItem,
        battery_id: str,
    ) -> None:
        """Initialize the generic pilot switch."""
        super().__init__(coordinator)
        self._pilot = pilot
        self._pilot_item = pilot_item
        self._battery_id = battery_id

        # Generate unique ID using class name pattern
        item_name = self._pilot_item.name.removeprefix("sax_")
        self._attr_unique_id = f"sax_{self._battery_id}_{item_name}"

        # Set entity description from pilot item if available
        if self._pilot_item.entitydescription is not None:
            self.entity_description = self._pilot_item.entitydescription  # type: ignore[assignment]

        # Set name from entity description or fallback
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "name")
            and isinstance(self.entity_description.name, str)
        ):
            base_name = self.entity_description.name
            # Remove "Sax " prefix if it exists
            base_name = base_name.removeprefix("Sax ")
        else:
            # Fallback name generation
            base_name = self._pilot_item.name.replace("_", " ").title()

        # Format battery display name
        battery_display = self._battery_id.replace("battery_", "Battery ").title()
        self._attr_name = f"Sax {battery_display} {base_name}"

        # Set default properties
        self._attr_icon = "mdi:toggle-switch"
        self._attr_entity_category = EntityCategory.CONFIG

        # Override with entity description properties if available
        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "icon")
            and self.entity_description.icon
        ):
            self._attr_icon = self.entity_description.icon

        if (
            hasattr(self, "entity_description")
            and self.entity_description
            and hasattr(self.entity_description, "entity_category")
        ):
            self._attr_entity_category = self.entity_description.entity_category

    @property
    def device_info(self) -> Any:
        """Return device info."""
        return self.coordinator.sax_data.get_device_info(self._battery_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the generic switch."""
        # Generic implementation - update coordinator data directly
        self.coordinator.data[self._pilot_item.name] = 1
        self.coordinator.async_set_updated_data(self.coordinator.data)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the generic switch."""
        # Generic implementation - update coordinator data directly
        self.coordinator.data[self._pilot_item.name] = 0
        self.coordinator.async_set_updated_data(self.coordinator.data)

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is enabled."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return None

        value = self.coordinator.data.get(self._pilot_item.name)
        if value is None:
            return None

        # Handle different value types
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        if isinstance(value, str):
            return value.lower() in ("1", "true", "on", "yes")

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        if not self.coordinator.last_update_success:
            return None

        return {
            "battery_id": self._battery_id,
            "pilot_item_name": self._pilot_item.name,
            "last_updated": self.coordinator.last_update_success_time,
        }
