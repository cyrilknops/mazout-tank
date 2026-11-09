"""Base entity for the Heating Oil Tank integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN, VERSION
from .tank import OilTank


class OilTankEntity(Entity):
    """Entity that follows the tank model."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, tank: OilTank, description: EntityDescription) -> None:
        self.tank = tank
        self.entity_description = description
        self._attr_unique_id = f"{tank.entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tank.entry.entry_id)},
            name=tank.entry.title,
            manufacturer="IWG-IT",
            model="Heating oil tank",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.tank.add_listener(self.async_write_ha_state))
