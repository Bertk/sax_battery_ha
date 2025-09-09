"""Modbus communication classes."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

if TYPE_CHECKING:
    from .items import ModbusItem

_LOGGER = logging.getLogger(__name__)


class ModbusAPI:
    """Streamlined Modbus API for SAX Battery communication.

    Integrates directly with ModbusItem objects for efficient communication.
    No longer uses ModbusObject wrapper for better performance.
    """

    def __init__(self, host: str, port: int, battery_id: str) -> None:
        """Initialize ModbusAPI."""
        self._host = host
        self._port = port
        self._battery_id = battery_id
        self._modbus_client: ModbusTcpClient | None = None
        self._connect_pending = False

    async def connect(self, startup: bool = False) -> bool:
        """Connect to the modbus device."""
        if self._connect_pending:
            return False

        self._connect_pending = True

        try:
            self._modbus_client = ModbusTcpClient(host=self._host, port=self._port)
            if await asyncio.get_event_loop().run_in_executor(
                None, self._modbus_client.connect
            ):
                if self._modbus_client.connected:
                    _LOGGER.debug("Connected to modbus device %s", self._battery_id)
                    return True

            # Connection failed
            self._close_connection()
            return False  # noqa: TRY300
        except ModbusException as exc:
            _LOGGER.error("ModbusException during connect: %s", exc)
            self._close_connection()
            return False
        finally:
            self._connect_pending = False

    def close(self) -> bool:
        """Close the modbus connection."""
        try:
            return self._close_connection()
        except ModbusException as exc:
            _LOGGER.error("ModbusException during close: %s", exc)
            return False

    def _close_connection(self) -> bool:
        """Close the modbus connection."""
        if self._modbus_client is not None:
            self._modbus_client.close()  # type:ignore[no-untyped-call]
            self._modbus_client = None
        return True

    async def read_holding_registers(
        self, count: int, modbus_item: ModbusItem
    ) -> int | float | bool | None:
        """Read holding registers with SAX Battery specific data conversion."""
        if self._modbus_client is None or not self._modbus_client.connected:
            return None

        def _read() -> int | float | bool | None:
            try:
                # Type guard already handled above
                assert self._modbus_client is not None

                result = self._modbus_client.read_holding_registers(
                    address=modbus_item.address,
                    count=count,
                    device_id=modbus_item.battery_slave_id,
                )

                if result.isError() or not result.registers:
                    return None

                # Handle data conversion for SAX Battery specific types
                if hasattr(modbus_item, "data_type") and modbus_item.data_type:
                    converted_data = self._convert_sax_battery_data(
                        result.registers, modbus_item
                    )
                    if converted_data is not None:
                        return converted_data

                # Fallback processing
                if count == 1:
                    return self._process_single_register(
                        result.registers[0], modbus_item
                    )

                # Multiple registers - return first valid value
                for register_value in result.registers:
                    processed_value = self._process_single_register(
                        register_value, modbus_item
                    )
                    if processed_value is not None:
                        return processed_value

                return None  # noqa: TRY300

            except (ModbusException, ValueError, TypeError) as exc:
                _LOGGER.error("Error reading register %d: %s", modbus_item.address, exc)
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _read)

    async def write_registers(self, value: float, modbus_item: ModbusItem) -> bool:
        """Write to holding register with SAX Battery specific conversion."""
        if self._modbus_client is None or not self._modbus_client.connected:
            return False

        def _write() -> bool:
            try:
                # Type guard already handled above
                assert self._modbus_client is not None

                # Convert value using SAX Battery data type
                if hasattr(modbus_item, "data_type") and modbus_item.data_type:
                    converted_data = self._modbus_client.convert_to_registers(
                        value=value, data_type=modbus_item.data_type
                    )
                    # Handle both single values and lists
                    if isinstance(converted_data, (list, tuple)):
                        raw_values = list(converted_data)
                    else:
                        raw_values = [int(converted_data)]  # type: ignore[unreachable]
                else:
                    # Fallback conversion
                    raw_values = [int(value)]

                # Always use array for Write registers (code 0x10)
                result = self._modbus_client.write_registers(
                    address=modbus_item.address,
                    values=raw_values,
                    device_id=modbus_item.battery_slave_id,
                )
                return not result.isError()

            except (ModbusException, ValueError, TypeError) as exc:
                _LOGGER.error(
                    "Error writing to register %d: %s", modbus_item.address, exc
                )
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _write)

    async def write_nominal_power(
        self, value: float, power_factor: int, modbus_item: ModbusItem | None = None
    ) -> bool:
        """Write nominal power value to holding register with specific power factor.

        Args:
            value: The nominal power value to write
            power_factor: Power factor to apply
            modbus_item: Optional modbus item for address and device_id info

        Returns:
            bool: True if write was successful, False otherwise

        """
        if self._modbus_client is None or not self._modbus_client.connected:
            return False

        def _write() -> bool:
            try:
                # Determine address and device_id
                if modbus_item:
                    address = modbus_item.address
                    device_id = modbus_item.battery_slave_id
                else:
                    _LOGGER.error(
                        "ModbusItem is required for write_holding_registers operation"
                    )
                    return False

                # Check for valid SAX battery address
                if address != 41:
                    _LOGGER.error(
                        "Invalid address %s for nominal power write, only address 41 is supported",
                        address,
                    )
                    return False

                # Convert power to integer for Modbus
                power_int = int(value) & 0xFFFF

                # Convert PF to integer (assuming PF is a small decimal like 0.95)
                # Scale PF by 10 to preserve precision
                pf_int = int(power_factor * 10) & 0xFFFF

                # Type guard to ensure _modbus_client is not None
                if self._modbus_client is None:
                    return False

                result = self._modbus_client.write_registers(
                    address=address, values=[power_int, pf_int], device_id=device_id
                )
                return not result.isError()
            except ModbusException as exc:
                _LOGGER.error("Modbus error during nominal power write: %s", exc)
                return False
            except (ValueError, TypeError) as exc:
                _LOGGER.error(
                    "Value conversion error during nominal power write: %s", exc
                )
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _write)

    def _convert_sax_battery_data(
        self, registers: list[int], modbus_item: ModbusItem
    ) -> int | float | bool | None:
        """Convert register data for SAX Battery specific data types.

        SAX Battery supports:
        - UINT16: Unsigned 16-bit integer
        - INT16: Signed 16-bit integer
        - bool: Boolean values (0/1)

        Args:
            registers: List of register values from Modbus read
            modbus_item: ModbusItem containing data type and conversion info

        Returns:
            Converted value or None if conversion fails

        """
        try:
            # Type guard to ensure _modbus_client is not None
            if self._modbus_client is None:
                _LOGGER.error(
                    "Cannot convert data for register %d: Modbus client not connected",
                    modbus_item.address,
                )
                return None

            # Convert using pymodbus built-in converter
            converted_data = self._modbus_client.convert_from_registers(
                registers, modbus_item.data_type
            )

            # Debug logging for specific registers
            if modbus_item.address in (47, 48):
                _LOGGER.debug(
                    "Register %d conversion: %s -> %s (%s)",
                    modbus_item.address,
                    registers,
                    converted_data,
                    type(converted_data).__name__,
                )

            # Handle different return types from convert_from_registers
            if isinstance(converted_data, (list, tuple)):
                if not converted_data:
                    return None
                # Use first value from list/tuple
                first_value = converted_data[0]
                return self._apply_sax_battery_conversion(first_value, modbus_item)

            if isinstance(converted_data, (int, float, bool)):
                return self._apply_sax_battery_conversion(converted_data, modbus_item)

            # Unexpected data type from conversion
            _LOGGER.warning(
                "Unexpected converted data type %s for register %d",
                type(converted_data).__name__,
                modbus_item.address,
            )
            return None  # noqa: TRY300

        except ModbusException as exc:
            _LOGGER.error(
                "ModbusException converting data for register %d: %s",
                modbus_item.address,
                exc,
            )
            return None
        except (ValueError, TypeError) as exc:
            _LOGGER.error(
                "Data conversion error for register %d: %s",
                modbus_item.address,
                exc,
            )
            return None

    def _apply_sax_battery_conversion(
        self,
        value: int | float | bool,  # noqa: PYI041
        modbus_item: ModbusItem,
    ) -> int | float | bool | None:
        """Apply SAX Battery specific conversions (factor/offset).

        Args:
            value: Raw converted value
            modbus_item: ModbusItem with conversion parameters

        Returns:
            Converted value with proper typing

        """

        # Boolean values should not have factor/offset applied
        if isinstance(value, bool):
            return value

        # # Validate numeric value for factor/offset calculation
        # if not isinstance(value, (int, float)):
        #     _LOGGER.warning(
        #         "Cannot apply factor/offset to non-numeric value %s (%s) for register %d",
        #         value,
        #         type(value).__name__,
        #         modbus_item.address,
        #     )
        #     return None

        try:
            # Apply factor and offset: result = (raw_value - offset) * factor
            # Note: This is the inverse of the write operation
            converted_value = (value - modbus_item.offset) * modbus_item.factor

            # Ensure we return appropriate type based on the result
            if isinstance(converted_value, float) and converted_value.is_integer():
                # Return int if the float is actually a whole number
                return int(converted_value)

            return converted_value  # noqa: TRY300

        except (ValueError, TypeError, OverflowError) as exc:
            _LOGGER.error(
                "Error applying factor/offset to value %s for register %d: %s",
                value,
                modbus_item.address,
                exc,
            )
            return None

    def _process_single_register(
        self, raw_value: int, modbus_item: ModbusItem
    ) -> int | float | bool | None:
        """Process single register value for SAX Battery data types.

        Args:
            raw_value: Raw register value
            modbus_item: ModbusItem with type and conversion info

        Returns:
            Processed value or None if invalid

        """
        # if not isinstance(raw_value, int):
        #     _LOGGER.warning(
        #         "Expected integer register value, got %s (%s) for address %d",
        #         raw_value,
        #         type(raw_value).__name__,
        #         modbus_item.address,
        #     )
        #     return None

        # Handle boolean registers (typically 0/1 values)
        if (
            hasattr(modbus_item, "data_type")
            and "bool" in str(modbus_item.data_type).lower()
        ):
            return bool(raw_value)

        # For UINT16/INT16, apply standard conversion
        return self._apply_sax_battery_conversion(raw_value, modbus_item)
