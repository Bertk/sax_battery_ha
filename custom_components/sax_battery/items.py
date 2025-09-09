"""Items module for SAX Battery integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
from typing import Any

from pymodbus.client.mixin import ModbusClientMixin
from pymodbus.exceptions import ModbusException

from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.switch import SwitchEntityDescription

# Import from entity_keys instead of const to break circular import
from .entity_keys import SAX_ENERGY_CONSUMED, SAX_ENERGY_PRODUCED, SAX_SOC
from .enums import DeviceConstants, TypeConstants

_LOGGER = logging.getLogger(__name__)


@dataclass
class BaseItem(ABC):
    """Base class for all SAX Battery data items.

    Supports multiple data sources: Modbus, Web API, calculated values.
    Future extensions can add WebAPIItem, BluetoothItem, etc.
    """

    name: str
    mtype: TypeConstants
    device: DeviceConstants
    translation_key: str = ""
    entitydescription: (
        SensorEntityDescription
        | NumberEntityDescription
        | SwitchEntityDescription
        | None
    ) = None

    # State management
    _state: Any = field(default=None, init=False)
    _is_invalid: bool = field(default=False, init=False)

    @property
    def state(self) -> Any:
        """Get the current state."""
        return self._state

    @state.setter
    def state(self, value: Any) -> None:
        """Set the current state."""
        self._state = value

    @property
    def is_invalid(self) -> bool:
        """Check if the item is invalid."""
        return self._is_invalid

    @is_invalid.setter
    def is_invalid(self, value: bool) -> None:
        """Set the invalid state."""
        self._is_invalid = value

    @abstractmethod
    async def async_read_value(self) -> int | float | bool | None:
        """Read value from data source."""

    @abstractmethod
    async def async_write_value(self, value: float) -> bool:
        """Write value to data source."""

    def validate_value(self, value: Any) -> int | float | bool | None:
        """Validate a value for this item."""
        if self.is_invalid or value is None:
            return None

        # Convert and validate based on type
        try:
            if self.mtype in (
                TypeConstants.SENSOR,
                TypeConstants.NUMBER,
                TypeConstants.NUMBER_RO,
            ):
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    return float(value)
                return None
            elif self.mtype in (TypeConstants.SWITCH,):  # noqa: RET505
                if isinstance(value, bool):
                    return value
                if isinstance(value, (int, str)):
                    return bool(int(value))
                return None
            else:
                # For other types, return as-is if numeric or bool
                if isinstance(value, (int, float, bool)):
                    return value
                return None
        except (ValueError, TypeError):
            return None


@dataclass
class ModbusItem(BaseItem):
    """Modbus-specific item with physical register communication."""

    address: int = 0
    battery_slave_id: int = 1
    data_type: ModbusClientMixin.DATATYPE = ModbusClientMixin.DATATYPE.INT16
    factor: float = 1.0
    offset: int = 0
    _modbus_api: Any = field(default=None, init=False)  # Will be set via set_api()

    def set_api(self, modbus_api: Any) -> None:
        """Set the ModbusAPI instance for this item."""
        self._modbus_api = modbus_api

    async def async_read_value(self) -> int | float | bool | None:
        """Read value from physical modbus register."""
        if self.is_invalid:
            return None

        # Check if this type supports reading using TypeConstants
        if self.mtype == TypeConstants.NUMBER_WO:
            _LOGGER.debug("Skipping read for write-only item %s", self.name)
            return None

        if self._modbus_api is None:
            _LOGGER.error("ModbusAPI not set for item %s", self.name)
            return None

        try:
            result = await self._modbus_api.read_holding_registers(
                count=1, modbus_item=self
            )
            # Ensure we return the correct type
            if isinstance(result, (int, float, bool)):
                return result
            else:  # noqa: RET505
                # Convert other types appropriately
                return float(result) if isinstance(result, (int, float)) else None
        except ModbusException:
            _LOGGER.exception("Failed to read value for %s", self.name)
            return None

    async def async_write_value(self, value: float) -> bool:
        """Write value to physical modbus register."""
        # Check if this type supports writing using TypeConstants
        if self.mtype in (
            TypeConstants.SENSOR,
            TypeConstants.NUMBER_RO,
            TypeConstants.SENSOR_CALC,
        ):
            _LOGGER.warning("Attempted to write to read-only item %s", self.name)
            return False

        if self._modbus_api is None:
            _LOGGER.error("ModbusAPI not set for item %s", self.name)
            return False

        try:
            result = await self._modbus_api.write_registers(
                value=value, modbus_item=self
            )
            return bool(result) if result is not None else False
        except ModbusException:
            _LOGGER.exception("Failed to write value for %s", self.name)
            return False

    def get_switch_on_value(self) -> int:
        """Get the value to write for switch on state."""
        return 2

    def get_switch_off_value(self) -> int:
        """Get the value to write for switch off state."""
        return 1

    def is_writable(self) -> bool:
        """Check if this item can be written to (legacy compatibility)."""
        return self.mtype not in (
            TypeConstants.SENSOR,
            TypeConstants.NUMBER_RO,
            TypeConstants.SENSOR_CALC,
        )


@dataclass
class SAXItem(BaseItem):
    """System-level calculated/aggregated item without physical communication.

    SAXItem represents calculated values across multiple batteries or system-wide
    configuration that doesn't correspond to a single physical register.
    """

    description: str = ""
    default_value: Any = None
    is_system_entity: bool = True
    _coordinators: dict[str, Any] = field(default_factory=dict, init=False)

    def set_coordinators(self, coordinators: dict[str, Any]) -> None:
        """Set coordinators for multi-battery calculations."""
        self._coordinators = coordinators

    async def async_read_value(self) -> int | float | bool | None:
        """Calculate system-wide value from multiple battery coordinators."""
        return self.calculate_value(self._coordinators)

    async def async_write_value(self, value: float) -> bool:
        """Write system configuration value."""
        # Check if this type supports writing using TypeConstants
        if self.mtype not in (TypeConstants.NUMBER, TypeConstants.NUMBER_WO):
            _LOGGER.warning("Attempted to write to read-only SAX item %s", self.name)
            return False

        # System configuration writes are handled through config entry updates
        # This will be implemented based on specific SAX item requirements
        _LOGGER.debug("SAX item write not yet implemented for %s", self.name)
        return False

    def calculate_value(self, coordinators: dict[str, Any]) -> float | int | None:
        """Calculate system-wide value from multiple battery coordinators."""
        try:
            if self.name == "sax_combined_soc":
                return self._calculate_combined_soc(coordinators)
            if self.name == "sax_cumulative_energy_produced":
                return self._calculate_cumulative_energy_produced(coordinators)
            if self.name == "sax_cumulative_energy_consumed":
                return self._calculate_cumulative_energy_consumed(coordinators)
            # Default: return None for unknown calculation types
            _LOGGER.warning("Unknown calculation type for SAXItem: %s", self.name)
            return None  # noqa: TRY300
        except (ValueError, TypeError, KeyError) as exc:
            _LOGGER.error("Error calculating value for %s: %s", self.name, exc)
            return None

    # Calculation functions for SAXItem values
    def _calculate_combined_soc(
        self,
        coordinators: dict[str, Any],
    ) -> float | None:
        """Calculate combined SOC across all batteries."""
        total_soc = 0.0
        count = 0

        for coordinator in coordinators.values():
            if coordinator.data and SAX_SOC in coordinator.data:
                soc_value = coordinator.data[SAX_SOC]
                if soc_value is not None:
                    total_soc += float(soc_value)
                    count += 1

        return total_soc / count if count > 0 else None

    def _calculate_cumulative_energy_produced(
        self,
        coordinators: dict[str, Any],
    ) -> float | None:
        """Calculate cumulative energy produced across all batteries."""
        total_energy = 0.0
        count = 0

        for coordinator in coordinators.values():
            if coordinator.data and SAX_ENERGY_PRODUCED in coordinator.data:
                energy_value = coordinator.data[SAX_ENERGY_PRODUCED]
                if energy_value is not None:
                    total_energy += float(energy_value)
                    count += 1

        return total_energy if count > 0 else None

    def _calculate_cumulative_energy_consumed(
        self,
        coordinators: dict[str, Any],
    ) -> float | None:
        """Calculate cumulative energy consumed across all batteries."""
        total_energy = 0.0
        count = 0

        for coordinator in coordinators.values():
            if coordinator.data and SAX_ENERGY_CONSUMED in coordinator.data:
                energy_value = coordinator.data[SAX_ENERGY_CONSUMED]
                if energy_value is not None:
                    total_energy += float(energy_value)
                    count += 1

        return total_energy if count > 0 else None


# Future extension example for Web API items
@dataclass
class WebAPIItem(BaseItem):
    """Web API-based item for SAX Power web application data.

    Future implementation for data not available via Modbus:
    - Detailed battery analytics
    - Historical performance data
    - Advanced configuration options
    - Remote diagnostics
    """

    api_endpoint: str = ""
    api_key: str = ""
    refresh_interval: int = 300  # 5 minutes default
    _web_api_client: Any = field(default=None, init=False)

    def set_api_client(self, web_api_client: Any) -> None:
        """Set the Web API client for this item."""
        self._web_api_client = web_api_client

    async def async_read_value(self) -> int | float | bool | None:
        """Read value from SAX Power Web API."""
        if self.is_invalid:
            return None

        # Future implementation
        _LOGGER.debug("Web API read not yet implemented for %s", self.name)
        return None

    async def async_write_value(self, value: float) -> bool:
        """Write value via SAX Power Web API."""
        # Check if this type supports writing using TypeConstants
        if self.mtype not in (
            TypeConstants.NUMBER,
            TypeConstants.NUMBER_WO,
            TypeConstants.SWITCH,
        ):
            return False

        if self.is_invalid:
            return False

        # Future implementation
        _LOGGER.debug("Web API write not yet implemented for %s", self.name)
        return False


# Helper functions for type checking using TypeConstants directly
def is_sensor_item(item: ModbusItem | SAXItem | WebAPIItem) -> bool:
    """Check if item is a sensor type."""
    return item.mtype in (TypeConstants.SENSOR, TypeConstants.SENSOR_CALC)


def is_number_item(item: ModbusItem | SAXItem | WebAPIItem) -> bool:
    """Check if item is a number type."""
    return item.mtype in (
        TypeConstants.NUMBER,
        TypeConstants.NUMBER_WO,
        TypeConstants.NUMBER_RO,
    )


def is_switch_item(item: ModbusItem | SAXItem | WebAPIItem) -> bool:
    """Check if item is a switch type."""
    return item.mtype == TypeConstants.SWITCH


def is_readonly_item(item: ModbusItem | SAXItem | WebAPIItem) -> bool:
    """Check if item is read-only using TypeConstants."""
    return item.mtype in (
        TypeConstants.SENSOR,
        TypeConstants.NUMBER_RO,
        TypeConstants.SENSOR_CALC,
    )


def is_writeonly_item(item: ModbusItem | SAXItem | WebAPIItem) -> bool:
    """Check if item is write-only using TypeConstants."""
    return item.mtype == TypeConstants.NUMBER_WO


def is_readable_item(item: ModbusItem | SAXItem | WebAPIItem) -> bool:
    """Check if item supports reading using TypeConstants."""
    return item.mtype != TypeConstants.NUMBER_WO


def is_writable_item(item: ModbusItem | SAXItem | WebAPIItem) -> bool:
    """Check if item supports writing using TypeConstants."""
    return item.mtype not in (
        TypeConstants.SENSOR,
        TypeConstants.NUMBER_RO,
        TypeConstants.SENSOR_CALC,
    )


def get_item_category(item: ModbusItem | SAXItem | WebAPIItem) -> str:
    """Get item category for grouping purposes."""
    if isinstance(item, ModbusItem):
        return "modbus"
    if isinstance(item, SAXItem):
        return "system"
    if isinstance(item, WebAPIItem):
        return "webapi"
    return "unknown"  # type:ignore[unreachable]
