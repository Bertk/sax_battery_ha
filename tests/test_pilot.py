"""Test SAX Battery pilot functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.sax_battery.coordinator import SAXBatteryCoordinator
from custom_components.sax_battery.pilot import (
    SAXBatteryPilot,
    SAXBatteryPilotEnabledSwitch,
    SAXBatterySolarChargingSwitch,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_hass():
    """Create mock Home Assistant."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def mock_sax_data():
    """Create mock SAX data."""
    data = MagicMock()
    data.get_modbus_items_for_battery.return_value = [
        MagicMock(name="sax_solar_charging", address=100),
        MagicMock(name="sax_pilot_enabled", address=101),
        MagicMock(name="sax_max_charge_power", address=102),
        MagicMock(name="sax_max_discharge_power", address=103),
    ]
    data.get_device_info.return_value = {}
    return data


@pytest.fixture
def mock_coordinator():
    """Create mock coordinator."""
    coordinator = MagicMock(spec=SAXBatteryCoordinator)
    coordinator.battery_id = "battery_a"
    coordinator.last_update_success = True
    coordinator.last_update_success_time = "2024-01-01T00:00:00+00:00"
    coordinator.data = {
        "sax_solar_charging": 1,
        "sax_pilot_enabled": 1,
        "sax_max_charge_power": 5000,
        "sax_max_discharge_power": 4000,
    }
    coordinator.async_write_modbus_register = AsyncMock(return_value=True)
    return coordinator


class TestSAXBatteryPilot:
    """Test SAX Battery pilot controller."""

    def test_pilot_init(self, mock_hass, mock_sax_data, mock_coordinator) -> None:
        """Test pilot initialization."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)

        assert pilot.hass == mock_hass
        assert pilot.sax_data == mock_sax_data
        assert pilot.coordinator == mock_coordinator
        assert pilot._pilot_enabled is True

    async def test_set_solar_charging_success(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test successful solar charging setting."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)

        success = await pilot.set_solar_charging(True)

        assert success is True
        mock_coordinator.async_write_modbus_register.assert_called_once()

    async def test_set_solar_charging_item_not_found(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test solar charging setting when item not found."""
        mock_sax_data.get_modbus_items_for_battery.return_value = []

        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)

        success = await pilot.set_solar_charging(True)

        assert success is False

    async def test_set_pilot_enabled_success(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test successful pilot enabled setting."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)

        success = await pilot.set_pilot_enabled(False)

        assert success is True
        assert pilot._pilot_enabled is False
        mock_coordinator.async_write_modbus_register.assert_called_once()

    async def test_set_charge_power_limit_success(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test successful charge power limit setting."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)

        success = await pilot.set_charge_power_limit(3000)

        assert success is True
        mock_coordinator.async_write_modbus_register.assert_called_once()

    async def test_set_discharge_power_limit_success(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test successful discharge power limit setting."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)

        success = await pilot.set_discharge_power_limit(3500)

        assert success is True
        mock_coordinator.async_write_modbus_register.assert_called_once()

    def test_pilot_properties(self, mock_hass, mock_sax_data, mock_coordinator) -> None:
        """Test pilot properties."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)

        assert pilot.is_pilot_enabled is True
        assert pilot.solar_charging_enabled is True
        assert pilot.current_charge_power_limit == 5000
        assert pilot.current_discharge_power_limit == 4000

    def test_pilot_properties_unavailable(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test pilot properties when coordinator unavailable."""
        mock_coordinator.last_update_success = False

        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)

        assert pilot.solar_charging_enabled is None
        assert pilot.current_charge_power_limit is None
        assert pilot.current_discharge_power_limit is None


class TestSAXBatterySolarChargingSwitch:
    """Test SAX Battery solar charging switch."""

    def test_solar_charging_switch_init(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test solar charging switch initialization."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatterySolarChargingSwitch(pilot, mock_coordinator)

        assert switch._pilot == pilot
        assert switch.unique_id == "battery_a_solar_charging"
        assert switch.name == "Battery A Solar Charging"
        assert switch.icon == "mdi:solar-power"

    def test_solar_charging_switch_is_on(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test solar charging switch is_on property."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatterySolarChargingSwitch(pilot, mock_coordinator)

        assert switch.is_on is True

    async def test_solar_charging_switch_turn_on(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test solar charging switch turn on."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatterySolarChargingSwitch(pilot, mock_coordinator)

        with patch.object(pilot, "set_solar_charging", return_value=True) as mock_set:
            await switch.async_turn_on()
            mock_set.assert_called_once_with(True)

    async def test_solar_charging_switch_turn_on_error(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test solar charging switch turn on error."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatterySolarChargingSwitch(pilot, mock_coordinator)

        with patch.object(pilot, "set_solar_charging", return_value=False):
            with pytest.raises(
                HomeAssistantError, match="Failed to enable solar charging"
            ):
                await switch.async_turn_on()

    async def test_solar_charging_switch_turn_off(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test solar charging switch turn off."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatterySolarChargingSwitch(pilot, mock_coordinator)

        with patch.object(pilot, "set_solar_charging", return_value=True) as mock_set:
            await switch.async_turn_off()
            mock_set.assert_called_once_with(False)


class TestSAXBatteryPilotEnabledSwitch:
    """Test SAX Battery pilot enabled switch."""

    def test_pilot_enabled_switch_init(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test pilot enabled switch initialization."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatteryPilotEnabledSwitch(pilot, mock_coordinator)

        assert switch._pilot == pilot
        assert switch.unique_id == "battery_a_pilot_enabled"
        assert switch.name == "Battery A Pilot Enabled"
        assert switch.icon == "mdi:auto-mode"
        assert switch.entity_category == "config"

    def test_pilot_enabled_switch_is_on(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test pilot enabled switch is_on property."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatteryPilotEnabledSwitch(pilot, mock_coordinator)

        assert switch.is_on is True

    async def test_pilot_enabled_switch_turn_on(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test pilot enabled switch turn on."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatteryPilotEnabledSwitch(pilot, mock_coordinator)

        with patch.object(pilot, "set_pilot_enabled", return_value=True) as mock_set:
            await switch.async_turn_on()
            mock_set.assert_called_once_with(True)

    async def test_pilot_enabled_switch_turn_off_error(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test pilot enabled switch turn off error."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatteryPilotEnabledSwitch(pilot, mock_coordinator)

        with patch.object(pilot, "set_pilot_enabled", return_value=False):
            with pytest.raises(HomeAssistantError, match="Failed to disable pilot"):
                await switch.async_turn_off()

    def test_pilot_enabled_switch_extra_attributes(
        self, mock_hass, mock_sax_data, mock_coordinator
    ) -> None:
        """Test pilot enabled switch extra state attributes."""
        pilot = SAXBatteryPilot(mock_hass, mock_sax_data, mock_coordinator)
        switch = SAXBatteryPilotEnabledSwitch(pilot, mock_coordinator)

        attributes = switch.extra_state_attributes
        assert attributes["battery_id"] == "battery_a"
        assert attributes["charge_power_limit"] == 5000
        assert attributes["discharge_power_limit"] == 4000
        assert "last_updated" in attributes
