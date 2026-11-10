"""Tests for the Heating Oil Tank integration."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.oil_tank.const import DOMAIN

SRC = "sensor.brennerlaufzeit_1"
PRICE = "sensor.oil_price"
DATA = {
    "name": "Gasoil tank",
    "runtime_entity": SRC,
    "price_entity": PRICE,
    "capacity": 4000.0,
    "liters_per_cm": 28.6,
    "low_alert": 500.0,
    "flow_rate": 3.0,
    "initial_gauge_cm": 48.0,
}
LEVEL = "sensor.gasoil_tank_level"


@pytest.fixture(autouse=True)
def auto_enable(enable_custom_integrations):
    yield


def _runtime(hass, minutes, unit="min"):
    hass.states.async_set(SRC, str(minutes), {"unit_of_measurement": unit})


async def _setup(hass, data=DATA):
    entry = MockConfigEntry(domain=DOMAIN, data=data, title=data["name"], unique_id=data["runtime_entity"])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _f(hass, eid):
    return float(hass.states.get(eid).state)


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    bad = {**DATA, "initial_gauge_cm": 200.0}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], bad)
    assert result["errors"] == {"initial_gauge_cm": "above_capacity"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DATA)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Gasoil tank"


async def test_level_from_runtime(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    hass.states.async_set(PRICE, "1.4139")
    _runtime(hass, 733268)
    await _setup(hass)
    assert _f(hass, LEVEL) == pytest.approx(1372.8)
    assert hass.states.get(LEVEL).attributes["waiting_for_counter"] is False
    assert _f(hass, "sensor.gasoil_tank_gauge_height") == pytest.approx(48.0)

    # 100 h of burner time at 3 L/h = 300 L
    freezer.tick(timedelta(hours=101))
    _runtime(hass, 733268 + 6000)
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(1072.8)
    assert _f(hass, "sensor.gasoil_tank_tank_value") == pytest.approx(1072.8 * 1.4139, abs=1)


async def test_offline_and_zero_do_not_change_level(hass: HomeAssistant, freezer) -> None:
    _runtime(hass, 733268)
    await _setup(hass)
    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 600)  # 10 h -> 30 L
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(1342.8)

    # ESP restart: unavailable, then 0, then the real value again
    hass.states.async_set(SRC, "unavailable")
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(1342.8)
    _runtime(hass, 0)
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(1342.8)
    _runtime(hass, 733268 + 600)
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(1342.8)
    assert hass.states.get("binary_sensor.gasoil_tank_burner_counter").state == "on"


async def test_glitch_jump_ignored(hass: HomeAssistant, freezer) -> None:
    _runtime(hass, 733268)
    await _setup(hass)
    freezer.tick(timedelta(minutes=10))
    _runtime(hass, 999999)  # impossible jump in 10 min
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(1372.8)


async def test_pending_until_counter_online(hass: HomeAssistant) -> None:
    hass.states.async_set(SRC, "unavailable")
    await _setup(hass)
    assert _f(hass, LEVEL) == pytest.approx(1372.8)
    assert hass.states.get(LEVEL).attributes["waiting_for_counter"] is True
    _runtime(hass, 733268)
    await hass.async_block_till_done()
    assert hass.states.get(LEVEL).attributes["waiting_for_counter"] is False
    assert _f(hass, LEVEL) == pytest.approx(1372.8)


async def test_actions_and_calibration(hass: HomeAssistant, freezer) -> None:
    _runtime(hass, 733268)
    await _setup(hass)

    await hass.services.async_call(DOMAIN, "add_delivery", {"liters": 1000}, blocking=True)
    assert _f(hass, LEVEL) == pytest.approx(2372.8)

    await hass.services.async_call(DOMAIN, "set_level", {"gauge_cm": 48}, blocking=True)
    assert _f(hass, LEVEL) == pytest.approx(1372.8)

    # Too early to calibrate
    res = await hass.services.async_call(
        DOMAIN, "calibrate_flow", {"gauge_cm": 47}, blocking=True, return_response=True
    )
    assert res["calibrated"] is False

    # 100 h later the gauge shows 38 cm: 1372.8 - 1086.8 = 286 L in 100 h = 2.86 L/h
    freezer.tick(timedelta(hours=101))
    _runtime(hass, 733268 + 6000)
    await hass.async_block_till_done()
    res = await hass.services.async_call(
        DOMAIN, "calibrate_flow", {"gauge_cm": 38}, blocking=True, return_response=True
    )
    assert res["calibrated"] is True
    assert res["flow_rate"] == pytest.approx(2.86, abs=0.01)
    assert _f(hass, "number.gasoil_tank_burner_flow_rate") == pytest.approx(2.86, abs=0.01)
    assert _f(hass, LEVEL) == pytest.approx(1086.8)


async def test_flow_change_keeps_level(hass: HomeAssistant, freezer) -> None:
    _runtime(hass, 733268)
    await _setup(hass)
    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 600)
    await hass.async_block_till_done()
    before = _f(hass, LEVEL)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.gasoil_tank_burner_flow_rate", "value": 2.0}, blocking=True
    )
    assert _f(hass, LEVEL) == pytest.approx(before)


async def test_low_level_and_counter_reset(hass: HomeAssistant, freezer) -> None:
    _runtime(hass, 1000)
    await _setup(hass, {**DATA, "initial_gauge_cm": 20.0})  # 572 L
    assert hass.states.get("binary_sensor.gasoil_tank_low_level").state == "off"
    freezer.tick(timedelta(hours=30))
    _runtime(hass, 1000 + 1800)  # 30 h * 3 = 90 L -> 482 L
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.gasoil_tank_low_level").state == "on"
    # New controller: counter starts low again, level must stay
    _runtime(hass, 50)
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(482.0)


async def test_hours_unit_and_restart_persistence(hass: HomeAssistant, freezer) -> None:
    _runtime(hass, 12221.1, unit="h")
    entry = await _setup(hass)
    freezer.tick(timedelta(hours=11))
    _runtime(hass, 12231.1, unit="h")  # 10 h -> 30 L
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(1342.8)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _f(hass, LEVEL) == pytest.approx(1342.8)


async def test_daily_use_and_average(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-09 12:00:00+00:00")
    _runtime(hass, 733268)
    await _setup(hass)
    for day in range(1, 4):
        freezer.move_to(f"2026-11-{9 + day:02d} 12:00:00+00:00")
        _runtime(hass, 733268 + day * 180)  # 3 h per day = 9 L
        await hass.async_block_till_done()
    assert _f(hass, "sensor.gasoil_tank_average_use_per_day") == pytest.approx(9.0, abs=0.1)
    freezer.move_to("2026-11-12 18:00:00+00:00")
    _runtime(hass, 733268 + 3 * 180 + 60)
    await hass.async_block_till_done()
    assert _f(hass, "sensor.gasoil_tank_used_today") == pytest.approx(3.0)
    days = _f(hass, "sensor.gasoil_tank_days_remaining")
    assert days > 50


async def test_energy_totals(hass: HomeAssistant, freezer) -> None:
    hass.states.async_set(PRICE, "1.40")
    _runtime(hass, 733268)
    await _setup(hass)
    cons = "sensor.gasoil_tank_consumption"
    cost = "sensor.gasoil_tank_total_cost"
    assert _f(hass, cons) == 0
    attrs = hass.states.get(cons).attributes
    assert attrs["device_class"] == "gas" and attrs["state_class"] == "total_increasing"
    assert attrs["unit_of_measurement"] == "L"

    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 600)  # 10 h * 3 L/h = 30 L at 1.40
    await hass.async_block_till_done()
    assert _f(hass, cons) == pytest.approx(30.0)
    assert _f(hass, cost) == pytest.approx(42.0)

    # Price changes: new liters use the new price
    hass.states.async_set(PRICE, "1.00")
    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 1200)
    await hass.async_block_till_done()
    assert _f(hass, cons) == pytest.approx(60.0)
    assert _f(hass, cost) == pytest.approx(72.0)

    # A delivery or a gauge correction does not change the totals
    await hass.services.async_call(DOMAIN, "add_delivery", {"liters": 500}, blocking=True)
    assert _f(hass, cons) == pytest.approx(60.0)

    # Offline and 0 do not add anything
    hass.states.async_set(SRC, "unavailable")
    await hass.async_block_till_done()
    _runtime(hass, 0)
    await hass.async_block_till_done()
    _runtime(hass, 733268 + 1200)
    await hass.async_block_till_done()
    assert _f(hass, cons) == pytest.approx(60.0)


async def test_card_registered_as_resource(hass: HomeAssistant) -> None:
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    _runtime(hass, 733268)
    await _setup(hass)
    res = hass.data[LOVELACE_DATA].resources
    mine = [r for r in res.async_items() if r["url"].startswith("/oil_tank/oil-tank-card.js?v=")]
    assert len(mine) == 1 and mine[0]["type"] == "module"


NOPRICE = {k: v for k, v in DATA.items() if k != "price_entity"}
TOTAL = "sensor.gasoil_tank_total_cost"
OILPRICE = "sensor.gasoil_tank_oil_price"


async def test_price_per_delivery(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-02 01:00:00+00:00")
    _runtime(hass, 733268)
    await _setup(hass, NOPRICE)
    # 1372.8 L in the tank, price unknown
    assert hass.states.get(OILPRICE).state == "unknown"

    # 30 L burned with an unknown price: no cost yet
    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 600)
    await hass.async_block_till_done()
    assert _f(hass, TOTAL) == 0
    assert hass.states.get(OILPRICE).attributes["unpriced_liters"] == pytest.approx(30.0)

    # Delivery with the invoice total: 1000 L for 1100 EUR = 1.10 EUR/L.
    # The old oil and the 30 L burned without a price get the new price.
    await hass.services.async_call(DOMAIN, "add_delivery", {"liters": 1000, "total_price": 1100}, blocking=True)
    assert _f(hass, TOTAL) == pytest.approx(33.0)
    assert _f(hass, OILPRICE) == pytest.approx(1.10)
    assert hass.states.get(OILPRICE).attributes["unpriced_liters"] == 0

    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 1200)  # 30 L more at 1.10
    await hass.async_block_till_done()
    assert _f(hass, TOTAL) == pytest.approx(66.0)
    assert _f(hass, "sensor.gasoil_tank_cost_this_month") == pytest.approx(66.0)

    # A second delivery at another price: the old oil burns first
    await hass.services.async_call(DOMAIN, "add_delivery", {"liters": 500, "price_per_liter": 1.5}, blocking=True)
    assert _f(hass, OILPRICE) == pytest.approx(1.10)
    # (1372.8 - 60 + 1000) * 1.10 + 500 * 1.50
    assert _f(hass, "sensor.gasoil_tank_tank_value") == pytest.approx(3294.08, abs=0.05)
    deliveries = hass.states.get(OILPRICE).attributes["deliveries"]
    assert [x["price"] for x in deliveries] == [1.1, 1.5]
    assert deliveries[0]["total"] == pytest.approx(1100.0)


async def test_fifo_across_batches_and_corrections(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-02 01:00:00+00:00")
    _runtime(hass, 733268)
    await _setup(hass, NOPRICE)
    await hass.services.async_call(DOMAIN, "add_delivery", {"liters": 1000, "price_per_liter": 1.0}, blocking=True)
    # Gauge correction down to 30 L: the oldest oil goes first, no cost
    await hass.services.async_call(DOMAIN, "set_level", {"liters": 30}, blocking=True)
    assert _f(hass, TOTAL) == 0
    await hass.services.async_call(DOMAIN, "add_delivery", {"liters": 100, "price_per_liter": 2.0}, blocking=True)

    # 60 L burned: 30 L at 1.00 and 30 L at 2.00
    freezer.tick(timedelta(hours=21))
    _runtime(hass, 733268 + 1200)
    await hass.async_block_till_done()
    assert _f(hass, TOTAL) == pytest.approx(90.0)
    assert _f(hass, OILPRICE) == pytest.approx(2.0)
    batches = hass.states.get(OILPRICE).attributes["batches"]
    assert [(b["liters"], b["price"]) for b in batches] == [(70.0, 2.0)]

    # Gauge correction up: no cost, the batches follow the level
    await hass.services.async_call(DOMAIN, "set_level", {"liters": 100}, blocking=True)
    assert _f(hass, TOTAL) == pytest.approx(90.0)
    assert sum(b["liters"] for b in hass.states.get(OILPRICE).attributes["batches"]) == pytest.approx(100.0)


async def test_price_sensor_is_only_a_fallback(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-02 01:00:00+00:00")
    hass.states.async_set(PRICE, "1.40")
    _runtime(hass, 733268)
    await _setup(hass)
    # Old oil uses the sensor price until a delivery gives a real price
    assert _f(hass, OILPRICE) == pytest.approx(1.40)
    await hass.services.async_call(DOMAIN, "add_delivery", {"liters": 500, "price_per_liter": 1.2}, blocking=True)
    hass.states.async_set(PRICE, "9.99")
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 600)
    await hass.async_block_till_done()
    # The old oil was given the delivery price; the sensor price is not used
    assert _f(hass, TOTAL) == pytest.approx(36.0)


async def test_default_price_from_settings(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-11-02 01:00:00+00:00")
    _runtime(hass, 733268)
    entry = await _setup(hass, NOPRICE)
    # 30 L burned with an unknown price
    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 600)
    await hass.async_block_till_done()
    assert _f(hass, TOTAL) == 0

    # Set a default price in the settings: the unpriced liters are booked at it
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "default_price" in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"runtime_entity": SRC, "default_price": 1.2, "capacity": 4000.0, "liters_per_cm": 28.6, "low_alert": 500.0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert _f(hass, TOTAL) == pytest.approx(36.0)
    assert _f(hass, OILPRICE) == pytest.approx(1.2)
    assert hass.states.get(OILPRICE).attributes["unpriced_liters"] == 0

    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 1200)  # 30 L more at the default price
    await hass.async_block_till_done()
    assert _f(hass, TOTAL) == pytest.approx(72.0)

    # A delivery with a price replaces the default price for the old oil
    await hass.services.async_call(DOMAIN, "add_delivery", {"liters": 500, "price_per_liter": 1.5}, blocking=True)
    freezer.tick(timedelta(hours=11))
    _runtime(hass, 733268 + 1800)
    await hass.async_block_till_done()
    assert _f(hass, TOTAL) == pytest.approx(117.0)
