"""Modbus communication classes."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

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

# Network error codes that indicate broken connections
BROKEN_CONNECTION_ERRORS = {
    32,  # EPIPE - Broken pipe
    104,  # ECONNRESET - Connection reset by peer
    110,  # ETIMEDOUT - Connection timed out
    111,  # ECONNREFUSED - Connection refused
    113,  # EHOSTUNREACH - No route to host
}

_LOGGER = logging.getLogger(__name__)


class ModbusAPI:
    """Streamlined Modbus API for SAX Battery communication.

    Handles SAX Battery Modbus transaction ID bug by using no_response_expected=True
    and implements robust connection recovery for dropped connections.

    Security: Validates all inputs and implements proper error handling
    Performance: Uses connection pooling and efficient retry strategies
    """

    def __init__(self, host: str, port: int, battery_id: str) -> None:
        """Initialize Modbus API with connection parameters.

        Args:
            host: Target host IP or hostname
            port: Target TCP port
            battery_id: Unique battery identifier for logging

        Security: Input validation prevents injection attacks
        """
        # OWASP A03: Input validation to prevent injection
        if not isinstance(host, str) or not host.strip():
            raise ValueError("Host must be a non-empty string")
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError("Port must be an integer between 1 and 65535")
        if not isinstance(battery_id, str) or not battery_id.strip():
            raise ValueError("Battery ID must be a non-empty string")

        self.host = host.strip()
        self.port = port
        self.battery_id = battery_id.strip()
        self.modbus_client: ModbusTcpClient | None = None
        self.connect_pending = False
        self.consecutive_failures = 0
        self.last_successful_connection: float | None = None
        self.connection_lock = asyncio.Lock()

    async def connect(self, startup: bool = False) -> bool:
        """Connect to modbus device with automatic retry on failure.

        Args:
            startup: Whether this is a startup connection attempt

        Returns:
            bool: True if connection successful, False otherwise

        Security: Implements connection timeout and retry limits
        Performance: Uses async locking to prevent connection races
        """
        async with self.connection_lock:
            return await self._connect_internal(startup)

    async def _connect_internal(self, startup: bool = False) -> bool:
        """Internal connection method with proper error handling.

        Security: Validates connection state before proceeding
        Performance: Efficient connection cleanup and establishment
        """
        if self.connect_pending:
            _LOGGER.debug(
                "Connection attempt already in progress for %s", self.battery_id
            )
            return False

        self.connect_pending = True

        try:
            # Close existing connection if any
            if self.modbus_client is not None:
                try:
                    self.modbus_client.close()  # type: ignore[no-untyped-call]
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Error closing existing connection for %s: %s",
                        self.battery_id,
                        err,
                    )
                finally:
                    self.modbus_client = None

            # Create new client with pymodbus v3.11.1 compatible settings
            self.modbus_client = ModbusTcpClient(
                host=self.host,
                port=self.port,
                timeout=5.0,  # Connection timeout
            )

            # Attempt connection
            _LOGGER.debug(
                "Connecting to modbus device %s at %s:%d",
                self.battery_id,
                self.host,
                self.port,
            )

            try:
                connect_result = await asyncio.get_event_loop().run_in_executor(
                    None, self.modbus_client.connect
                )
            except OSError as err:
                # Network-level connection errors
                if err.errno in BROKEN_CONNECTION_ERRORS:
                    _LOGGER.warning(
                        "Network error connecting to %s: %s", self.battery_id, err
                    )
                else:
                    _LOGGER.error("Connection error for %s: %s", self.battery_id, err)
                raise
            except Exception as err:
                _LOGGER.error(
                    "Unexpected error connecting to %s: %s", self.battery_id, err
                )
                raise

            if not connect_result or not self.modbus_client.connected:
                _LOGGER.warning("Failed to establish connection to %s", self.battery_id)
                if self.modbus_client:
                    self.modbus_client.close()  # type: ignore[no-untyped-call]
                    self.modbus_client = None
                return False

            # Connection successful
            self.last_successful_connection = time.time()
            self.consecutive_failures = 0

            _LOGGER.debug("Connected to modbus device %s", self.battery_id)
            return True  # noqa: TRY300

        except (OSError, ConnectionException, ModbusException) as err:
            self.consecutive_failures += 1
            _LOGGER.error(
                "Connection failed for %s (attempt %d): %s",
                self.battery_id,
                self.consecutive_failures,
                err,
            )

            # Clean up failed connection
            if self.modbus_client:
                try:
                    self.modbus_client.close()  # type: ignore[no-untyped-call]
                except Exception:  # noqa: BLE001
                    pass  # Ignore cleanup errors
                finally:
                    self.modbus_client = None

            return False

        except Exception as err:  # noqa: BLE001
            # Unexpected errors - log and fail
            self.consecutive_failures += 1
            _LOGGER.error(
                "Unexpected connection error for %s: %s", self.battery_id, err
            )

            if self.modbus_client:
                try:
                    self.modbus_client.close()  # type: ignore[no-untyped-call]
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    self.modbus_client = None

            return False

        finally:
            self.connect_pending = False

    def close(self) -> bool:
        """Close the modbus connection.

        Returns:
            bool: True if closed successfully, False otherwise

        Security: Handles cleanup errors gracefully
        """
        try:
            return self._close_connection()
        except ModbusException as exc:
            _LOGGER.error("ModbusException during close: %s", exc)
            return False

    def _close_connection(self) -> bool:
        """Close the modbus connection."""
        if self.modbus_client is not None:
            self.modbus_client.close()  # type: ignore[no-untyped-call]
            self.modbus_client = None
        return True

    def is_connected(self) -> bool:
        """Check if modbus client is connected.

        Returns:
            bool: True if connected, False otherwise

        Security: Safe attribute access with proper checks
        """
        return (
            self.modbus_client is not None
            and hasattr(self.modbus_client, "connected")
            and self.modbus_client.connected
        )

    async def read_holding_registers(
        self, count: int, modbus_item: ModbusItem, max_retries: int = 3
    ) -> int | float | None:
        """Read holding registers with automatic reconnection on failure.

        Args:
            count: Number of registers to read
            modbus_item: ModbusItem containing read parameters
            max_retries: Maximum retry attempts

        Returns:
            Converted register value or None if failed

        Security: Input validation and error handling
        Performance: Efficient retry logic with backoff
        """
        # Security: Input validation
        if not isinstance(count, int) or count <= 0:
            raise ValueError("Count must be a positive integer")
        if count > 125:  # Modbus protocol limit
            raise ValueError("Count exceeds Modbus protocol limit of 125 registers")

        if self.modbus_client is None:
            _LOGGER.debug(
                "No client available for %s, attempting connection", self.battery_id
            )
            if not await self.connect():
                return None

        if not self.is_connected():
            _LOGGER.debug(
                "Client not connected for %s, attempting reconnection", self.battery_id
            )
            if not await self.connect():
                return None

        for attempt in range(max_retries + 1):
            try:
                # Type guard to ensure modbus_client is not None
                if self.modbus_client is None:
                    return None

                # Create a wrapper function for executor
                def _read_registers() -> ModbusResponse:
                    # Type guard ensures modbus_client is not None at this point
                    assert self.modbus_client is not None
                    return self.modbus_client.read_holding_registers(
                        address=modbus_item.address,
                        count=count,
                        device_id=modbus_item.battery_slave_id,
                    )

                # Attempt to read registers
                result = await asyncio.get_event_loop().run_in_executor(
                    None, _read_registers
                )

                if result.isError():
                    error_msg = str(result)
                    _LOGGER.warning(
                        "Modbus read error for %s register %d: %s",
                        self.battery_id,
                        modbus_item.address,
                        error_msg,
                    )

                    # Enhanced error detection for connection issues
                    connection_error_indicators = [
                        "connection",
                        "timeout",
                        "broken",
                        "reset",
                        "refused",
                        "unreachable",
                        "pipe",
                        "socket",
                    ]

                    if any(
                        err_text in error_msg.lower()
                        for err_text in connection_error_indicators
                    ):
                        if attempt < max_retries:
                            _LOGGER.debug(
                                "Connection error detected, attempting reconnection for %s",
                                self.battery_id,
                            )
                            if await self.reconnect_on_error():
                                continue  # Retry with new connection

                    return None

                # Success - extract and convert value
                if not result.registers:
                    _LOGGER.debug(
                        "Empty register data for %s register %d",
                        self.battery_id,
                        modbus_item.address,
                    )
                    return None

                raw_value = (
                    result.registers[0]
                    if len(result.registers) == 1
                    else result.registers
                )
                converted_value = self.convert_register_value(raw_value, modbus_item)

                # Reset failure counter on success
                self.consecutive_failures = 0
                return converted_value  # noqa: TRY300

            except OSError as err:
                # Enhanced network error handling
                if err.errno in BROKEN_CONNECTION_ERRORS:
                    _LOGGER.warning(
                        "Network error reading from %s: [Errno %d] %s (attempt %d/%d)",
                        self.battery_id,
                        err.errno,
                        err,
                        attempt + 1,
                        max_retries + 1,
                    )

                    if attempt < max_retries:
                        if await self.reconnect_on_error():
                            continue  # Retry with new connection
                else:
                    _LOGGER.error(
                        "Unexpected OS error reading from %s: [Errno %d] %s",
                        self.battery_id,
                        getattr(err, "errno", "unknown"),
                        err,
                    )

                # If we can't recover, return None
                return None

            except (ConnectionException, ModbusIOException, ModbusException) as err:
                _LOGGER.warning(
                    "Modbus error reading from %s: %s (attempt %d/%d)",
                    self.battery_id,
                    err,
                    attempt + 1,
                    max_retries + 1,
                )

                if attempt < max_retries:
                    if await self.reconnect_on_error():
                        continue  # Retry with new connection

                return None

            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Unexpected error reading from %s: %s", self.battery_id, err
                )
                return None

        # All retries exhausted
        _LOGGER.error(
            "Failed to read from %s after %d attempts",
            self.battery_id,
            max_retries + 1,
        )
        return None

    async def write_holding_register(
        self, modbus_item: ModbusItem, value: float, max_retries: int = 3
    ) -> bool:
        """Write to holding register with automatic reconnection on failure.

        Args:
            modbus_item: ModbusItem containing write parameters
            value: Value to write
            max_retries: Maximum retry attempts

        Returns:
            bool: True if write successful, False otherwise

        Security: Input validation and safe conversion
        Performance: Efficient retry with exponential backoff
        """
        # Security: Input validation
        if not isinstance(value, (int, float)):
            raise TypeError("Value must be numeric")

        if self.modbus_client is None:
            _LOGGER.debug(
                "No client available for %s, attempting connection", self.battery_id
            )
            if not await self.connect():
                return False

        if not self.is_connected():
            _LOGGER.debug(
                "Client not connected for %s, attempting reconnection", self.battery_id
            )
            if not await self.connect():
                return False

        # Convert value according to modbus item specifications
        converted_value = self.convert_value_for_write(value, modbus_item)

        for attempt in range(max_retries + 1):
            try:
                # Type guard to ensure modbus_client is not None
                if self.modbus_client is None:
                    return False

                # Create a wrapper function for executor
                def _write_register() -> ModbusResponse:
                    # Type guard ensures modbus_client is not None at this point
                    assert self.modbus_client is not None
                    return self.modbus_client.write_register(
                        address=modbus_item.address,
                        value=converted_value,
                        device_id=modbus_item.battery_slave_id,
                    )

                result = await asyncio.get_event_loop().run_in_executor(
                    None, _write_register
                )

                if result.isError():
                    error_msg = str(result)
                    _LOGGER.warning(
                        "Modbus write error for %s register %d: %s",
                        self.battery_id,
                        modbus_item.address,
                        error_msg,
                    )

                    # Enhanced error detection for connection issues
                    connection_error_indicators = [
                        "connection",
                        "timeout",
                        "broken",
                        "reset",
                        "refused",
                        "unreachable",
                        "pipe",
                        "socket",
                    ]

                    if any(
                        err_text in error_msg.lower()
                        for err_text in connection_error_indicators
                    ):
                        if attempt < max_retries:
                            _LOGGER.debug(
                                "Connection error detected, attempting reconnection for %s",
                                self.battery_id,
                            )
                            if await self.reconnect_on_error():
                                continue  # Retry with new connection

                    return False

                # Success
                _LOGGER.debug(
                    "Successfully wrote %s to %s register %d",
                    converted_value,
                    self.battery_id,
                    modbus_item.address,
                )
                self.consecutive_failures = 0
                return True  # noqa: TRY300

            except OSError as err:
                # Enhanced network error handling
                if err.errno in BROKEN_CONNECTION_ERRORS:
                    _LOGGER.warning(
                        "Network error writing to %s: [Errno %d] %s (attempt %d/%d)",
                        self.battery_id,
                        err.errno,
                        err,
                        attempt + 1,
                        max_retries + 1,
                    )

                    if attempt < max_retries:
                        if await self.reconnect_on_error():
                            continue  # Retry with new connection
                else:
                    _LOGGER.error(
                        "Unexpected OS error writing to %s: [Errno %d] %s",
                        self.battery_id,
                        getattr(err, "errno", "unknown"),
                        err,
                    )

                return False

            except (ConnectionException, ModbusIOException, ModbusException) as err:
                _LOGGER.warning(
                    "Modbus error writing to %s: %s (attempt %d/%d)",
                    self.battery_id,
                    err,
                    attempt + 1,
                    max_retries + 1,
                )

                if attempt < max_retries:
                    if await self.reconnect_on_error():
                        continue  # Retry with new connection

                return False

            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Unexpected error writing to %s: %s", self.battery_id, err
                )
                return False

        # All retries exhausted
        _LOGGER.error(
            "Failed to write to %s after %d attempts", self.battery_id, max_retries + 1
        )
        return False

    async def reconnect_on_error(self) -> bool:
        """Attempt to reconnect after an error with enhanced backoff.

        Returns:
            bool: True if reconnection successful, False otherwise

        Performance: Progressive delay based on failure history
        Security: Limited retry attempts to prevent resource exhaustion
        """
        _LOGGER.debug(
            "Connection lost for %s, attempting to reconnect", self.battery_id
        )

        # Close the broken connection
        if self.modbus_client:
            try:
                self.modbus_client.close()  # type: ignore[no-untyped-call]
            except Exception:  # noqa: BLE001
                pass  # Ignore cleanup errors
            finally:
                self.modbus_client = None

        # Progressive delay based on consecutive failures
        base_delay = min(0.5 + (self.consecutive_failures * 0.2), 2.0)
        await asyncio.sleep(base_delay)

        # Attempt reconnection with fewer retries as failures accumulate
        max_attempts = max(1, 4 - self.consecutive_failures)

        for attempt in range(max_attempts):
            if await self.connect():
                _LOGGER.debug(
                    "Reconnected to %s on attempt %d/%d",
                    self.battery_id,
                    attempt + 1,
                    max_attempts,
                )
                return True

            if attempt < max_attempts - 1:
                # Progressive backoff: 1s, 2s, 4s
                backoff_delay = min(2**attempt, 4)
                _LOGGER.debug(
                    "Reconnection attempt %d failed, waiting %ds before retry",
                    attempt + 1,
                    backoff_delay,
                )
                await asyncio.sleep(backoff_delay)

        _LOGGER.warning(
            "Failed to reconnect to %s after %d attempts",
            self.battery_id,
            max_attempts,
        )
        self.consecutive_failures += 1
        return False

    def should_force_reconnect(self) -> bool:
        """Determine if connection should be forcefully recreated.

        Returns:
            bool: True if reconnection should be forced

        Performance: Prevents hanging connections
        Security: Limits connection lifetime for security
        """
        # Force reconnect after too many consecutive failures
        if self.consecutive_failures > 10:
            return True

        # Force reconnect if connection has been idle too long
        if self.last_successful_connection:
            idle_time = time.time() - self.last_successful_connection
            if idle_time > 300:  # 5 minutes
                return True

        return False

    @property
    def connection_health(self) -> dict[str, Any]:
        """Get detailed connection health information.

        Returns:
            dict: Connection health metrics

        Performance: Efficient health status calculation
        Security: No sensitive information exposed
        """
        current_time = time.time()

        health_status = "good"
        if self.consecutive_failures > 5:
            health_status = "poor"
        elif self.consecutive_failures > 2:
            health_status = "degraded"

        return {
            "connected": self.is_connected(),
            "consecutive_failures": self.consecutive_failures,
            "last_successful_connection": self.last_successful_connection,
            "seconds_since_last_success": (
                current_time - self.last_successful_connection
                if self.last_successful_connection
                else None
            ),
            "battery_id": self.battery_id,
            "host": self.host,
            "port": self.port,
            "health_status": health_status,
            "should_force_reconnect": self.should_force_reconnect(),
        }

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

        Security: Validates all inputs and addresses
        Performance: Single transaction for both registers
        """
        if not await self.ensure_connection():
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

                # Type guard to ensure modbus_client is not None
                if self.modbus_client is None:
                    return False

                # Use no_response_expected=True to work around SAX Battery transaction ID bug
                result = self.modbus_client.write_registers(
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
                    if self.is_connection_error(result):
                        _LOGGER.warning(
                            "Connection error writing pilot control for %s",
                            self.battery_id,
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
                    self.battery_id,
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

    async def ensure_connection(self) -> bool:
        """Ensure modbus connection is established with retry logic.

        Returns:
            bool: True if connection is ready, False otherwise

        Performance: Efficient connection state checking
        Security: Connection timeout limits
        """
        if self.is_connected():
            return True

        _LOGGER.debug(
            "Connection lost for %s, attempting to reconnect", self.battery_id
        )

        # Simple retry with backoff
        for attempt in range(3):
            if await self.connect():
                _LOGGER.debug(
                    "Reconnected to %s on attempt %d/3",
                    self.battery_id,
                    attempt + 1,
                )
                return True

            if attempt < 2:
                delay = 1.0 * (2**attempt)  # Exponential backoff
                _LOGGER.debug(
                    "Connection attempt %d/3 failed for %s, retrying in %.1fs",
                    attempt + 1,
                    self.battery_id,
                    delay,
                )
                await asyncio.sleep(delay)

        _LOGGER.error(
            "Failed to reconnect to %s after 3 attempts",
            self.battery_id,
        )
        return False

    def is_connection_error(self, result: ModbusResponse) -> bool:
        """Check if the result indicates a connection error.

        Analyzes Modbus response objects to determine if errors are connection-related
        rather than protocol or data errors. Uses multiple detection strategies for
        robust error classification.

        Args:
            result: Modbus result object (any Modbus response type)

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

        return False

    def convert_value_for_write(self, value: float, modbus_item: ModbusItem) -> int:
        """Convert value for writing to Modbus register.

        Args:
            value: Value to convert
            modbus_item: ModbusItem containing conversion info

        Returns:
            int: Converted integer value for Modbus write

        Security: Input validation and range checking
        Performance: Efficient conversion with bounds checking
        """
        try:
            # Security: Input validation
            if not isinstance(value, (int, float)):
                raise TypeError("Value must be numeric")  # noqa: TRY301

            # Apply inverse conversion: modbus_value = (value / factor) + offset
            modbus_value = (value / modbus_item.factor) + modbus_item.offset

            # Convert to integer and ensure it fits in 16-bit register
            int_value = int(modbus_value)

            # Security: Range validation for 16-bit register
            if not (-32768 <= int_value <= 65535):
                _LOGGER.warning(
                    "Value %s out of range for 16-bit register, clamping",
                    int_value,
                )
                int_value = max(-32768, min(65535, int_value))

            return int_value & 0xFFFF  # Ensure 16-bit unsigned

        except (ValueError, TypeError, ZeroDivisionError) as exc:
            _LOGGER.error(
                "Error converting value %s for write to %s: %s",
                value,
                modbus_item.name,
                exc,
            )
            # Return safe default
            return 0

    def convert_register_value(
        self, raw_value: int | list[int], modbus_item: ModbusItem
    ) -> int | float | None:
        """Convert raw register value using ModbusItem specifications.

        Args:
            raw_value: Raw register value(s) from Modbus read
            modbus_item: ModbusItem containing conversion info

        Returns:
            Converted value or None if conversion fails

        Security: Input validation and safe type conversion
        Performance: Efficient data type handling with proper error recovery
        """
        try:
            # Security: Input validation
            if raw_value is None:
                return None  # type:ignore [unreachable]

            if isinstance(raw_value, list) and not raw_value:
                _LOGGER.debug("Empty register list for %s", modbus_item.name)
                return None

            # Step 1: Extract working value from raw input
            if isinstance(raw_value, list):
                if len(raw_value) == 1:
                    # Single register in list format
                    work_value: int | float = raw_value[0]
                else:
                    # Multi-register value - combine according to data type
                    work_value = self._combine_registers(raw_value, modbus_item)
            else:
                # Single integer value
                work_value = raw_value

            _LOGGER.debug(
                "Register %d initial conversion: %s -> %s (%s)",
                modbus_item.address,
                raw_value,
                work_value,
                type(work_value).__name__,
            )

            # Step 2: Apply data type conversion using pymodbus if available
            if hasattr(modbus_item, "data_type") and modbus_item.data_type:
                converted_value = self._convert_data_type(work_value, modbus_item)
                if converted_value is not None:
                    work_value = converted_value

            # Step 3: Apply factor and offset transformation
            final_value = self._apply_factor_and_offset(work_value, modbus_item)

            _LOGGER.debug(
                "Register %d final conversion: %s -> %s",
                modbus_item.address,
                work_value,
                final_value,
            )

            return final_value  # noqa: TRY300

        except (ValueError, TypeError, AttributeError) as exc:
            _LOGGER.error(
                "Error converting register value %s for %s: %s",
                raw_value,
                modbus_item.name,
                exc,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            # Security: Catch any unexpected errors to prevent crashes
            _LOGGER.error(
                "Unexpected error converting register value %s for %s: %s",
                raw_value,
                modbus_item.name,
                exc,
            )
            return None

    def _combine_registers(self, registers: list[int], modbus_item: ModbusItem) -> int:
        """Combine multiple registers into a single value.

        Args:
            registers: List of register values to combine
            modbus_item: ModbusItem for context and logging

        Returns:
            Combined integer value

        Security: Validates register count and prevents overflow
        Performance: Efficient bit operations for register combination
        """
        if len(registers) == 1:
            return registers[0]
        if len(registers) == 2:
            # 32-bit value: high register first (big-endian)
            # Security: Check for valid register values
            high_reg = registers[0] & 0xFFFF
            low_reg = registers[1] & 0xFFFF
            combined = (high_reg << 16) | low_reg

            _LOGGER.debug(
                "Combined 32-bit registers for %s: [%04X, %04X] -> %08X (%d)",
                modbus_item.name,
                high_reg,
                low_reg,
                combined,
                combined,
            )
            return combined
        if len(registers) == 4:
            # 64-bit value: combine four 16-bit registers
            # Security: Validate all register values
            regs = [reg & 0xFFFF for reg in registers]
            combined = (regs[0] << 48) | (regs[1] << 32) | (regs[2] << 16) | regs[3]

            _LOGGER.debug(
                "Combined 64-bit registers for %s: %s -> %016X (%d)",
                modbus_item.name,
                [f"{reg:04X}" for reg in regs],
                combined,
                combined,
            )
            return combined
        # Unsupported register count - use first register as fallback
        _LOGGER.warning(
            "Unsupported register count %d for %s, using first register",
            len(registers),
            modbus_item.name,
        )
        return registers[0]

    def _convert_data_type(
        self, work_value: float, modbus_item: ModbusItem
    ) -> int | float | None:
        """Convert value according to ModbusItem data type specifications.

        Args:
            work_value: Value to convert
            modbus_item: ModbusItem containing data type info

        Returns:
            Converted value or None if conversion fails

        Security: Safe type conversion with validation
        Performance: Efficient type detection and conversion
        """
        try:
            data_type = modbus_item.data_type

            # Handle boolean data type
            if "bool" in str(data_type).lower():
                # Convert any non-zero value to True
                return bool(work_value)

            # Handle string data types (convert to string representation)
            # if "string" in str(data_type).lower():
            #     return str(work_value)

            # Handle signed integer conversion using pymodbus if available
            if self.modbus_client and hasattr(
                self.modbus_client, "convert_from_registers"
            ):
                try:
                    # Convert single value to list for pymodbus conversion
                    if isinstance(work_value, (int, float)):
                        register_list = [int(work_value) & 0xFFFF]
                    else:
                        register_list = [work_value]  # type:ignore [unreachable]

                    # Use pymodbus conversion
                    converted_data = self.modbus_client.convert_from_registers(
                        register_list, data_type
                    )

                    # Extract converted value
                    if isinstance(converted_data, (list, tuple)) and converted_data:
                        return converted_data[0]
                    if isinstance(converted_data, (int, float)):
                        return converted_data

                    # Conversion returned unexpected type
                    _LOGGER.debug(
                        "Pymodbus conversion returned unexpected type %s for %s",
                        type(converted_data).__name__,
                        modbus_item.name,
                    )
                    return None  # noqa: TRY300

                except (ValueError, TypeError, AttributeError) as exc:
                    _LOGGER.debug(
                        "Pymodbus conversion failed for %s: %s, using manual conversion",
                        modbus_item.name,
                        exc,
                    )

            # Manual conversion for common data types
            return self._manual_data_type_conversion(work_value, data_type, modbus_item)

        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(
                "Data type conversion failed for %s: %s, using original value",
                modbus_item.name,
                exc,
            )
            return None

    def _manual_data_type_conversion(
        self, work_value: float, data_type: Any, modbus_item: ModbusItem
    ) -> int | float:
        """Manual data type conversion for common Modbus data types.

        Args:
            work_value: Value to convert
            data_type: Data type specification
            modbus_item: ModbusItem for context

        Returns:
            Converted value

        Performance: Fast manual conversion for common cases
        Security: Bounds checking for integer conversions
        """
        # Convert data_type to string for comparison
        data_type_str = str(data_type).lower()

        # Handle signed 16-bit integers
        if "int16" in data_type_str or "short" in data_type_str:
            int_value = int(work_value) & 0xFFFF
            # Convert unsigned to signed 16-bit
            if int_value > 32767:
                signed_value = int_value - 65536
                _LOGGER.debug(
                    "Converted unsigned %d to signed %d for %s",
                    int_value,
                    signed_value,
                    modbus_item.name,
                )
                return signed_value
            return int_value

        # Handle signed 32-bit integers
        if "int32" in data_type_str or "long" in data_type_str:
            int_value = int(work_value) & 0xFFFFFFFF
            # Convert unsigned to signed 32-bit
            if int_value > 2147483647:
                signed_value = int_value - 4294967296
                _LOGGER.debug(
                    "Converted unsigned %d to signed %d for %s",
                    int_value,
                    signed_value,
                    modbus_item.name,
                )
                return signed_value
            return int_value

        # Handle float types
        if "float" in data_type_str or "real" in data_type_str:
            return float(work_value)

        # Default: return as-is
        return work_value

    def _apply_factor_and_offset(
        self,
        work_value: int | float,  # noqa: PYI041
        modbus_item: ModbusItem,
    ) -> int | float:
        """Apply factor and offset transformations to the value.

        Args:
            work_value: Value to transform
            modbus_item: ModbusItem containing factor and offset

        Returns:
            Transformed value

        Security: Validates numeric inputs and prevents overflow
        Performance: Efficient arithmetic operations
        """
        try:
            # Security: Ensure we have numeric values
            if not isinstance(work_value, (int, float)):
                _LOGGER.warning(  # type:ignore [unreachable]
                    "Cannot apply factor/offset to non-numeric value %s for %s",
                    work_value,
                    modbus_item.name,
                )
                return work_value

            # Get factor and offset with defaults
            factor = getattr(modbus_item, "factor", 1.0)
            offset = getattr(modbus_item, "offset", 0.0)

            # Security: Validate factor and offset are numeric
            if not isinstance(factor, (int, float)):
                _LOGGER.warning(
                    "Invalid factor %s for %s, using 1.0",
                    factor,
                    modbus_item.name,
                )
                factor = 1.0

            if not isinstance(offset, (int, float)):
                _LOGGER.warning(
                    "Invalid offset %s for %s, using 0.0",
                    offset,
                    modbus_item.name,
                )
                offset = 0.0

            # Apply transformation: result = (raw_value * factor) + offset
            result = (work_value * factor) + offset

            # Return appropriate type based on whether we have fractional parts
            if isinstance(result, float):
                # If result is a whole number and original was integer, return int
                if (
                    result.is_integer()
                    and isinstance(work_value, int)
                    and factor == 1.0
                ):
                    return int(result)
                return result

            return result  # noqa: TRY300

        except (ValueError, TypeError, OverflowError) as exc:
            _LOGGER.error(
                "Error applying factor/offset to %s for %s: %s",
                work_value,
                modbus_item.name,
                exc,
            )
            # Return original value as fallback
            return work_value
