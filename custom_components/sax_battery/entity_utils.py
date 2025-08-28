"""Utility functions for entity creation."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.config_entries import ConfigEntry

from .enums import TypeConstants
from .items import ModbusItem, SAXItem
from .utils import should_include_entity

_LOGGER = logging.getLogger(__name__)


def filter_items_by_type(
    items: list[ModbusItem],
    target_type: TypeConstants,
    config_entry: ConfigEntry,
    battery_id: str,
) -> list[ModbusItem]:
    """Filter items by type with proper entity description validation."""
    filtered_items = []

    for item in items:
        if item.mtype != target_type:
            continue

        # ✅ Validate entity description type matches platform
        if target_type == TypeConstants.NUMBER:
            if item.entitydescription and not isinstance(
                item.entitydescription, NumberEntityDescription
            ):
                _LOGGER.warning(
                    "Item %s has wrong entity description type for number platform: %s",
                    item.name,
                    type(item.entitydescription),
                )
                continue

        elif target_type == TypeConstants.SENSOR:
            if item.entitydescription and not isinstance(
                item.entitydescription, SensorEntityDescription
            ):
                _LOGGER.warning(
                    "Item %s has wrong entity description type for sensor platform: %s",
                    item.name,
                    type(item.entitydescription),
                )
                continue

        if should_include_entity(item, config_entry, battery_id):
            filtered_items.append(item)

    return filtered_items


def filter_sax_items_by_type(
    sax_items: list[SAXItem],
    item_type: TypeConstants,
) -> list[SAXItem]:
    """Filter SAXItem objects by type."""
    return [item for item in sax_items if item.mtype == item_type]
