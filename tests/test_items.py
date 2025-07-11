"""Test items for SAX Battery integration."""

from __future__ import annotations

import pytest

from custom_components.sax_battery.enums import (
    DeviceConstants,
    FormatConstants,
    TypeConstants,
)
from custom_components.sax_battery.items import ModbusItem, SAXItem, StatusItem


class TestStatusItem:
    """Test StatusItem class."""

    def test_status_item_initialization(self) -> None:
        """Test StatusItem initialization."""
        item = StatusItem(
            number=1,
            text="Connected",
            translation_key="connected",
            description="Device is connected",
        )

        assert item.number == 1
        assert item.text == "Connected"

    def test_status_item_setters(self) -> None:
        """Test StatusItem property setters."""
        item = StatusItem(number=0, text="")

        item.number = 42
        item.text = "Test Status"

        assert item.number == 42
        assert item.text == "Test Status"


class TestModbusItem:
    """Test ModbusItem class."""

    def test_modbus_item_initialization(self) -> None:
        """Test ModbusItem initialization."""
        item = ModbusItem(
            slave=1,
            address=100,
            name="test_sensor",
            mformat=FormatConstants.NUMBER,
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SYS,
        )

        assert item.slave == 1
        assert item.address == 100
        assert item.name == "test_sensor"
        assert item.mformat == FormatConstants.NUMBER
        assert item.mtype == TypeConstants.SENSOR
        assert item.device == DeviceConstants.SYS

    def test_modbus_item_properties(self) -> None:
        """Test ModbusItem property setters."""
        item = ModbusItem(
            slave=1,
            address=100,
            name="test_switch",
            mformat=FormatConstants.STATUS,
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
        )

        # Test setters
        item.on_value = 1
        item.off_value = 0
        item.master_only = True
        item.required_features = ["feature_a", "feature_b"]

        assert item.on_value == 1
        assert item.off_value == 0
        assert item.master_only is True
        assert item.required_features == ["feature_a", "feature_b"]


class TestSAXItem:
    """Test SAXItem class."""

    def test_sax_item_initialization(self) -> None:
        """Test SAXItem initialization."""
        item = SAXItem(
            name="pilot_switch",
            mformat=FormatConstants.STATUS,
            mtype=TypeConstants.SWITCH,
            device=DeviceConstants.SYS,
        )

        assert item.name == "pilot_switch"
        assert item.mformat == FormatConstants.STATUS
        assert item.mtype == TypeConstants.SWITCH
        assert item.device == DeviceConstants.SYS
