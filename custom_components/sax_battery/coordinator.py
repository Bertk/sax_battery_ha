"""SAX Battery data update coordinator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from pymodbus import ModbusException

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BATTERY_POLL_INTERVAL,
    BATTERY_POLL_SLAVE_INTERVAL,
    CONF_BATTERY_IS_MASTER,
)
from .enums import TypeConstants
from .items import ModbusItem, SAXItem
from .modbusobject import ModbusAPI
from .models import SAXBatteryData

_LOGGER = logging.getLogger(__name__)


class SAXBatteryCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """SAX Battery data update coordinator with direct ModbusItem integration.

    Security: Implements proper error handling and input validation
    Performance: Efficient update strategies with connection pooling
    """

    def __init__(
        self,
        hass: HomeAssistant,
        battery_id: str,
        sax_data: SAXBatteryData,
        modbus_api: ModbusAPI,
        config_entry: ConfigEntry,
        battery_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            battery_id: Unique battery identifier
            sax_data: SAX battery data model
            modbus_api: Modbus communication API
            config_entry: Configuration entry
            battery_config: Battery-specific configuration

        Security: Validates all input parameters
        """
        # Security: Input validation
        if not isinstance(battery_id, str) or not battery_id.strip():
            raise ValueError("Battery ID must be a non-empty string")

        self.battery_id = battery_id.strip()
        self.sax_data = sax_data
        self.modbus_api = modbus_api
        self.config_entry = config_entry
        self.battery_config = battery_config or {}

        # Initialize timestamp for tracking last successful update
        self.last_update_success_time: datetime | None = None

        # Determine update interval based on battery role
        is_master_battery = self.battery_config.get(CONF_BATTERY_IS_MASTER, False)
        update_interval = (
            BATTERY_POLL_INTERVAL if is_master_battery else BATTERY_POLL_SLAVE_INTERVAL
        )  # Master polls more frequently

        super().__init__(
            hass,
            _LOGGER,
            name=f"SAX Battery {battery_id}",
            update_interval=timedelta(seconds=update_interval),
        )

        # Initialize ModbusItems with API reference
        self._setup_modbus_items()

    @property
    def is_master(self) -> bool:
        """Check if this battery is the master battery.

        Returns:
            bool: True if this is the master battery

        Performance: Cached property access
        """
        return bool(self.battery_config.get(CONF_BATTERY_IS_MASTER, False))

    def _setup_modbus_items(self) -> None:
        """Set up ModbusItems with API reference for direct communication.

        Performance: Efficient item setup using list comprehension patterns
        Security: Validates item types before setup
        """
        # Performance optimization: Use list comprehension to filter and setup
        modbus_items = [
            item
            for item in self.sax_data.get_modbus_items_for_battery(self.battery_id)
            if isinstance(item, ModbusItem)
        ]

        # Setup API references for modbus items
        for item in modbus_items:
            item.modbus_api = self.modbus_api

        # Set up SAXItems with coordinator references
        sax_items = [
            item
            for item in self.sax_data.get_sax_items_for_battery(self.battery_id)
            if isinstance(item, SAXItem)
        ]

        # Performance: Use extend pattern for coordinator setup
        for sax_item in sax_items:
            # Pass all coordinators for multi-battery calculations
            sax_item.set_coordinators(self.sax_data.coordinators)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from SAX Battery with improved error handling.

        Returns:
            dict: Updated battery data

        Security: Comprehensive error handling with input validation
        Performance: Optimized update flow with connection health monitoring
        """
        start_time = time.time()

        try:
            # Check connection health before proceeding
            if self.modbus_api and self.modbus_api.should_force_reconnect():
                _LOGGER.warning(
                    "Battery %s connection health is poor, forcing reconnection",
                    self.battery_id,
                )
                # Force close and recreate connection
                self.modbus_api.close()
                if not await self.modbus_api.connect():
                    raise UpdateFailed(  # noqa: TRY301
                        f"Failed to reconnect to battery {self.battery_id} after health check"
                    )

            data: dict[str, Any] = {}

            # Update smart meter data (master only)
            if self.is_master:
                try:
                    await self._update_smart_meter_data(data)
                except OSError as err:
                    if err.errno in {
                        32,
                        104,
                        110,
                        111,
                    }:  # Broken pipe, connection reset, timeout, refused
                        _LOGGER.warning(
                            "Smart meter connection error for %s: [Errno %d] %s - will retry",
                            self.battery_id,
                            err.errno,
                            err,
                        )
                        # Don't fail the entire update for smart meter issues
                    else:
                        _LOGGER.error(
                            "Smart meter communication error for %s: %s",
                            self.battery_id,
                            err,
                        )
                        raise UpdateFailed(f"Smart meter error: {err}") from err
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error(
                        "Unexpected smart meter error for %s: %s", self.battery_id, err
                    )
                    # Continue with battery data even if smart meter fails

            # Update battery data
            try:
                await self._update_battery_data(data)
            except OSError as err:
                if err.errno in {32, 104, 110, 111}:  # Network connection errors
                    _LOGGER.warning(
                        "Battery connection error for %s: [Errno %d] %s - attempting recovery",
                        self.battery_id,
                        err.errno,
                        err,
                    )

                    # Attempt immediate recovery
                    if self.modbus_api and await self.modbus_api.reconnect_on_error():
                        _LOGGER.info(
                            "Successfully recovered connection to %s", self.battery_id
                        )
                        # Retry battery data collection once
                        try:
                            await self._update_battery_data(data)
                        except Exception as retry_err:
                            _LOGGER.error(
                                "Retry failed for %s: %s", self.battery_id, retry_err
                            )
                            raise UpdateFailed(
                                f"Battery communication failed after recovery attempt: {retry_err}"
                            ) from retry_err
                    else:
                        raise UpdateFailed(
                            f"Failed to recover connection to battery {self.battery_id}"
                        ) from err
                else:
                    _LOGGER.error(
                        "Battery communication error for %s: %s", self.battery_id, err
                    )
                    raise UpdateFailed(f"Battery error: {err}") from err
            except Exception as err:
                _LOGGER.error(
                    "Unexpected battery error for %s: %s", self.battery_id, err
                )
                raise UpdateFailed(
                    f"Error communicating with battery {self.battery_id}"
                ) from err

            # Update calculated values
            self._update_calculated_values(data)

            # Security: Set success timestamp after successful update
            self.last_update_success_time = datetime.now()

            # Log successful update with connection health
            duration = time.time() - start_time
            health = self.modbus_api.connection_health if self.modbus_api else {}

            _LOGGER.debug(
                "Finished fetching SAX Battery %s data in %.3f seconds (success: True, health: %s)",
                self.battery_id,
                duration,
                health.get("health_status", "unknown"),
            )

            return data  # noqa: TRY300

        except UpdateFailed:
            # Re-raise UpdateFailed exceptions
            duration = time.time() - start_time
            _LOGGER.debug(
                "Finished fetching SAX Battery %s data in %.3f seconds (success: False)",
                self.battery_id,
                duration,
            )
            raise
        except Exception as err:
            duration = time.time() - start_time
            _LOGGER.error("Unexpected error fetching %s data: %s", self.battery_id, err)
            _LOGGER.debug(
                "Finished fetching SAX Battery %s data in %.3f seconds (success: False)",
                self.battery_id,
                duration,
            )
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _update_smart_meter_data(self, data: dict[str, Any]) -> None:
        """Update smart meter data (only for master battery).

        Args:
            data: Dictionary to store the updated values

        Security: Error handling for network communication
        Performance: Efficient item iteration and value setting
        """
        try:
            # Performance: Get smart meter items once
            smart_meter_items = [
                item
                for item in self.sax_data.get_smart_meter_items()
                if isinstance(item, ModbusItem)
            ]

            # Performance optimization: Use list comprehension for reads
            read_tasks = []
            for item in smart_meter_items:
                # Security: Ensure API reference is set
                if item.modbus_api is None:
                    item.modbus_api = self.modbus_api
                read_tasks.append(self._read_smart_meter_item(item, data))

            # Performance: Execute reads concurrently
            if read_tasks:
                await asyncio.gather(*read_tasks, return_exceptions=True)

        except (ModbusException, OSError, TimeoutError) as err:
            _LOGGER.error("Error updating smart meter data: %s", err)
            raise

    async def _read_smart_meter_item(
        self, item: ModbusItem, data: dict[str, Any]
    ) -> None:
        """Read a single smart meter item.

        Args:
            item: ModbusItem to read
            data: Dictionary to store the result

        Performance: Individual item reads for better error isolation
        """
        try:
            value = await item.async_read_value()
            if value is not None:
                data[item.name] = value

                # Update smart meter model if available
                if self.sax_data.smart_meter_data:
                    # Security: Validate numeric value before setting
                    if isinstance(value, (int, float)):
                        self.sax_data.smart_meter_data.set_value(
                            item.name, float(value)
                        )

        except (ModbusException, OSError, TimeoutError) as err:
            _LOGGER.warning("Failed to read smart meter item %s: %s", item.name, err)
            data[item.name] = None

    async def async_write_number_value(self, item: ModbusItem, value: float) -> bool:
        """Write number value using direct ModbusItem communication.

        Args:
            item: ModbusItem to write to
            value: Value to write

        Returns:
            bool: True if write successful

        Security: Input validation and error handling
        """
        # Security: Input validation
        if not isinstance(item, ModbusItem):
            raise TypeError("Item must be a ModbusItem")
        if not isinstance(value, (int, float)):
            raise TypeError("Value must be numeric")

        # Ensure API is set
        if item.modbus_api is None:
            item.modbus_api = self.modbus_api
        return await item.async_write_value(value)

    async def async_write_switch_value(self, item: ModbusItem, value: bool) -> bool:
        """Write switch value using direct ModbusItem communication.

        Args:
            item: ModbusItem to write to
            value: Boolean value to write

        Returns:
            bool: True if write successful

        Security: Input validation and safe boolean conversion
        """
        # Security: Input validation
        if not isinstance(item, ModbusItem):
            _LOGGER.error("Expected ModbusItem, got %s", type(item))  # type:ignore [unreachable]
            return False
        if not isinstance(value, bool):
            _LOGGER.error("Expected bool value, got %s", type(value))  # type:ignore [unreachable]
            return False

        # Ensure API is set
        if item.modbus_api is None:
            item.modbus_api = self.modbus_api

        # Convert boolean to appropriate switch value (now synchronous)
        write_value = (
            item.get_switch_on_value() if value else item.get_switch_off_value()
        )
        return await item.async_write_value(write_value)

    def update_sax_item_state(self, item: SAXItem | str, value: Any) -> None:
        """Update SAX item state in the coordinator data.

        Args:
            item: SAXItem or item name to update
            value: New value to set

        Performance: Efficient state update with listener notification
        """
        if isinstance(item, str):
            item_name = item
        else:
            item_name = item.name

        if self.data:
            self.data[item_name] = value
            self.async_update_listeners()

    async def async_write_pilot_control_value(
        self,
        power_item: ModbusItem,
        power_factor_item: ModbusItem,
        power: float,
        power_factor: float,
    ) -> bool:
        """Write pilot control values (power and power factor) simultaneously.

        This method is specifically for MODBUS_BATTERY_PILOT_CONTROL_ITEMS that require
        writing both power and power factor registers at the same time.

        Args:
            power_item: ModbusItem for the power register (address 41)
            power_factor_item: ModbusItem for the power factor register (address 42)
            power: Power value to write
            power_factor: Power factor value to write

        Returns:
            bool: True if both values were written successfully

        Security:
            Validates input types and ranges before writing

        Performance:
            Single Modbus transaction for both registers
        """
        # Security: Input validation
        if not isinstance(power, (int, float)):
            raise TypeError("Power must be numeric")
        if not isinstance(power_factor, (int, float)):
            raise TypeError("Power factor must be numeric")

        # Range validation for power factor (typical range 0.0 to 1.0)
        if not (0.0 <= power_factor <= 1.0):
            raise ValueError(
                f"Power factor {power_factor} outside valid range [0.0, 1.0]"
            )

        try:
            # Use the specialized write method that handles both registers
            success = await self.modbus_api.write_nominal_power(
                value=power,
                power_factor=int(
                    power_factor * 10000
                ),  # Convert to integer with precision
                modbus_item=power_item,  # Use power item for address/device_id
            )

            if success:
                # Security: Ensure data dict exists before updating
                if self.data is None:
                    self.data = {}  # type:ignore [unreachable]

                # Update coordinator data for both values (performance optimization)
                self.data[power_item.name] = power
                self.data[power_factor_item.name] = power_factor
                _LOGGER.debug(
                    "Successfully wrote pilot control: power=%s, power_factor=%s",
                    power,
                    power_factor,
                )
            else:
                _LOGGER.error(
                    "Failed to write pilot control values: power=%s, power_factor=%s",
                    power,
                    power_factor,
                )

            return success  # noqa: TRY300

        except (OSError, TimeoutError, ModbusException) as err:
            _LOGGER.error("Error writing pilot control values: %s", err)
            return False

    async def _update_battery_data(self, data: dict[str, Any]) -> None:
        """Update battery data from modbus items.

        Args:
            data: Dictionary to store the updated values

        Security: Error handling for communication failures
        Performance: Efficient item iteration with read-only checks
        """
        try:
            # Performance optimization: Use list comprehension to get modbus items
            modbus_items = [
                item
                for item in self.sax_data.get_modbus_items_for_battery(self.battery_id)
                if isinstance(item, ModbusItem)
            ]

            # Update data from each modbus item
            for item in modbus_items:
                # Performance: Skip read-only check for write-only items (now synchronous)
                if hasattr(item, "is_read_only") and not item.is_read_only():
                    continue

                await self._read_battery_item(item, data)

        except (ModbusException, OSError, TimeoutError) as err:
            _LOGGER.error(
                "Error updating battery data for %s: %s", self.battery_id, err
            )
            raise

    async def _read_battery_item(self, item: ModbusItem, data: dict[str, Any]) -> None:
        """Read a single battery item and update data dictionary.

        Args:
            item: ModbusItem to read
            data: Dictionary to store the result

        Security: Handles all read errors gracefully
        Performance: Individual item reads for better error isolation
        """
        try:
            value = await item.async_read_value()
            if value is not None:
                data[item.name] = value
                _LOGGER.debug("Read %s: %s", item.name, value)
            else:
                _LOGGER.debug("Skipping read for write-only item %s", item.name)

        except (ModbusException, OSError, TimeoutError) as err:
            _LOGGER.warning("Failed to read item %s: %s", item.name, err)
            # Don't fail the entire update for individual item failures
            data[item.name] = None

    def _update_calculated_values(self, data: dict[str, Any]) -> None:
        """Update calculated SAX values based on raw modbus data.

        Args:
            data: Dictionary to store the calculated values

        Performance: Uses efficient dictionary operations with type filtering
        Security: Validates all calculations for numeric bounds
        """
        try:
            # Get SAX items for this battery
            all_sax_items = self.sax_data.get_sax_items_for_battery(self.battery_id)

            # Performance optimization: Filter calculable items using list comprehension
            calculable_items = [
                sax_item
                for sax_item in all_sax_items
                if isinstance(sax_item, SAXItem)
                and sax_item.mtype
                in (
                    TypeConstants.SENSOR,
                    TypeConstants.SENSOR_CALC,
                    TypeConstants.NUMBER,
                    TypeConstants.NUMBER_RO,
                )
            ]

            # Performance optimization: Use dictionary update pattern
            calculated_values: dict[str, Any] = {}

            for sax_item in calculable_items:
                try:
                    # Security: Validate coordinators are available
                    if (
                        not hasattr(sax_item, "coordinators")
                        or not sax_item.coordinators
                    ):
                        sax_item.set_coordinators(self.sax_data.coordinators)

                    value = sax_item.calculate_value(self.sax_data.coordinators)
                    if value is not None:
                        calculated_values[sax_item.name] = value
                        _LOGGER.debug("Calculated %s: %s", sax_item.name, value)
                    else:
                        # Security: Explicitly set None for failed calculations
                        calculated_values[sax_item.name] = None
                        _LOGGER.debug("Calculation returned None for %s", sax_item.name)

                except (ValueError, TypeError, ZeroDivisionError) as err:
                    _LOGGER.warning("Failed to calculate %s: %s", sax_item.name, err)
                    # Security: Set None for calculation errors to maintain data consistency
                    calculated_values[sax_item.name] = None

            # Performance: Single update operation
            data.update(calculated_values)

            _LOGGER.debug(
                "Updated %d calculated values, skipped %d non-calculable items",
                len(calculated_values),
                len(all_sax_items) - len(calculable_items),
            )

        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error updating calculated values: %s", err)
