"""SAX Battery data update coordinator."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from pymodbus import ModbusException

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BATTERY_POLL_INTERVAL, DOMAIN
from .items import ModbusItem, SAXItem
from .modbusobject import ModbusAPI
from .models import SAXBatteryData

_LOGGER = logging.getLogger(__name__)


class SAXBatteryCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """SAX Battery data update coordinator with direct ModbusItem integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        battery_id: str,
        sax_data: SAXBatteryData,
        modbus_api: ModbusAPI,
        config_entry: config_entries.ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{battery_id}",
            update_interval=timedelta(seconds=BATTERY_POLL_INTERVAL),
            config_entry=config_entry,
        )

        self.battery_id = battery_id
        self.sax_data = sax_data
        self.modbus_api = modbus_api
        self.last_update_success_time: datetime | None = None

        # Initialize ModbusItems with API reference
        self._setup_modbus_items()

    def _setup_modbus_items(self) -> None:
        """Set up ModbusItems with API reference for direct communication."""
        for item in self.sax_data.get_modbus_items_for_battery(self.battery_id):
            if isinstance(item, ModbusItem):
                item.set_api(self.modbus_api)

        # Set up SAXItems with coordinator references
        for sax_item in self.sax_data.get_sax_items_for_battery(self.battery_id):
            if isinstance(sax_item, SAXItem):
                # Pass all coordinators for multi-battery calculations
                sax_item.set_coordinators(self.sax_data.coordinators)

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data from battery using direct ModbusItem communication."""
        try:
            data: dict[str, Any] = {}

            # Update smart meter data if this is master battery
            if self.sax_data.should_poll_smart_meter(self.battery_id):
                await self._update_smart_meter_data(data)

            # Update battery data using direct ModbusItem calls
            for item in self.sax_data.get_modbus_items_for_battery(self.battery_id):
                if isinstance(item, ModbusItem):
                    value = await item.async_read_value()
                    data[item.name] = value

            # Update SAX calculated items
            for sax_item in self.sax_data.get_sax_items_for_battery(self.battery_id):
                if isinstance(sax_item, SAXItem):
                    calculated_value = await sax_item.async_read_value()
                    data[sax_item.name] = calculated_value

            self.last_update_success_time = datetime.now()
            return data  # noqa: TRY300

        except (ModbusException, OSError, TimeoutError) as err:
            _LOGGER.error("Error updating battery data: %s", err)
            raise UpdateFailed(
                f"Error communicating with battery {self.battery_id}"
            ) from err

    async def _update_smart_meter_data(self, data: dict[str, Any]) -> None:
        """Update smart meter data (only for master battery)."""
        try:
            for item in self.sax_data.get_smart_meter_items():
                if isinstance(item, ModbusItem):
                    # Set API reference if not already set
                    if item._modbus_api is None:  # noqa: SLF001
                        item.set_api(self.modbus_api)

                    value = await item.async_read_value()
                    data[item.name] = value

                    # Update smart meter model if available
                    if self.sax_data.smart_meter_data and value is not None:
                        self.sax_data.smart_meter_data.set_value(
                            item.name, float(value)
                        )

        except (ModbusException, OSError, TimeoutError) as err:
            _LOGGER.error("Error updating smart meter data: %s", err)

    async def async_write_number_value(self, item: ModbusItem, value: float) -> bool:
        """Write number value using direct ModbusItem communication."""
        if isinstance(item, ModbusItem):
            # Ensure API is set
            if item._modbus_api is None:  # noqa: SLF001
                item.set_api(self.modbus_api)
            return await item.async_write_value(value)
        return False  # type:ignore[unreachable]

    async def async_write_switch_value(self, item: ModbusItem, value: bool) -> bool:
        """Write switch value using direct ModbusItem communication."""
        if isinstance(item, ModbusItem):
            # Ensure API is set
            if item._modbus_api is None:  # noqa: SLF001
                item.set_api(self.modbus_api)

            # Convert boolean to appropriate switch value
            write_value = (
                item.get_switch_on_value() if value else item.get_switch_off_value()
            )
            return await item.async_write_value(write_value)
        return False  # type:ignore[unreachable]

    def update_sax_item_state(self, item: SAXItem | str, value: Any) -> None:
        """Update SAX item state in the coordinator data."""
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
        # Input validation (security)
        if not isinstance(power, (int, float)):
            raise ValueError("Power must be numeric")  # noqa: TRY004
        if not isinstance(power_factor, (int, float)):
            raise ValueError("Power factor must be numeric")  # noqa: TRY004

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
