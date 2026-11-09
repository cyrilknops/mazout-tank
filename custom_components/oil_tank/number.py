"""Flow rate number for the Heating Oil Tank integration."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OilTankConfigEntry
from .const import MAX_FLOW_RATE, MIN_FLOW_RATE
from .entity import OilTankEntity

FLOW = NumberEntityDescription(
    key="flow_rate",
    name="Burner flow rate",
    icon="mdi:fire",
    native_unit_of_measurement="L/h",
    native_min_value=MIN_FLOW_RATE,
    native_max_value=MAX_FLOW_RATE,
    native_step=0.01,
    mode=NumberMode.BOX,
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OilTankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FlowRateNumber(entry.runtime_data, FLOW)])


class FlowRateNumber(OilTankEntity, NumberEntity):
    @property
    def native_value(self) -> float:
        return self.tank.flow_rate

    async def async_set_native_value(self, value: float) -> None:
        self.tank.set_flow_rate(value)
