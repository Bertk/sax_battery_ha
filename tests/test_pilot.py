"""Test pilot platform for SAX Battery integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.sax_battery.const import (
    CONF_PILOT_FROM_HA,
    DOMAIN,
    MANUAL_CONTROL_SWITCH,
    PILOT_ITEMS,
    PILOT_POWER_ENTITY,
    SOLAR_CHARGING_SWITCH,
)
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import SAXItem
from custom_components.sax_battery.pilot import (
    SAXBatteryManualControlSwitch,
    SAXBatteryPilot,
    SAXBatterySolarChargingSwitch,
    async_setup_entry,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


@pytest.fixture
def pilot_items_mixed() -> list[SAXItem]:
    """Return pilot items with both number and switch entities."""
    # fmt: off
    return [
        SAXItem(name=PILOT_POWER_ENTITY, mtype=TypeConstants.NUMBER, device=DeviceConstants.SYS),
        SAXItem(name=SOLAR_CHARGING_SWITCH, mtype=TypeConstants.SWITCH, device=DeviceConstants.SYS),
        SAXItem(name=MANUAL_CONTROL_SWITCH, mtype=TypeConstants.SWITCH, device=DeviceConstants.SYS),
    ]
    # fmt: on


class TestAsyncSetupEntry:
    """Test async_setup_entry function."""

    @pytest.fixture
    def mock_hass_pilot_setup_entry(self) -> MagicMock:
        """Create mock Home Assistant instance."""
        mock_hass = MagicMock(spec=HomeAssistant)
        mock_hass.data = {}
        return mock_hass

    @pytest.fixture
    def mock_config_entry_pilot_setup_entry(self) -> MagicMock:
        """Create mock config entry."""
        entry = MagicMock(spec=ConfigEntry)
        entry.entry_id = "test_entry_id"
        entry.data = {CONF_PILOT_FROM_HA: True}
        return entry

    @pytest.fixture
    def mock_coordinator_pilot_setup_entry(self) -> MagicMock:
        """Create mock coordinator."""
        coordinator = MagicMock()
        coordinator.battery_id = "battery_a"
        coordinator.update_interval = 30
        coordinator.sax_data.get_device_info.return_value = {
            "identifiers": {("sax_battery", "battery_a")},
            "name": "SAX Battery A",
        }
        return coordinator

    @pytest.fixture
    def mock_sax_data_pilot_setup_entry(
        self, mock_coordinator_pilot_setup_entry
    ) -> MagicMock:
        """Create mock SAXBatteryData."""
        sax_data = MagicMock()
        sax_data.master_battery_id = "battery_a"
        sax_data.coordinators = {"battery_a": mock_coordinator_pilot_setup_entry}
        # Mock the entry property that SAXBatteryPilot expects
        sax_data.entry = MagicMock()
        sax_data.entry.data = {CONF_PILOT_FROM_HA: True}
        return sax_data

    async def test_setup_entry_with_master_battery(
        self,
        mock_hass_pilot_setup_entry,
        mock_config_entry_pilot_setup_entry,
        mock_sax_data_pilot_setup_entry,
        pilot_items_mixed,
    ):
        """Test setup entry creates pilot entities for master battery."""
        with (
            patch(
                "custom_components.sax_battery.pilot.async_track_time_interval"
            ) as mock_track,
            patch("custom_components.sax_battery.pilot.PILOT_ITEMS", pilot_items_mixed),
            patch(
                "custom_components.sax_battery.pilot.SAXBatteryPilot"
            ) as mock_pilot_class,
        ):
            # Setup mock pilot instance
            mock_pilot = MagicMock()
            mock_pilot.async_start = AsyncMock()
            mock_pilot_class.return_value = mock_pilot

            mock_track.return_value = MagicMock()

            mock_hass_pilot_setup_entry.data = {
                DOMAIN: {
                    mock_config_entry_pilot_setup_entry.entry_id: {
                        "coordinators": mock_sax_data_pilot_setup_entry.coordinators,
                        "sax_data": mock_sax_data_pilot_setup_entry,
                    }
                }
            }

            async_add_entities = MagicMock()

            await async_setup_entry(
                mock_hass_pilot_setup_entry,
                mock_config_entry_pilot_setup_entry,
                async_add_entities,
            )

            # Verify pilot was created and started
            mock_pilot_class.assert_called_once()
            mock_pilot.async_start.assert_called_once()

            # Verify entities were added
            async_add_entities.assert_called_once()
            call_args = async_add_entities.call_args
            assert call_args.kwargs["update_before_add"] is True
            entities = call_args.args[0]
            assert len(entities) == 3

            # Check entity types based on their names rather than order
            entity_types = {type(entity).__name__ for entity in entities}
            expected_types = {
                "SAXBatteryPilotPowerEntity",
                "SAXBatterySolarChargingSwitch",
                "SAXBatteryManualControlSwitch",
            }
            assert entity_types == expected_types

    async def test_setup_entry_pilot_disabled(
        self, mock_hass_pilot_setup_entry, mock_sax_data_pilot_setup_entry
    ):
        """Test setup entry when pilot from HA is disabled."""
        # Create config entry with pilot disabled
        mock_config_entry = MagicMock(spec=ConfigEntry)
        mock_config_entry.entry_id = "test_entry_id"
        mock_config_entry.data = {CONF_PILOT_FROM_HA: False}

        mock_hass_pilot_setup_entry.data = {
            DOMAIN: {
                mock_config_entry.entry_id: {
                    "coordinators": mock_sax_data_pilot_setup_entry.coordinators,
                    "sax_data": mock_sax_data_pilot_setup_entry,
                }
            }
        }

        async_add_entities = MagicMock()

        with patch("custom_components.sax_battery.pilot.PILOT_ITEMS", []):
            await async_setup_entry(
                mock_hass_pilot_setup_entry, mock_config_entry, async_add_entities
            )

            # async_add_entities is NOT called when there are no entities to add
            async_add_entities.assert_not_called()

    async def test_setup_entry_no_master_battery(
        self, mock_hass_pilot_setup_entry, mock_config_entry_pilot_setup_entry
    ):
        """Test setup entry with no master battery creates no entities."""
        mock_sax_data = MagicMock()
        mock_sax_data.master_battery_id = None
        mock_hass_pilot_setup_entry.data = {
            DOMAIN: {
                mock_config_entry_pilot_setup_entry.entry_id: {
                    "coordinators": {},
                    "sax_data": mock_sax_data,
                }
            }
        }

        async_add_entities = MagicMock()

        await async_setup_entry(
            mock_hass_pilot_setup_entry,
            mock_config_entry_pilot_setup_entry,
            async_add_entities,
        )

        # async_add_entities is NOT called when there are no entities to add
        async_add_entities.assert_not_called()

    async def test_setup_entry_master_battery_not_in_coordinators(
        self, mock_hass_pilot_setup_entry, mock_config_entry_pilot_setup_entry
    ):
        """Test setup entry when master battery is not in coordinators."""
        mock_sax_data = MagicMock()
        mock_sax_data.master_battery_id = "battery_a"
        mock_sax_data.coordinators = {}  # Empty coordinators
        mock_hass_pilot_setup_entry.data = {
            DOMAIN: {
                mock_config_entry_pilot_setup_entry.entry_id: {
                    "coordinators": {},
                    "sax_data": mock_sax_data,
                }
            }
        }

        async_add_entities = MagicMock()

        await async_setup_entry(
            mock_hass_pilot_setup_entry,
            mock_config_entry_pilot_setup_entry,
            async_add_entities,
        )

        # async_add_entities is NOT called when there are no entities to add
        async_add_entities.assert_not_called()


class TestSAXBatteryPilot:
    """Test SAXBatteryPilot class."""

    @pytest.fixture
    def mock_hass_pilot_instance(self) -> MagicMock:
        """Create mock Home Assistant instance."""
        return MagicMock(spec=HomeAssistant)

    @pytest.fixture
    def mock_coordinator_pilot_instance(self) -> MagicMock:
        """Create mock coordinator."""
        coordinator = MagicMock()
        coordinator.battery_id = "battery_a"
        coordinator.data = {}
        coordinator.async_set_updated_data = MagicMock()
        coordinator.async_write_int_value = AsyncMock(return_value=True)
        coordinator.last_update_success = True
        return coordinator

    @pytest.fixture
    def mock_sax_data_pilot_instance(self) -> MagicMock:
        """Create mock SAXBatteryData."""
        sax_data = MagicMock()
        # Mock the entry property
        sax_data.entry = MagicMock()
        sax_data.entry.data = {CONF_PILOT_FROM_HA: True}
        charge_item = MagicMock()
        charge_item.name = "sax_max_charge_power"
        discharge_item = MagicMock()
        discharge_item.name = "sax_max_discharge_power"
        sax_data.get_modbus_items_for_battery.return_value = [
            charge_item,
            discharge_item,
        ]
        return sax_data

    @pytest.fixture
    def pilot_instance_main(
        self,
        mock_hass_pilot_instance,
        mock_sax_data_pilot_instance,
        mock_coordinator_pilot_instance,
    ) -> SAXBatteryPilot:
        """Create SAXBatteryPilot instance."""
        with patch("custom_components.sax_battery.pilot.async_track_time_interval"):
            pilot = SAXBatteryPilot(
                mock_hass_pilot_instance,
                mock_sax_data_pilot_instance,
                mock_coordinator_pilot_instance,
            )
            # Set real values for properties that would normally be set in __init__
            pilot.update_interval = 60
            pilot.calculated_power = 0.0
            pilot.max_discharge_power = 3600
            pilot.max_charge_power = 4500
            return pilot

    async def test_set_charge_power_limit_success(self, pilot_instance_main):
        """Test setting charge power limit successfully."""
        result = await pilot_instance_main.set_charge_power_limit(5000)

        assert result is True
        pilot_instance_main.coordinator.async_write_int_value.assert_called_once()

    async def test_set_charge_power_limit_no_item(self, pilot_instance_main):
        """Test setting charge power limit when item not found."""
        pilot_instance_main.sax_data.get_modbus_items_for_battery.return_value = []

        result = await pilot_instance_main.set_charge_power_limit(5000)

        assert result is False

    async def test_set_charge_power_limit_write_failure(self, pilot_instance_main):
        """Test setting charge power limit when write fails."""
        pilot_instance_main.coordinator.async_write_int_value.return_value = False

        result = await pilot_instance_main.set_charge_power_limit(5000)

        assert result is False

    async def test_set_discharge_power_limit_success(self, pilot_instance_main):
        """Test setting discharge power limit successfully."""
        result = await pilot_instance_main.set_discharge_power_limit(4000)

        assert result is True
        pilot_instance_main.coordinator.async_write_int_value.assert_called_once()

    async def test_set_discharge_power_limit_no_item(self, pilot_instance_main):
        """Test setting discharge power limit when item not found."""
        pilot_instance_main.sax_data.get_modbus_items_for_battery.return_value = []

        result = await pilot_instance_main.set_discharge_power_limit(4000)

        assert result is False

    async def test_set_discharge_power_limit_write_failure(self, pilot_instance_main):
        """Test setting discharge power limit when write fails."""
        pilot_instance_main.coordinator.async_write_int_value.return_value = False

        result = await pilot_instance_main.set_discharge_power_limit(4000)

        assert result is False

    def test_get_pilot_item_found(self, pilot_instance_main):
        """Test getting pilot item that exists."""
        # Find the solar charging item from PILOT_ITEMS
        solar_item = None
        for item in PILOT_ITEMS:
            if item.name == SOLAR_CHARGING_SWITCH:
                solar_item = item
                break

        result = pilot_instance_main._get_pilot_item(SOLAR_CHARGING_SWITCH)
        assert result == solar_item

    def test_get_pilot_item_not_found(self, pilot_instance_main):
        """Test getting pilot item that doesn't exist."""
        result = pilot_instance_main._get_pilot_item("non_existent_item")
        assert result is None

    def test_get_modbus_item_found(self, pilot_instance_main):
        """Test getting modbus item that exists."""
        mock_item = MagicMock()
        mock_item.name = "sax_max_charge_power"
        pilot_instance_main.sax_data.get_modbus_items_for_battery.return_value = [
            mock_item
        ]

        result = pilot_instance_main._get_modbus_item("sax_max_charge_power")
        assert result == mock_item

    def test_get_modbus_item_not_found(self, pilot_instance_main):
        """Test getting modbus item that doesn't exist."""
        pilot_instance_main.sax_data.get_modbus_items_for_battery.return_value = []

        result = pilot_instance_main._get_modbus_item("non_existent_item")
        assert result is None

    def test_manual_control_enabled_property(self, pilot_instance_main):
        """Test manual control enabled property."""
        pilot_instance_main.coordinator.data = {MANUAL_CONTROL_SWITCH: 1}
        assert pilot_instance_main.manual_control_enabled is True

        pilot_instance_main.coordinator.data = {MANUAL_CONTROL_SWITCH: 0}
        assert pilot_instance_main.manual_control_enabled is False

    def test_manual_control_enabled_property_no_success(self, pilot_instance_main):
        """Test manual control enabled property when coordinator has no success."""
        pilot_instance_main.coordinator.last_update_success = False
        assert pilot_instance_main.manual_control_enabled is None

    def test_current_charge_power_limit_property(self, pilot_instance_main):
        """Test current charge power limit property."""
        pilot_instance_main.coordinator.data = {"sax_max_charge_power": 5000}
        assert pilot_instance_main.current_charge_power_limit == 5000

    def test_current_charge_power_limit_property_no_success(self, pilot_instance_main):
        """Test current charge power limit property when coordinator has no success."""
        pilot_instance_main.coordinator.last_update_success = False
        assert pilot_instance_main.current_charge_power_limit is None

    def test_current_discharge_power_limit_property(self, pilot_instance_main):
        """Test current discharge power limit property."""
        pilot_instance_main.coordinator.data = {"sax_max_discharge_power": 4000}
        assert pilot_instance_main.current_discharge_power_limit == 4000

    def test_current_discharge_power_limit_property_no_success(
        self, pilot_instance_main
    ):
        """Test current discharge power limit property when coordinator has no success."""
        pilot_instance_main.coordinator.last_update_success = False
        assert pilot_instance_main.current_discharge_power_limit is None


class TestSAXBatterySolarChargingSwitch:
    """Test SAXBatterySolarChargingSwitch class."""

    @pytest.fixture
    def mock_pilot_solar_switch(self) -> MagicMock:
        """Create mock pilot."""
        pilot = MagicMock(spec=SAXBatteryPilot)
        pilot.set_solar_charging = AsyncMock(return_value=True)
        pilot.solar_charging_enabled = True
        pilot.manual_control_enabled = False
        pilot.calculated_power = 1500.0
        return pilot

    @pytest.fixture
    def mock_coordinator_solar_switch(self) -> MagicMock:
        """Create mock coordinator."""
        coordinator = MagicMock()
        coordinator.battery_id = "battery_a"
        coordinator.last_update_success = True
        coordinator.last_update_success_time = 1234567890.0
        coordinator.sax_data.get_device_info.return_value = {
            "identifiers": {("sax_battery", "battery_a")},
            "name": "SAX Battery A",
        }
        return coordinator

    @pytest.fixture
    def solar_charging_item_switch(self) -> SAXItem:
        """Create solar charging SAXItem."""
        for item in PILOT_ITEMS:
            if item.name == SOLAR_CHARGING_SWITCH:
                return item
        # Fallback if not found in PILOT_ITEMS
        return SAXItem(
            name=SOLAR_CHARGING_SWITCH,
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
        )

    @pytest.fixture
    def solar_switch_instance(
        self,
        mock_pilot_solar_switch,
        mock_coordinator_solar_switch,
        solar_charging_item_switch,
    ) -> SAXBatterySolarChargingSwitch:
        """Create SAXBatterySolarChargingSwitch instance."""
        return SAXBatterySolarChargingSwitch(
            mock_pilot_solar_switch,
            mock_coordinator_solar_switch,
            solar_charging_item_switch,
            "battery_a",
        )

    def test_extra_state_attributes(
        self,
        solar_switch_instance,
        mock_coordinator_solar_switch,
        mock_pilot_solar_switch,
    ):
        """Test extra state attributes."""
        attributes = solar_switch_instance.extra_state_attributes

        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        assert attributes["manual_control_enabled"] is False
        assert attributes["calculated_power"] == 1500.0
        assert attributes["last_updated"] == 1234567890.0

    def test_extra_state_attributes_no_success(
        self, solar_switch_instance, mock_coordinator_solar_switch
    ):
        """Test extra state attributes when coordinator has no success."""
        mock_coordinator_solar_switch.last_update_success = False

        attributes = solar_switch_instance.extra_state_attributes
        assert attributes is None

    def test_entity_properties(self, solar_switch_instance):
        """Test entity properties are set correctly."""
        assert "Battery A" in solar_switch_instance._attr_name
        assert solar_switch_instance._attr_icon == "mdi:solar-power"
        assert solar_switch_instance._attr_unique_id is not None


class TestSAXBatteryManualControlSwitch:
    """Test SAXBatteryManualControlSwitch class."""

    @pytest.fixture
    def mock_pilot_manual_switch(self) -> MagicMock:
        """Create mock pilot."""
        pilot = MagicMock(spec=SAXBatteryPilot)
        pilot.set_manual_control = AsyncMock(return_value=True)
        pilot.manual_control_enabled = True
        pilot.solar_charging_enabled = False
        pilot.current_charge_power_limit = 3500
        pilot.current_discharge_power_limit = 4600
        pilot.calculated_power = 2500.0  # Add calculated_power property
        return pilot

    @pytest.fixture
    def mock_coordinator_manual_switch(self) -> MagicMock:
        """Create mock coordinator."""
        coordinator = MagicMock()
        coordinator.battery_id = "battery_a"
        coordinator.last_update_success = True
        coordinator.last_update_success_time = 1234567890.0
        coordinator.sax_data.get_device_info.return_value = {
            "identifiers": {("sax_battery", "battery_a")},
            "name": "SAX Battery A",
        }
        return coordinator

    @pytest.fixture
    def manual_control_item_switch(self) -> SAXItem:
        """Create manual control SAXItem."""
        for item in PILOT_ITEMS:
            if item.name == MANUAL_CONTROL_SWITCH:
                return item
        # Fallback if not found in PILOT_ITEMS
        return SAXItem(
            name=MANUAL_CONTROL_SWITCH,
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
        )

    @pytest.fixture
    def manual_switch_instance(
        self,
        mock_pilot_manual_switch,
        mock_coordinator_manual_switch,
        manual_control_item_switch,
    ) -> SAXBatteryManualControlSwitch:
        """Create SAXBatteryManualControlSwitch instance."""
        return SAXBatteryManualControlSwitch(
            mock_pilot_manual_switch,
            mock_coordinator_manual_switch,
            manual_control_item_switch,
            "battery_a",
        )

    def test_is_on_property(self, manual_switch_instance, mock_pilot_manual_switch):
        """Test is_on property."""
        mock_pilot_manual_switch.manual_control_enabled = True
        assert manual_switch_instance.is_on is True

        mock_pilot_manual_switch.manual_control_enabled = False
        assert manual_switch_instance.is_on is False

        mock_pilot_manual_switch.manual_control_enabled = None
        assert manual_switch_instance.is_on is None

    def test_extra_state_attributes(
        self,
        manual_switch_instance,
        mock_coordinator_manual_switch,
        mock_pilot_manual_switch,
    ):
        """Test extra state attributes."""
        attributes = manual_switch_instance.extra_state_attributes

        assert attributes is not None
        assert attributes["battery_id"] == "battery_a"
        # assert attributes["solar_charging_enabled"] is False
        # assert attributes["manual_control_enabled"] is True
        assert attributes["charge_power_limit"] == 3500
        assert attributes["discharge_power_limit"] == 4600
        assert attributes["calculated_power"] == 2500.0
        assert attributes["last_updated"] == 1234567890.0

    def test_extra_state_attributes_no_success(
        self, manual_switch_instance, mock_coordinator_manual_switch
    ):
        """Test extra state attributes when coordinator has no success."""
        mock_coordinator_manual_switch.last_update_success = False

        attributes = manual_switch_instance.extra_state_attributes
        assert attributes is None

    def test_entity_properties(self, manual_switch_instance):
        """Test entity properties are set correctly."""
        assert "Battery A" in manual_switch_instance._attr_name
        # The actual icon from PILOT_ITEMS entity description is "mdi:hand", not "mdi:cog"
        assert manual_switch_instance._attr_icon == "mdi:hand"
        assert manual_switch_instance._attr_unique_id is not None
