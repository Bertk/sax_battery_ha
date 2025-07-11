"""Item definitions for SAX Battery integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.const import EntityCategory

from .enums import DeviceConstants, FormatConstants, TypeConstants


@dataclass
class StatusItem:
    """Status item for result list mapping."""

    value: int
    text: str


@dataclass
class ModbusItem:
    """Modbus item definition."""

    slave: int
    address: int
    name: str
    mformat: FormatConstants  # Modbus-specific format for data adaptation
    mtype: TypeConstants
    device: DeviceConstants
    description: str = ""
    translation_key: str = ""
    resultlist: list[StatusItem] | None = None
    params: dict[str, Any] = field(default_factory=dict)
    divider: int = 1
    on_value: int = 1
    off_value: int = 0
    master_only: bool = False
    required_features: list[str] = field(default_factory=list)
    category: EntityCategory | str | None = None
    icon: str | None = None
    unit: str | None = None
    precision: int | None = None
    is_invalid: bool = False

    @property
    def format(self) -> FormatConstants:
        """Return Modbus format constant for compatibility."""
        return self.mformat

    @property
    def type(self) -> TypeConstants:
        """Return type constant for compatibility."""
        return self.mtype

    def get_text_from_number(self, value: int | None) -> str | None:
        """Get text representation from numeric value."""
        if value is None or not self.resultlist:
            return None

        for item in self.resultlist:
            if item.value == value:
                return item.text

        return f"unbekannt <{value}>"

    def get_number_from_text(self, text: str | None) -> int | None:
        """Get numeric value from text representation."""
        if text is None or not self.resultlist:
            return None

        for item in self.resultlist:
            if item.text == text:
                return item.value

        return None


@dataclass
class SAXItem:
    """SAX item definition for pilot functionality."""

    name: str
    mformat: FormatConstants  # modbus format -> not home assistant formats
    mtype: TypeConstants  # modbus type -> not home assistant type
    device: DeviceConstants
    description: str = ""
    translation_key: str = ""
    icon: str | None = None
    category: EntityCategory | str | None = None
    unit: str | None = None
    on_value: int = 1
    off_value: int = 0
    master_only: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    required_features: list[str] = field(default_factory=list)
    _last_update: float = 0.0
    _update_interval: int = 60  # SAX items update every minute

    @property
    def format(self) -> FormatConstants:
        """Return format constant for compatibility."""
        return self.mformat

    @property
    def type(self) -> TypeConstants:
        """Return type constant for compatibility."""
        return self.mtype

    @property
    def last_update(self) -> float:
        """Return timestamp of last update."""
        return self._last_update

    @property
    def update_interval(self) -> int:
        """Return update interval in seconds."""
        return self._update_interval

    def mark_updated(self) -> None:
        """Mark item as recently updated."""
        import time

        self._last_update = time.time()

    def needs_update(self) -> bool:
        """Check if item needs updating based on interval."""
        import time

        return (time.time() - self._last_update) >= self._update_interval
