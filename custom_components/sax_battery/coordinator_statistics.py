"""SAX Battery coordinator statistics and monitoring.

Encapsulates error collection, error rate calculation, cycle time statistics,
and diagnostic logging. Extracted from coordinator.py to satisfy
the 1000-line file size limit (SRP / Ruff D103).

Security:
    OWASP A05: Performance monitoring and error tracking for anomaly detection
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from statistics import mean, stdev
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from .circuit_breaker import CircuitBreaker
    from .modbusobject import OperationStatus

_LOGGER = logging.getLogger(__name__)


class CoordinatorStatistics:
    """Statistics and monitoring for SAX Battery coordinator.

    Encapsulates error collection, error rate calculation,
    cycle time statistics, and diagnostic logging.

    Uses composition pattern — instantiated by SAXBatteryCoordinator
    and given a reference to its CircuitBreaker for data access.

    Security:
        OWASP A05: Aggregated error metrics for monitoring and alerts
    """

    def __init__(
        self,
        circuit_breaker: CircuitBreaker,
        battery_id: str,
        last_cycle_duration_fn: Callable[[], float | None],
    ) -> None:
        """Initialize statistics tracker.

        Args:
            circuit_breaker: Circuit breaker instance for error/cycle data
            battery_id: Battery identifier for log messages
            last_cycle_duration_fn: Callable returning the last cycle duration

        Security:
            OWASP A05: Explicit dependencies prevent hidden state access
        """
        self._circuit_breaker = circuit_breaker
        self._battery_id = battery_id
        self._last_cycle_duration_fn = last_cycle_duration_fn

    def collect_modbus_error(self, status: OperationStatus) -> None:
        """Collect error from last ModbusAPI operation for statistics.

        Args:
            status: Last operation status from ModbusAPI

        Security:
            OWASP A05: Aggregates errors for monitoring (not circuit breaker)
        """
        if not status.success and status.error_type:
            # Include all 3 tuple elements (timestamp, error_type, register_address)
            self._circuit_breaker.error_history.append(
                (
                    status.timestamp or datetime.now(),
                    status.error_type,
                    status.register_address,  # Include register_address (can be None)
                )
            )

    def calculate_errors_per_hour(self) -> float:
        """Calculate error rate from collected history with time-based decay.

        Returns:
            Number of errors that occurred in the last 60 minutes

        Security:
            OWASP A05: Time-windowed error tracking prevents unbounded growth
        """
        if not self._circuit_breaker.error_history:
            return 0.0

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        # Only count errors within last hour (automatic decay)
        recent_error_count = sum(
            1
            for timestamp, _, _ in self._circuit_breaker.error_history
            if timestamp >= one_hour_ago
        )

        # Clean up old errors beyond 1 hour to prevent unbounded growth
        # This ensures the deque doesn't fill with ancient errors
        cutoff_time = now - timedelta(hours=2)  # Keep 2 hours for safety margin
        while (
            self._circuit_breaker.error_history
            and self._circuit_breaker.error_history[0][0] < cutoff_time
        ):
            self._circuit_breaker.error_history.popleft()

        return float(recent_error_count)

    def log_cycle_statistics(self) -> None:
        """Log coordinator cycle time statistics.

        Calculates and logs:
        - Average cycle time
        - Min/Max cycle times
        - Standard deviation
        - Errors per hour (instead of failure rate percentage)

        Security:
            OWASP A05: Performance monitoring for anomaly detection
        """
        if not self._circuit_breaker.cycle_times:
            return

        avg_time = mean(self._circuit_breaker.cycle_times)
        min_time = min(self._circuit_breaker.cycle_times)
        max_time = max(self._circuit_breaker.cycle_times)
        std_dev = (
            stdev(self._circuit_breaker.cycle_times)
            if len(self._circuit_breaker.cycle_times) > 1
            else 0.0
        )
        errors_per_hour = self.calculate_errors_per_hour()

        _LOGGER.info(
            "%s: Cycle stats (n=%d): avg=%.2fs, min=%.2fs, max=%.2fs, "
            "stddev=%.2fs, errors/hr=%.1f, circuit_breaker=%s",
            self._battery_id,
            len(self._circuit_breaker.cycle_times),
            avg_time,
            min_time,
            max_time,
            std_dev,
            errors_per_hour,
            "OPEN" if self._circuit_breaker.is_open else "CLOSED",
        )
        # Log detailed error breakdown
        self.log_error_statistics()

    def log_error_statistics(self) -> None:
        """Log detailed error statistics for diagnostics.

        Security:
            OWASP A05: Structured error logging for monitoring and alerts
        """
        if not self._circuit_breaker.error_history:
            return

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)

        # Count errors by type in last hour
        error_counts: dict[str, int] = {}
        register_errors: dict[int, int] = {}

        for (
            timestamp,
            error_type,
            register_address,
        ) in self._circuit_breaker.error_history:
            # Only count errors in last hour
            if timestamp < one_hour_ago:
                continue

            # Count by error type
            if error_type:
                error_counts[error_type] = error_counts.get(error_type, 0) + 1

            # Count by register address
            if register_address is not None:
                register_errors[register_address] = (
                    register_errors.get(register_address, 0) + 1
                )

        # Log error breakdown for diagnostics
        total_errors = sum(error_counts.values())
        if total_errors > 0:
            # Format error counts for logging
            error_breakdown = ", ".join(
                f"{error_type}: {count}"
                for error_type, count in sorted(error_counts.items())
            )

            _LOGGER.info(
                "%s: Error statistics (last hour): %d total errors - %s",
                self._battery_id,
                total_errors,
                error_breakdown,
            )

            # Log top 3 most affected registers
            if register_errors:
                top_registers = sorted(
                    register_errors.items(), key=lambda x: x[1], reverse=True
                )[:3]
                register_summary = ", ".join(
                    f"addr_{addr}: {count}" for addr, count in top_registers
                )
                _LOGGER.info(
                    "%s: Most affected registers: %s",
                    self._battery_id,
                    register_summary,
                )

    @property
    def cycle_time_statistics(self) -> dict[str, Any]:
        """Get cycle time and error statistics.

        Returns:
            Dictionary with performance metrics

        Security:
            OWASP A05: Exposes aggregated error metrics
        """
        # Calculate error breakdown
        error_counts: dict[str, int] = {}
        failed_registers: dict[int, int] = {}

        for _, error_type, register_address in self._circuit_breaker.error_history:
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
            if register_address is not None:
                failed_registers[register_address] = (
                    failed_registers.get(register_address, 0) + 1
                )

        if not self._circuit_breaker.cycle_times:
            return {
                "average": 0.0,
                "min": 0.0,
                "max": 0.0,
                "stddev": 0.0,
                "last": 0.0,
                "errors_per_hour": self.calculate_errors_per_hour(),
                "circuit_breaker_open": 0.0,
                "modbus_errors": error_counts.get("modbus", 0),
                "network_errors": error_counts.get("network", 0),
                "timeout_errors": error_counts.get("timeout", 0),
                "failed_registers": failed_registers,
                "last_error_time": (
                    self._circuit_breaker.error_history[-1][0].isoformat()
                    if self._circuit_breaker.error_history
                    else None
                ),
            }

        return {
            "average": mean(self._circuit_breaker.cycle_times),
            "min": min(self._circuit_breaker.cycle_times),
            "max": max(self._circuit_breaker.cycle_times),
            "stddev": (
                stdev(self._circuit_breaker.cycle_times)
                if len(self._circuit_breaker.cycle_times) > 1
                else 0.0
            ),
            "last": self._last_cycle_duration_fn() or 0.0,
            "errors_per_hour": self.calculate_errors_per_hour(),
            "circuit_breaker_open": (1.0 if self._circuit_breaker.is_open else 0.0),
            "modbus_errors": error_counts.get("modbus", 0),
            "network_errors": error_counts.get("network", 0),
            "timeout_errors": error_counts.get("timeout", 0),
            "failed_registers": failed_registers,
            "last_error_time": (
                self._circuit_breaker.error_history[-1][0].isoformat()
                if self._circuit_breaker.error_history
                else None
            ),
        }
