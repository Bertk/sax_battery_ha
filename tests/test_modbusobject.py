"""Test modbusobject.py functionality."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

from pymodbus import ModbusException
from pymodbus.client.mixin import ModbusClientMixin

from custom_components.sax_battery.enums import DeviceConstants, TypeConstants
from custom_components.sax_battery.items import ModbusItem
from custom_components.sax_battery.modbusobject import ModbusAPI


class TestModbusAPI:
    """Test ModbusAPI connection and register operations."""

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_connect_success(self, mock_client_class):
        """Test successful connection."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=True)
        mock_client.connect.return_value = True
        mock_client_class.return_value = mock_client

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        result = await api.connect()
        assert result is True

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_connect_failure(self, mock_client_class):
        """Test connection failure."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=False)
        mock_client.connect.return_value = False
        mock_client.close.return_value = None
        mock_client_class.return_value = mock_client

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        result = await api.connect()
        assert result is False
        assert api._connect_pending is False
        mock_client.close.assert_called_once()

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_connect_exception(self, mock_client_class):
        """Test ModbusException during connect."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=False)
        mock_client.connect.side_effect = ModbusException("fail")
        mock_client.close.return_value = None
        mock_client_class.return_value = mock_client

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        result = await api.connect()
        assert result is False
        mock_client.close.assert_called_once()

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    def test_close_success(self, mock_client_class):
        """Test successful close."""
        mock_client = MagicMock()
        mock_client.close.return_value = None
        mock_client_class.return_value = mock_client

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        # Set the client manually since we're not calling connect
        api._modbus_client = mock_client
        assert api.close() is True
        mock_client.close.assert_called_once()

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    def test_close_exception(self, mock_client_class):
        """Test ModbusException during close."""
        mock_client = MagicMock()
        mock_client.close.side_effect = ModbusException("fail")
        mock_client_class.return_value = mock_client

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        # Set the client manually since we're not calling connect
        api._modbus_client = mock_client
        assert api.close() is False

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_write_registers_success(self, mock_client_class):
        """Test successful write_registers."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=True)
        mock_result = MagicMock()
        mock_result.isError.return_value = False
        mock_client.write_registers.return_value = mock_result
        mock_client_class.return_value = mock_client

        # Create a proper ModbusItem
        modbus_item = ModbusItem(
            name="test_item",
            mtype=TypeConstants.NUMBER_WO,
            device=DeviceConstants.SYS,
            address=123,
            factor=1.0,
            offset=0,
            battery_slave_id=1,
        )

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        # Set the client manually since we're not calling connect
        api._modbus_client = mock_client
        result = await api.write_registers(value=10, modbus_item=modbus_item)

        assert result is True

        # Verify the correct method was called with expected parameters
        # The actual implementation converts value based on factor/offset
        mock_client.write_registers.assert_called_once_with(
            address=123,
            values=[1],  # 10 / factor (10.0) = 1, corrected expectation
            device_id=1,
        )

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_write_registers_error(self, mock_client_class):
        """Test write_registers with error response."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=True)
        mock_result = MagicMock()
        mock_result.isError.return_value = True
        mock_client.write_registers.return_value = mock_result
        mock_client_class.return_value = mock_client

        modbus_item = ModbusItem(
            name="test_item",
            mtype=TypeConstants.NUMBER,
            device=DeviceConstants.SYS,
            address=123,
            factor=1.0,
        )

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        # Set the client manually since we're not calling connect
        api._modbus_client = mock_client
        result = await api.write_registers(value=10, modbus_item=modbus_item)
        assert result is False

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_write_registers_exception(self, mock_client_class):
        """Test ModbusException during write_registers."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=True)
        mock_client.write_registers.side_effect = ModbusException("fail")
        mock_client_class.return_value = mock_client

        modbus_item = ModbusItem(
            name="test_item",
            mtype=TypeConstants.NUMBER,
            device=DeviceConstants.SYS,
            address=123,
            factor=1.0,
        )

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        # Set the client manually since we're not calling connect
        api._modbus_client = mock_client
        result = await api.write_registers(value=10, modbus_item=modbus_item)
        assert result is False

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_read_holding_registers_success(self, mock_client_class):
        """Test successful read_holding_registers."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=True)
        mock_result = MagicMock()
        mock_result.isError.return_value = False
        mock_result.registers = [1500]
        mock_client.read_holding_registers.return_value = mock_result
        mock_client.convert_from_registers.return_value = [1500]
        mock_client_class.return_value = mock_client

        modbus_item = ModbusItem(
            name="test_item",
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SYS,
            address=10,
            data_type=ModbusClientMixin.DATATYPE.INT16,
        )

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        # Set the client manually since we're not calling connect
        api._modbus_client = mock_client
        result = await api.read_holding_registers(count=1, modbus_item=modbus_item)
        assert result == 1500

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_read_holding_registers_error(self, mock_client_class):
        """Test read_holding_registers with error response."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=True)
        mock_result = MagicMock()
        mock_result.isError.return_value = True
        mock_client.read_holding_registers.return_value = mock_result
        mock_client_class.return_value = mock_client

        modbus_item = ModbusItem(
            name="test_item",
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SYS,
            address=10,
        )

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        # Set the client manually since we're not calling connect
        api._modbus_client = mock_client
        result = await api.read_holding_registers(count=1, modbus_item=modbus_item)
        assert result is None

    @patch("custom_components.sax_battery.modbusobject.ModbusTcpClient")
    async def test_read_holding_registers_exception(self, mock_client_class):
        """Test ModbusException during read_holding_registers."""
        mock_client = MagicMock()
        type(mock_client).connected = PropertyMock(return_value=True)
        mock_client.read_holding_registers.side_effect = ModbusException("fail")
        mock_client_class.return_value = mock_client

        modbus_item = ModbusItem(
            name="test_item",
            mtype=TypeConstants.SENSOR,
            device=DeviceConstants.SYS,
            address=10,
        )

        api = ModbusAPI(host="127.0.0.1", port=502, battery_id="bat")
        # Set the client manually since we're not calling connect
        api._modbus_client = mock_client
        result = await api.read_holding_registers(count=1, modbus_item=modbus_item)
        assert result is None
