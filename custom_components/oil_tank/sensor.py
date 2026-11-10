"""Sensors for the Heating Oil Tank integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfLength,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OilTankConfigEntry
from .entity import OilTankEntity
from .tank import OilTank


@dataclass(frozen=True, kw_only=True)
class OilTankSensorDescription(SensorEntityDescription):
    value_fn: Callable[[OilTank], float | None]


SENSORS: tuple[OilTankSensorDescription, ...] = (
    OilTankSensorDescription(
        key="level",
        name="Level",
        icon="mdi:storage-tank",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda t: t.level,
    ),
    OilTankSensorDescription(
        key="level_percent",
        name="Level percent",
        icon="mdi:gauge",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda t: t.percent,
    ),
    OilTankSensorDescription(
        key="level_height",
        name="Gauge height",
        icon="mdi:arrow-expand-vertical",
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda t: t.height_cm,
    ),
    OilTankSensorDescription(
        key="used_today",
        name="Used today",
        icon="mdi:water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda t: t.used_today,
    ),
    OilTankSensorDescription(
        key="used_month",
        name="Used this month",
        icon="mdi:water",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        value_fn=lambda t: t.used_month,
    ),
    OilTankSensorDescription(
        key="average_per_day",
        name="Average use per day",
        icon="mdi:chart-line",
        native_unit_of_measurement="L/d",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda t: t.avg_per_day,
    ),
    OilTankSensorDescription(
        key="days_remaining",
        name="Days remaining",
        icon="mdi:calendar-clock",
        native_unit_of_measurement=UnitOfTime.DAYS,
        suggested_display_precision=0,
        value_fn=lambda t: t.days_remaining,
    ),
    OilTankSensorDescription(
        key="cost_today",
        name="Cost today",
        icon="mdi:currency-eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda t: t.cost_today,
    ),
    OilTankSensorDescription(
        key="cost_month",
        name="Cost this month",
        icon="mdi:currency-eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda t: t.cost_month,
    ),
    OilTankSensorDescription(
        key="tank_value",
        name="Tank value",
        icon="mdi:cash",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=0,
        value_fn=lambda t: t.tank_value,
    ),
    OilTankSensorDescription(
        key="consumption",
        name="Consumption",
        icon="mdi:fire",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda t: t.total_liters,
    ),
    OilTankSensorDescription(
        key="total_cost",
        name="Total cost",
        icon="mdi:currency-eur",
        native_unit_of_measurement="EUR",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda t: t.total_cost,
    ),
    OilTankSensorDescription(
        key="oil_price",
        name="Oil price",
        icon="mdi:cash-multiple",
        native_unit_of_measurement="EUR/L",
        suggested_display_precision=3,
        value_fn=lambda t: t.price,
    ),
    OilTankSensorDescription(
        key="runtime_since_reference",
        name="Burner time since reference",
        icon="mdi:timer-outline",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=1,
        value_fn=lambda t: t.runtime_since_reference,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OilTankConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    tank = entry.runtime_data
    async_add_entities(OilTankSensor(tank, d) for d in SENSORS)


class OilTankSensor(OilTankEntity, SensorEntity):
    entity_description: OilTankSensorDescription

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self.tank)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key == "oil_price":
            t = self.tank
            return {
                "batches": [
                    {"liters": round(b["liters"], 1), "price": b.get("price"), "date": b.get("date")}
                    for b in t.data.get("batches", [])
                ],
                "deliveries": t.data.get("deliveries", []),
                "unpriced_liters": t.unpriced_liters,
                "last_paid_price": t.last_paid_price,
            }
        if self.entity_description.key != "level":
            return None
        t = self.tank
        d = t.data
        # The tank card reads these attributes
        return {
            "oil_tank": True,
            "config_entry_id": t.entry.entry_id,
            "capacity": t.capacity,
            "liters_per_cm": t.liters_per_cm,
            "low_alert": t.low_alert,
            "percent": t.percent,
            "height_cm": t.height_cm,
            "flow_rate": t.flow_rate,
            "used_today": t.used_today,
            "average_per_day": t.avg_per_day,
            "days_remaining": t.days_remaining,
            "reference_level": d.get("ref_level"),
            "reference_runtime_min": d.get("ref_runtime"),
            "waiting_for_counter": t.pending,
            "source_available": t.source_available,
            "source_entity": t.runtime_entity,
        }
