"""Constants for the Heating Oil Tank integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "oil_tank"
VERSION: Final = "2026.11.9"

CONF_RUNTIME_ENTITY: Final = "runtime_entity"
CONF_PRICE_ENTITY: Final = "price_entity"
CONF_CAPACITY: Final = "capacity"
CONF_LITERS_PER_CM: Final = "liters_per_cm"
CONF_FLOW_RATE: Final = "flow_rate"
CONF_LOW_ALERT: Final = "low_alert"
CONF_INITIAL_CM: Final = "initial_gauge_cm"

DEFAULT_NAME: Final = "Gasoil tank"
DEFAULT_CAPACITY: Final = 4000.0
DEFAULT_LITERS_PER_CM: Final = 28.6
DEFAULT_FLOW_RATE: Final = 3.0
DEFAULT_LOW_ALERT: Final = 500.0

MIN_FLOW_RATE: Final = 0.5
MAX_FLOW_RATE: Final = 15.0

# Calibration needs enough data to give a useful result
CALIBRATE_MIN_HOURS: Final = 20.0
CALIBRATE_MIN_LITERS: Final = 50.0

# Daily snapshots kept for the 7-day average
HISTORY_DAYS: Final = 8

SERVICE_ADD_DELIVERY: Final = "add_delivery"
SERVICE_SET_LEVEL: Final = "set_level"
SERVICE_CALIBRATE_FLOW: Final = "calibrate_flow"

ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_LITERS: Final = "liters"
ATTR_GAUGE_CM: Final = "gauge_cm"

CARD_URL: Final = f"/{DOMAIN}/oil-tank-card.js"
