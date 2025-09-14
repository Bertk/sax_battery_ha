"""Test switch platform for SAX Battery integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.sax_battery.const import DESCRIPTION_SAX_BATTERY_SWITCH, DOMAIN
from custom_components.sax_battery.coordinator import SAXBatteryCoordinator
from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem
from custom_components.sax_battery.switch import SAXBatterySwitch, async_setup_entry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import async_generate_entity_id


class TestSAXBatterySwitch:
    """Test SAX Battery switch entity."""

    @pytest.fixture
    def mock_coordinator_switch(self) -> MagicMock:
        """Create mock coordinator for switch tests."""
        coordinator = MagicMock()
        coordinator.data = {"test_switch": 1}
        coordinator.last_update_success = True
        coordinator.async_write_switch_value = AsyncMock(return_value=True)
        coordinator.async_request_refresh = AsyncMock()

        # Mock sax_data and device info
        mock_sax_data = MagicMock()
        mock_sax_data.get_device_info.return_value = {
            "identifiers": {("sax_battery", "battery_1")},
            "name": "SAX Battery 1",
            "manufacturer": "SAX Power",
            "model": "Battery System",
        }
        coordinator.sax_data = mock_sax_data

        return coordinator

    @pytest.fixture
    def modbus_item_switch(self) -> ModbusItem:
        """Create a test modbus item for switch."""
        return ModbusItem(
            name="test_switch",
            device=DeviceConstants.SYS,
            mtype=TypeConstants.SWITCH,
            address=1000,  # Use valid Modbus address instead of 0
            battery_slave_id=1,
            factor=1.0,
            entitydescription=DESCRIPTION_SAX_BATTERY_SWITCH,
        )

    @pytest.fixture
    def mock_config_entry_switch(self):
        """Create mock config entry for switch tests."""
        config_entry = MagicMock()
        config_entry.entry_id = "test_entry_switch"
        config_entry.data = {
            "host": "192.168.1.100",
            "port": 502,
            "batteries": {"battery_a": {"role": "master"}},
        }
        config_entry.options = {}
        return config_entry

    @pytest.fixture
    def mock_sax_data_switch(self):
        """Create mock SAX data for switch tests."""
        return MagicMock()

    async def test_async_setup_entry_with_entity_id_generation(
        self, hass: HomeAssistant, mock_config_entry_switch, mock_sax_data_switch
    ) -> None:
        """Test setup entry with proper entity_id generation."""

        # Mock coordinator
        mock_coordinator = MagicMock(spec=SAXBatteryCoordinator)
        mock_coordinator.hass = hass  # Ensure hass is available

        # Create test entities with entity_id generation
        entities_created = []

        def mock_add_entities(new_entities, update_before_add=False):
            # Apply entity_id generation as Home Assistant would
            for entity in new_entities:
                if hasattr(entity, "_attr_unique_id"):
                    entity.entity_id = async_generate_entity_id(
                        f"{entity.domain}.{{}}", entity._attr_unique_id, hass=hass
                    )
            entities_created.extend(new_entities)

        # Store data and run setup
        hass.data[DOMAIN] = {
            mock_config_entry_switch.entry_id: {
                "coordinators": {"battery_a": mock_coordinator},
                "sax_data": mock_sax_data_switch,
            }
        }

        await async_setup_entry(hass, mock_config_entry_switch, mock_add_entities)

        # Verify entities have proper entity_ids
        for entity in entities_created:
            assert hasattr(entity, "entity_id")
            assert entity.entity_id.startswith(f"{entity.domain}.")

    def test_switch_initialization(
        self, mock_coordinator_switch, modbus_item_switch
    ) -> None:
        """Test switch entity initialization."""
        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        assert switch.unique_id == "sax_battery_1_test_switch"
        assert switch.name == "On/Off"

        assert switch._battery_id == "battery_1"
        assert switch._modbus_item == modbus_item_switch

    def test_switch_is_on_true(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test switch is_on returns True when value matches on_value."""
        mock_coordinator_switch.data = {"test_switch": 1}

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        assert switch.is_on is True

    def test_switch_is_on_false(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test switch is_on returns False when value matches off_value."""
        mock_coordinator_switch.data = {"test_switch": 0}

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        assert switch.is_on is False

    async def test_switch_turn_on_success(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test successful turn_on operation."""
        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        await switch.async_turn_on()

        mock_coordinator_switch.async_write_switch_value.assert_called_once_with(
            modbus_item_switch, True
        )
        mock_coordinator_switch.async_request_refresh.assert_called_once()

    async def test_switch_turn_on_failure(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test turn_on operation failure."""
        mock_coordinator_switch.async_write_switch_value.return_value = False

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        with pytest.raises(HomeAssistantError, match="Failed to turn on On/Off"):
            await switch.async_turn_on()

    def test_switch_extra_state_attributes(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test extra state attributes."""
        # Set the address to match expected value
        modbus_item_switch.address = 1000

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        attrs = switch.extra_state_attributes

        # Fixed: Handle None return value properly
        assert attrs is not None
        assert attrs["battery_id"] == "battery_1"
        assert attrs["modbus_address"] == 1000
        assert "last_update" in attrs
        assert "raw_value" in attrs

    def test_switch_unavailable_coordinator(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test switch behavior when coordinator is unavailable."""
        mock_coordinator_switch.last_update_success = False

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        assert switch.available is False

    def test_switch_no_data(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test switch behavior when coordinator has no data."""
        mock_coordinator_switch.data = None

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        assert switch.is_on is None
        assert switch.available is False

    def test_switch_missing_data_key(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test switch behavior when data key is missing."""
        mock_coordinator_switch.data = {"other_switch": 1}

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        assert switch.is_on is None
        assert switch.available is False

    def test_switch_string_values(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test switch with string values."""
        test_cases = [
            ("on", True),
            ("off", False),
            ("true", True),
            ("false", False),
            ("1", True),
            ("0", False),
            ("yes", True),
            ("no", False),
            ("ON", True),
            ("OFF", False),
        ]

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        for string_value, expected_bool in test_cases:
            mock_coordinator_switch.data = {"test_switch": string_value}
            assert switch.is_on is expected_bool, f"Failed for '{string_value}'"

    async def test_switch_turn_off_success(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test successful turn_off operation."""
        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        await switch.async_turn_off()

        mock_coordinator_switch.async_write_switch_value.assert_called_once_with(
            modbus_item_switch, False
        )
        mock_coordinator_switch.async_request_refresh.assert_called_once()

    async def test_switch_turn_off_failure(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test turn_off operation failure."""
        mock_coordinator_switch.async_write_switch_value.return_value = False

        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        with pytest.raises(HomeAssistantError, match="Failed to turn off On/Off"):
            await switch.async_turn_off()

    def test_switch_device_info(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test device info property."""
        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        device_info = switch.device_info

        # Handle the case where device_info might be None
        assert device_info is not None
        assert device_info["identifiers"] == {("sax_battery", "battery_1")}
        assert device_info["name"] == "SAX Battery 1"
        assert device_info["manufacturer"] == "SAX Power"

    def test_switch_icon_property(
        self, mock_coordinator_switch: MagicMock, modbus_item_switch: ModbusItem
    ) -> None:
        """Test icon property."""
        switch = SAXBatterySwitch(
            coordinator=mock_coordinator_switch,
            battery_id="battery_1",
            modbus_item=modbus_item_switch,
        )

        # The implementation returns None for icon, meaning it uses the default
        # Home Assistant switch icon behavior
        assert switch.icon == "mdi:battery"
