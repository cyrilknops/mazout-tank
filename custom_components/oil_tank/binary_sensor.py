"""Binary sensors for the Heating Oil Tank integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OilTankConfigEntry
from .entity import OilTankEntity

LOW = BinarySensorEntityDescription(
    key="low", name="Low level", device_class=BinarySensorDeviceClass.PROBLEM
)
SOURCE = BinarySensorEntityDescription(
    key="source",
    name="Burner counter",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OilTankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    tank = entry.runtime_data
    async_add_entities([LowLevelSensor(tank, LOW), SourceSensor(tank, SOURCE)])


class LowLevelSensor(OilTankEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool:
        return self.tank.is_low


class SourceSensor(OilTankEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool:
        return self.tank.source_available
