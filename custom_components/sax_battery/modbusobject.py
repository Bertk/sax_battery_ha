"""Modbus communication classes."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException, ModbusIOException
from pymodbus.pdu import ExceptionResponse
from pymodbus.pdu.pdu import ModbusPDU
from pymodbus.pdu.register_message import (
    ReadHoldingRegistersResponse,
    WriteMultipleRegistersResponse,
)

if TYPE_CHECKING:
    from .items import ModbusItem

ModbusResponse = (
    ReadHoldingRegistersResponse
    | WriteMultipleRegistersResponse
    | ExceptionResponse
    | ModbusPDU
)

_LOGGER = logging.getLogger(__name__)


class ModbusAPI:
    """Streamlined Modbus API for SAX Battery communication.

    Handles SAX Battery Modbus transaction ID bug by using no_response_expected=True
    and implementing robust connection recovery for dropped connections.
    """

    def __init__(self, host: str, port: int, battery_id: str) -> None:
        """Initialize ModbusAPI."""
        self._host = host
        self._port = port
        self._battery_id = battery_id
        self._modbus_client: ModbusTcpClient | None = None
        self._connect_pending = False
        self._connection_retries = 0
        self._max_retries = 3
        self._retry_delay = 1.0

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
                    self._connection_retries = 0  # Reset retry counter on success
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

    def is_connected(self) -> bool:
        """Check if modbus client is connected."""
        return (
            self._modbus_client is not None
            and hasattr(self._modbus_client, "connected")
            and self._modbus_client.connected
        )

    async def _ensure_connection(self) -> bool:
        """Ensure modbus connection is established with retry logic."""
        if self.is_connected():
            return True

        _LOGGER.debug(
            "Connection lost for %s, attempting to reconnect", self._battery_id
        )

        for attempt in range(self._max_retries):
            if await self.connect():
                _LOGGER.debug(
                    "Reconnected to %s on attempt %d/%d",
                    self._battery_id,
                    attempt + 1,
                    self._max_retries,
                )
                return True

            if attempt < self._max_retries - 1:
                delay = self._retry_delay * (2**attempt)  # Exponential backoff
                _LOGGER.debug(
                    "Connection attempt %d/%d failed for %s, retrying in %.1fs",
                    attempt + 1,
                    self._max_retries,
                    self._battery_id,
                    delay,
                )
                await asyncio.sleep(delay)

        _LOGGER.error(
            "Failed to reconnect to %s after %d attempts",
            self._battery_id,
            self._max_retries,
        )
        return False

    async def read_holding_registers(
        self, count: int, modbus_item: ModbusItem
    ) -> int | float | bool | None:
        """Read holding registers with SAX Battery specific data conversion."""
        if not await self._ensure_connection():
            return None

        def _read() -> int | float | bool | None:
            try:
                # Type guard already handled by _ensure_connection
                assert self._modbus_client is not None

                result = self._modbus_client.read_holding_registers(
                    address=modbus_item.address,
                    count=count,
                    device_id=modbus_item.battery_slave_id,
                )

                if result.isError() or not result.registers:
                    # Check for connection-related errors
                    if self._is_connection_error(result):
                        _LOGGER.warning(
                            "Connection error reading register %d for %s",
                            modbus_item.address,
                            self._battery_id,
                        )
                        self._close_connection()
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

            except (ConnectionException, ModbusIOException) as exc:
                _LOGGER.warning(
                    "Connection lost reading register %d for %s: %s",
                    modbus_item.address,
                    self._battery_id,
                    exc,
                )
                self._close_connection()
                return None
            except (ModbusException, ValueError, TypeError) as exc:
                _LOGGER.error("Error reading register %d: %s", modbus_item.address, exc)
                return None

        return await asyncio.get_event_loop().run_in_executor(None, _read)

    async def write_registers(self, value: float, modbus_item: ModbusItem) -> bool:
        """Write to holding register with SAX Battery specific conversion and connection recovery.

        Uses no_response_expected=True to work around SAX Battery transaction ID bug.
        """
        if not await self._ensure_connection():
            return False

        def _write() -> bool:
            try:
                # Type guard already handled by _ensure_connection
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
                        raw_values = [int(converted_data)]  # type:ignore[unreachable]
                else:
                    # Fallback conversion with proper scaling
                    scaled_value = (value / modbus_item.factor) + modbus_item.offset
                    raw_values = [int(scaled_value)]

                # Use no_response_expected=True to work around SAX Battery transaction ID bug
                result = self._modbus_client.write_registers(
                    address=modbus_item.address,
                    values=raw_values,
                    device_id=modbus_item.battery_slave_id,
                    no_response_expected=True,
                )

                _LOGGER.debug(
                    "Wrote registers at address %d: %s (raw: %s), error: %s, result: %s",
                    modbus_item.address,
                    value,
                    raw_values,
                    result.isError(),
                    result,
                )

                # Handle SAX Battery specific success conditions
                if result.isError():
                    # ExceptionResponse(0xff) with exception_code=0 is success for write-only registers
                    if (
                        result.function_code == 0xFF
                        and hasattr(result, "exception_code")
                        and result.exception_code == 0
                    ):
                        return True

                    # Check for connection-related errors
                    if self._is_connection_error(result):
                        _LOGGER.warning(
                            "Connection error writing to register %d for %s",
                            modbus_item.address,
                            self._battery_id,
                        )
                        self._close_connection()
                        return False

                    _LOGGER.warning(
                        "Write failed for register %d: function_code=%s, exception_code=%s",
                        modbus_item.address,
                        getattr(result, "function_code", "unknown"),
                        getattr(result, "exception_code", "unknown"),
                    )
                    return False

                return True  # noqa: TRY300

            except (ConnectionException, ModbusIOException) as exc:
                _LOGGER.warning(
                    "Connection lost writing to register %d for %s: %s",
                    modbus_item.address,
                    self._battery_id,
                    exc,
                )
                self._close_connection()
                return False
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

        Uses no_response_expected=True to work around SAX Battery transaction ID bug.
        Implements automatic connection recovery for dropped connections.

        Args:
            value: The nominal power value to write
            power_factor: Power factor as scaled integer (e.g., 9500 for 0.95)
            modbus_item: Optional modbus item for address and device_id info

        Returns:
            bool: True if write was successful, False otherwise

        """
        if not await self._ensure_connection():
            return False

        def _write() -> bool:
            try:
                # Determine address and device_id
                if modbus_item:
                    address = modbus_item.address
                    device_id = modbus_item.battery_slave_id
                else:
                    _LOGGER.error(
                        "ModbusItem is required for write_nominal_power operation"
                    )
                    return False

                # Security: Check for valid SAX battery address
                if address != 41:
                    _LOGGER.error(
                        "Invalid address %s for nominal power write, only address 41 is supported",
                        address,
                    )
                    return False

                # Convert power to integer for Modbus (security: input validation)
                if not isinstance(value, (int, float)):
                    raise TypeError("Power value must be numeric")  # noqa: TRY301
                power_int = int(value) & 0xFFFF

                # Power factor is already scaled integer (security: validate range)
                if not isinstance(power_factor, int) or not (
                    0 <= power_factor <= 10000
                ):
                    raise ValueError(  # noqa: TRY301
                        f"Power factor {power_factor} outside valid range [0, 10000]"
                    )
                pf_int = power_factor & 0xFFFF

                # Type guard to ensure _modbus_client is not None
                if self._modbus_client is None:
                    return False

                # Use no_response_expected=True to work around SAX Battery transaction ID bug
                result = self._modbus_client.write_registers(
                    address=address,
                    values=[power_int, pf_int],
                    device_id=device_id,
                    no_response_expected=True,
                )

                _LOGGER.debug(
                    "Wrote pilot control registers at address %d: power=%s, power_factor=%s, error=%s",
                    address,
                    power_int,
                    pf_int,
                    result.isError(),
                )

                # Handle SAX Battery specific success conditions
                if result.isError():
                    # ExceptionResponse(0xff) with exception_code=0 is success for write-only registers
                    if (
                        result.function_code == 0xFF
                        and hasattr(result, "exception_code")
                        and result.exception_code == 0
                    ):
                        return True

                    # Check for connection-related errors
                    if self._is_connection_error(result):
                        _LOGGER.warning(
                            "Connection error writing pilot control for %s",
                            self._battery_id,
                        )
                        self._close_connection()
                        return False

                    _LOGGER.warning(
                        "Pilot control write failed: function_code=%s, exception_code=%s",
                        getattr(result, "function_code", "unknown"),
                        getattr(result, "exception_code", "unknown"),
                    )
                    return False

                return True  # noqa: TRY300

            except (ConnectionException, ModbusIOException) as exc:
                _LOGGER.warning(
                    "Connection lost during pilot control write for %s: %s",
                    self._battery_id,
                    exc,
                )
                self._close_connection()
                return False
            except ModbusException as exc:
                _LOGGER.error("Modbus error during nominal power write: %s", exc)
                return False
            except (ValueError, TypeError) as exc:
                _LOGGER.error(
                    "Value conversion error during nominal power write: %s", exc
                )
                return False

        return await asyncio.get_event_loop().run_in_executor(None, _write)

    def _is_connection_error(self, result: ModbusResponse) -> bool:
        """Check if the result indicates a connection error.

        Analyzes Modbus response objects to determine if errors are connection-related
        rather than protocol or data errors. Uses multiple detection strategies for
        robust error classification.

        Args:
            result: Modbus result object (any response or exception type)

        Returns:
            bool: True if this appears to be a connection error

        Security Note:
            Input validation through hasattr() checks prevents attribute access errors.
            String analysis is limited to lowercase conversion to prevent injection.
        """
        # Strategy 1: Check for Modbus exception codes
        if hasattr(result, "exception_code"):
            try:
                exception_code = int(result.exception_code)
                # Modbus exception codes indicating connection/communication issues
                # Reference: Modbus Application Protocol Specification V1.1b3
                connection_error_codes = [
                    1,  # Illegal Function - device may be unreachable
                    4,  # Slave Device Failure - device communication failure
                    6,  # Slave Device Busy - device temporarily unavailable
                    10,  # Gateway Path Unavailable - network routing issue
                    11,  # Gateway Target Device Failed to Respond - timeout/unreachable
                ]

                if exception_code in connection_error_codes:
                    _LOGGER.debug(
                        "Connection error detected via exception code %d",
                        exception_code,
                    )
                    return True

            except (ValueError, TypeError, AttributeError) as exc:
                _LOGGER.debug("Failed to parse exception_code: %s", exc)

        # Strategy 2: Check error status and analyze string representation
        if hasattr(result, "isError"):
            try:
                if callable(result.isError) and result.isError():
                    # Safely convert to string and analyze for connection keywords
                    result_str = str(result).lower()

                    # Connection-related error patterns
                    connection_indicators = [
                        "connection",
                        "closed",
                        "timeout",
                        "disconnected",
                        "network",
                        "socket",
                        "reset",
                        "broken pipe",
                        "refused",
                        "unreachable",
                        "timed out",
                        "connection lost",
                        "connection refused",
                        "no route to host",
                        "network unreachable",
                        "connection reset",
                        "connection aborted",
                        "host unreachable",
                        "connection failed",
                    ]

                    for indicator in connection_indicators:
                        if indicator in result_str:
                            _LOGGER.debug(
                                "Connection error detected via string analysis: %s",
                                indicator,
                            )
                            return True

            except (AttributeError, TypeError) as exc:
                _LOGGER.debug("Failed to analyze result error status: %s", exc)

        # Strategy 3: Fallback string analysis for any object
        try:
            result_str = str(result).lower()
            # Look for critical connection failure keywords
            critical_indicators = [
                "connection refused",
                "connection reset",
                "connection timeout",
                "network unreachable",
                "host unreachable",
                "connection failed",
                "connection closed",
                "socket error",
                "broken pipe",
            ]

            for indicator in critical_indicators:
                if indicator in result_str:
                    _LOGGER.debug(
                        "Connection error detected via fallback analysis: %s", indicator
                    )
                    return True

        except Exception as exc:  # noqa: BLE001
            # Catch-all for any unexpected errors during string conversion
            _LOGGER.debug("Failed to convert result to string: %s", exc)

        return False

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
        value: float | bool,
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
        # Handle boolean registers (typically 0/1 values)
        if (
            hasattr(modbus_item, "data_type")
            and "bool" in str(modbus_item.data_type).lower()
        ):
            return bool(raw_value)

        # For UINT16/INT16, apply standard conversion
        return self._apply_sax_battery_conversion(raw_value, modbus_item)
