"""Test SAX Battery coordinator statistics.

Tests for CoordinatorStatistics extracted from coordinator.py.
Validates error collection, error rate calculation, cycle time statistics,
and diagnostic logging in isolation.

Security:
    OWASP A05: Validates monitoring and error tracking behavior
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging
from unittest.mock import MagicMock

import pytest

from custom_components.sax_battery.coordinator_statistics import CoordinatorStatistics
from custom_components.sax_battery.modbusobject import OperationStatus


class TestCoordinatorStatistics:
    """Test CoordinatorStatistics class."""

    @pytest.fixture
    def mock_circuit_breaker_stats(self) -> MagicMock:
        """Create mock circuit breaker for statistics tests."""
        cb = MagicMock()
        cb.error_history = deque()
        cb.cycle_times = deque()
        cb.is_open = False
        return cb

    @pytest.fixture
    def coordinator_stats(
        self, mock_circuit_breaker_stats: MagicMock
    ) -> CoordinatorStatistics:
        """Create CoordinatorStatistics instance for testing."""
        return CoordinatorStatistics(
            circuit_breaker=mock_circuit_breaker_stats,
            battery_id="bess_a",
            last_cycle_duration_fn=lambda: 1.5,
        )

    # --- collect_modbus_error tests ---

    def test_collect_modbus_error_on_failure(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test error collection when operation fails."""
        now = datetime.now()
        status = OperationStatus(
            success=False,
            error_type="modbus",
            error_message="Connection refused",
            timestamp=now,
            register_address=40113,
        )

        coordinator_stats.collect_modbus_error(status)

        assert len(mock_circuit_breaker_stats.error_history) == 1
        timestamp, error_type, register_addr = mock_circuit_breaker_stats.error_history[
            0
        ]
        assert timestamp == now
        assert error_type == "modbus"
        assert register_addr == 40113

    def test_collect_modbus_error_skips_success(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test that successful operations are not collected."""
        status = OperationStatus(success=True)

        coordinator_stats.collect_modbus_error(status)

        assert len(mock_circuit_breaker_stats.error_history) == 0

    def test_collect_modbus_error_skips_no_error_type(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test that failures without error_type are not collected."""
        status = OperationStatus(
            success=False,
            error_type=None,
        )

        coordinator_stats.collect_modbus_error(status)

        assert len(mock_circuit_breaker_stats.error_history) == 0

    def test_collect_modbus_error_with_none_timestamp(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test error collection generates timestamp when None."""
        status = OperationStatus(
            success=False,
            error_type="timeout",
            timestamp=None,
            register_address=None,
        )

        coordinator_stats.collect_modbus_error(status)

        assert len(mock_circuit_breaker_stats.error_history) == 1
        timestamp, error_type, register_addr = mock_circuit_breaker_stats.error_history[
            0
        ]
        assert isinstance(timestamp, datetime)
        assert error_type == "timeout"
        assert register_addr is None

    def test_collect_modbus_error_multiple_errors(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test collecting multiple errors."""
        now = datetime.now()
        for i in range(5):
            status = OperationStatus(
                success=False,
                error_type="network",
                timestamp=now + timedelta(seconds=i),
                register_address=40100 + i,
            )
            coordinator_stats.collect_modbus_error(status)

        assert len(mock_circuit_breaker_stats.error_history) == 5

    # --- calculate_errors_per_hour tests ---

    def test_calculate_errors_per_hour_empty(
        self,
        coordinator_stats: CoordinatorStatistics,
    ) -> None:
        """Test error rate with empty history."""
        assert coordinator_stats.calculate_errors_per_hour() == 0.0

    def test_calculate_errors_per_hour_recent_errors(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test error rate with recent errors."""
        now = datetime.now()
        mock_circuit_breaker_stats.error_history.extend(
            [
                (now - timedelta(minutes=10), "modbus", None),
                (now - timedelta(minutes=20), "network", 40113),
                (now - timedelta(minutes=30), "timeout", None),
            ]
        )

        result = coordinator_stats.calculate_errors_per_hour()

        assert result == 3.0

    def test_calculate_errors_per_hour_excludes_old_errors(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test that errors older than 1 hour are not counted."""
        now = datetime.now()
        mock_circuit_breaker_stats.error_history.extend(
            [
                (now - timedelta(minutes=10), "modbus", None),  # Recent
                (
                    now - timedelta(hours=2),
                    "network",
                    None,
                ),  # Old (counted but not in window)
            ]
        )

        result = coordinator_stats.calculate_errors_per_hour()

        assert result == 1.0

    def test_calculate_errors_per_hour_cleans_old_entries(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test that entries older than 2 hours are cleaned up."""
        now = datetime.now()
        mock_circuit_breaker_stats.error_history.extend(
            [
                (now - timedelta(hours=3), "modbus", None),  # Should be cleaned
                (now - timedelta(hours=3), "network", None),  # Should be cleaned
                (now - timedelta(minutes=30), "timeout", None),  # Should remain
            ]
        )

        coordinator_stats.calculate_errors_per_hour()

        # Old entries beyond 2-hour cutoff should be removed
        assert len(mock_circuit_breaker_stats.error_history) == 1

    # --- log_cycle_statistics tests ---

    def test_log_cycle_statistics_empty_cycle_times(
        self,
        coordinator_stats: CoordinatorStatistics,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that logging is skipped with empty cycle times."""
        with caplog.at_level(logging.INFO):
            coordinator_stats.log_cycle_statistics()

        # No info log should be emitted
        assert "Cycle stats" not in caplog.text

    def test_log_cycle_statistics_with_data(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test cycle statistics logging with data."""
        mock_circuit_breaker_stats.cycle_times.extend([1.0, 2.0, 3.0])

        with caplog.at_level(logging.INFO):
            coordinator_stats.log_cycle_statistics()

        assert "bess_a: Cycle stats" in caplog.text
        assert "avg=2.00s" in caplog.text
        assert "min=1.00s" in caplog.text
        assert "max=3.00s" in caplog.text
        assert "CLOSED" in caplog.text

    def test_log_cycle_statistics_circuit_breaker_open(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test logging shows OPEN when circuit breaker is open."""
        mock_circuit_breaker_stats.cycle_times.extend([1.0, 2.0])
        mock_circuit_breaker_stats.is_open = True

        with caplog.at_level(logging.INFO):
            coordinator_stats.log_cycle_statistics()

        assert "OPEN" in caplog.text

    def test_log_cycle_statistics_single_value(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test logging with single cycle time (stddev=0)."""
        mock_circuit_breaker_stats.cycle_times.append(1.5)

        with caplog.at_level(logging.INFO):
            coordinator_stats.log_cycle_statistics()

        assert "stddev=0.00s" in caplog.text

    # --- log_error_statistics tests ---

    def test_log_error_statistics_empty_history(
        self,
        coordinator_stats: CoordinatorStatistics,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that logging is skipped with empty error history."""
        with caplog.at_level(logging.INFO):
            coordinator_stats.log_error_statistics()

        assert "Error statistics" not in caplog.text

    def test_log_error_statistics_with_recent_errors(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test error statistics logging with recent errors."""
        now = datetime.now()
        mock_circuit_breaker_stats.error_history.extend(
            [
                (now - timedelta(minutes=5), "modbus", 40113),
                (now - timedelta(minutes=10), "modbus", 40113),
                (now - timedelta(minutes=15), "network", 40200),
            ]
        )

        with caplog.at_level(logging.INFO):
            coordinator_stats.log_error_statistics()

        assert "3 total errors" in caplog.text
        assert "modbus: 2" in caplog.text
        assert "network: 1" in caplog.text
        assert "Most affected registers" in caplog.text
        assert "addr_40113" in caplog.text

    def test_log_error_statistics_old_errors_not_counted(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that old errors are not logged in statistics."""
        now = datetime.now()
        mock_circuit_breaker_stats.error_history.extend(
            [
                (now - timedelta(hours=2), "modbus", None),  # Old
            ]
        )

        with caplog.at_level(logging.INFO):
            coordinator_stats.log_error_statistics()

        # No error statistics logged (all errors are old)
        assert "Error statistics" not in caplog.text

    def test_log_error_statistics_no_register_addresses(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test error statistics without register addresses."""
        now = datetime.now()
        mock_circuit_breaker_stats.error_history.extend(
            [
                (now - timedelta(minutes=5), "timeout", None),
            ]
        )

        with caplog.at_level(logging.INFO):
            coordinator_stats.log_error_statistics()

        assert "1 total errors" in caplog.text
        assert "timeout: 1" in caplog.text
        assert "Most affected registers" not in caplog.text

    # --- cycle_time_statistics property tests ---

    def test_cycle_time_statistics_empty(
        self,
        coordinator_stats: CoordinatorStatistics,
    ) -> None:
        """Test statistics with no cycle times."""
        stats = coordinator_stats.cycle_time_statistics

        assert stats["average"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0
        assert stats["stddev"] == 0.0
        assert stats["last"] == 0.0
        assert stats["errors_per_hour"] == 0.0
        assert stats["circuit_breaker_open"] == 0.0
        assert stats["modbus_errors"] == 0
        assert stats["network_errors"] == 0
        assert stats["timeout_errors"] == 0
        assert stats["failed_registers"] == {}
        assert stats["last_error_time"] is None

    def test_cycle_time_statistics_with_data(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test statistics with cycle times and errors."""
        now = datetime.now()
        mock_circuit_breaker_stats.cycle_times.extend([1.0, 2.0, 3.0])
        mock_circuit_breaker_stats.error_history.extend(
            [
                (now - timedelta(minutes=10), "modbus", 40113),
                (now - timedelta(minutes=20), "network", None),
                (now - timedelta(minutes=30), "timeout", 40200),
            ]
        )

        stats = coordinator_stats.cycle_time_statistics

        assert stats["average"] == 2.0
        assert stats["min"] == 1.0
        assert stats["max"] == 3.0
        assert stats["stddev"] > 0.0
        assert stats["last"] == 1.5  # From last_cycle_duration_fn
        assert stats["errors_per_hour"] == 3.0
        assert stats["circuit_breaker_open"] == 0.0
        assert stats["modbus_errors"] == 1
        assert stats["network_errors"] == 1
        assert stats["timeout_errors"] == 1
        assert 40113 in stats["failed_registers"]
        assert 40200 in stats["failed_registers"]
        assert stats["last_error_time"] is not None

    def test_cycle_time_statistics_circuit_breaker_open(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test statistics with open circuit breaker."""
        mock_circuit_breaker_stats.cycle_times.extend([1.0])
        mock_circuit_breaker_stats.is_open = True

        stats = coordinator_stats.cycle_time_statistics

        assert stats["circuit_breaker_open"] == 1.0

    def test_cycle_time_statistics_single_cycle(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test statistics with single cycle time (stddev=0)."""
        mock_circuit_breaker_stats.cycle_times.extend([2.5])

        stats = coordinator_stats.cycle_time_statistics

        assert stats["average"] == 2.5
        assert stats["min"] == 2.5
        assert stats["max"] == 2.5
        assert stats["stddev"] == 0.0

    def test_cycle_time_statistics_last_error_time(
        self,
        coordinator_stats: CoordinatorStatistics,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test last_error_time is from most recent error."""
        now = datetime.now()
        mock_circuit_breaker_stats.error_history.extend(
            [
                (now - timedelta(minutes=30), "modbus", None),
                (now - timedelta(minutes=5), "network", None),
            ]
        )

        stats = coordinator_stats.cycle_time_statistics

        # last_error_time should be from the last entry in the deque
        expected_time = (now - timedelta(minutes=5)).isoformat()
        assert stats["last_error_time"] == expected_time

    def test_cycle_time_statistics_last_cycle_duration_none(
        self,
        mock_circuit_breaker_stats: MagicMock,
    ) -> None:
        """Test statistics when last_cycle_duration_fn returns None."""
        stats_obj = CoordinatorStatistics(
            circuit_breaker=mock_circuit_breaker_stats,
            battery_id="bess_b",
            last_cycle_duration_fn=lambda: None,
        )
        mock_circuit_breaker_stats.cycle_times.extend([1.0, 2.0])

        stats = stats_obj.cycle_time_statistics

        assert stats["last"] == 0.0
