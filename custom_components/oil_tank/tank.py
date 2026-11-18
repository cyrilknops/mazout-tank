"""Tank model: calculates the oil level from the burner runtime counter.

The level is calculated from ONE reference point:

    level = reference level - (runtime now - reference runtime) / 60 * flow rate

Nothing is added up over time, so restarts, an offline ESP or a missing
value cannot make the level drift. The reference point is stored on disk.

Cost: the oil in the tank is kept as batches (one per delivery, oldest first),
each with the price paid per liter. Burned oil comes from the oldest batch
(first in, first out), so the cost uses the price that was really paid.
Oil with an unknown price (for example oil that was in the tank before the
first delivery with a price) gets the price of the next delivery with a price.

Flow rate: every gauge reading is stored with the burner counter at that time.
The liters really used between two readings are

    previous reading + liters delivered in between - this reading

The flow rate (L/h) is the slope of a straight line through all readings:
liters used against burner hours. With two readings this is simply liters / hours.
More readings make the result better; one wrong reading has little effect, and
it can be deleted. A counter reset or a refill that was not entered starts a new
series: the slope is fitted per series, with one common flow rate.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CALIBRATE_MIN_HOURS,
    CALIBRATE_MIN_LITERS,
    CONF_CAPACITY,
    CONF_DEFAULT_PRICE,
    CONF_FLOW_RATE,
    CONF_INITIAL_CM,
    CONF_LITERS_PER_CM,
    CONF_LOW_ALERT,
    CONF_PRICE_ENTITY,
    CONF_RUNTIME_ENTITY,
    DEFAULT_CAPACITY,
    DEFAULT_FLOW_RATE,
    DEFAULT_LITERS_PER_CM,
    DEFAULT_LOW_ALERT,
    DOMAIN,
    HISTORY_DAYS,
    MAX_FLOW_RATE,
    MIN_FLOW_RATE,
    READING_MERGE_HOURS,
    READING_PERIOD_MIN_HOURS,
    READING_REFILL_LITERS,
    READINGS_KEEP,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# A counter cannot run faster than the clock. Allow a small margin.
GLITCH_MARGIN_MIN = 5.0
# Batches smaller than this are empty (rounding of the level)
BATCH_EPS = 0.05
# Deliveries kept in the history attribute
DELIVERY_HISTORY = 20


class OilTank:
    """State and calculations for one oil tank."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self.data: dict[str, Any] = {}
        self.source_available = False

    # ------------------------------------------------------------------ config
    @property
    def _cfg(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def runtime_entity(self) -> str:
        return self._cfg[CONF_RUNTIME_ENTITY]

    @property
    def price_entity(self) -> str | None:
        return self._cfg.get(CONF_PRICE_ENTITY) or None

    @property
    def capacity(self) -> float:
        return float(self._cfg.get(CONF_CAPACITY, DEFAULT_CAPACITY))

    @property
    def liters_per_cm(self) -> float:
        return float(self._cfg.get(CONF_LITERS_PER_CM, DEFAULT_LITERS_PER_CM))

    @property
    def low_alert(self) -> float:
        return float(self._cfg.get(CONF_LOW_ALERT, DEFAULT_LOW_ALERT))

    @property
    def flow_rate(self) -> float:
        return float(self.data.get("flow_rate", DEFAULT_FLOW_RATE))

    # --------------------------------------------------------------- lifecycle
    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored is None:
            cm = float(self._cfg.get(CONF_INITIAL_CM, 0))
            stored = {
                "ref_level": self._clamp(cm * self.liters_per_cm),
                "ref_runtime": None,
                "pending": True,
                "flow_rate": float(self._cfg.get(CONF_FLOW_RATE, DEFAULT_FLOW_RATE)),
                "last_runtime": None,
                "last_update": None,
                "day": None,
                "day_start": None,
                "month": None,
                "month_start": None,
                "history": [],
                "low_notified": False,
                # The gauge reading from the setup is the first calibration point
                "readings": [_reading(1, self._clamp(cm * self.liters_per_cm), cm, None, 0.0, 0)],
            }
        # Cumulative totals for the Energy dashboard (added in 1.1.0)
        stored.setdefault("total_liters", 0.0)
        stored.setdefault("total_cost", 0.0)
        # Price per delivery (added in 2026.11.10)
        stored.setdefault("unpriced_liters", 0.0)
        stored.setdefault("deliveries", [])
        # Gauge readings for the flow calibration (added in 2026.11.18).
        # The current reference point is the first reading: the gauge reading or
        # delivery it came from. Delete it in the card if it was not a real reading.
        if "readings" not in stored:
            ref_ok = not stored.get("pending") and stored.get("ref_runtime") is not None
            stored["readings"] = (
                [_reading(1, stored["ref_level"], None, stored["ref_runtime"], 0.0, 0, note="reference")]
                if ref_ok
                else []
            )
        stored.setdefault("epoch", 0)
        stored.setdefault("delivered_since_reading", 0.0)
        self.data = stored
        if "batches" not in stored:
            # The oil that is in the tank now: price unknown until the next delivery with a price
            level = self.level
            stored["batches"] = [{"liters": level, "price": None, "date": None}] if level > BATCH_EPS else []
        # Liters burned before a price was known: book them at the fallback price
        fallback = self.fallback_price
        if fallback is not None and stored["unpriced_liters"] > 0:
            stored["total_cost"] += stored["unpriced_liters"] * fallback
            stored["unpriced_liters"] = 0.0

        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.runtime_entity], self._handle_runtime_event
            )
        )
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._handle_midnight, hour=0, minute=0, second=5
            )
        )
        if self.price_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.price_entity], self._handle_price_event
                )
            )
        self._process_state(self.hass.states.get(self.runtime_entity))
        self._save()

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self.data)

    @callback
    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)

        def _remove() -> None:
            self._listeners.remove(update)

        return _remove

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(lambda: self.data, 5)

    # ----------------------------------------------------------------- source
    @staticmethod
    def _read_minutes(state: State | None) -> float | None:
        """Return the runtime counter in minutes, or None if not valid."""
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        # The KM271 publishes 0 for a short time after a restart
        if value <= 0:
            return None
        unit = state.attributes.get("unit_of_measurement")
        if unit == "h":
            value *= 60
        elif unit == "s":
            value /= 60
        elif unit == "d":
            value *= 1440
        return value

    @callback
    def _handle_runtime_event(self, event: Event[EventStateChangedData]) -> None:
        self._process_state(event.data["new_state"])

    @callback
    def _handle_price_event(self, event: Event[EventStateChangedData]) -> None:
        self._notify()

    @callback
    def _handle_midnight(self, _now) -> None:
        if self.data.get("last_runtime") is not None:
            self._roll_periods(self.data["last_runtime"])
            self._save()
        self._notify()

    @callback
    def _process_state(self, state: State | None) -> None:
        runtime = self._read_minutes(state)
        self.source_available = runtime is not None
        if runtime is None:
            self._notify()
            return

        d = self.data
        now = dt_util.utcnow().timestamp()
        last = d.get("last_runtime")

        if last is not None and runtime > last and d.get("last_update"):
            elapsed_min = (now - d["last_update"]) / 60
            if runtime - last > elapsed_min + GLITCH_MARGIN_MIN:
                _LOGGER.warning(
                    "Ignored runtime jump from %s to %s min in %.1f min",
                    last, runtime, elapsed_min,
                )
                return

        if last is not None and runtime > last:
            # Add only real burner time. Values are never subtracted, so the
            # totals always go up (Energy dashboard requirement).
            liters = self._liters_for_minutes(runtime - last)
            d["total_liters"] = d.get("total_liters", 0.0) + liters
            d["total_cost"] = d.get("total_cost", 0.0) + self._take(liters, book=True)

        if d["pending"] or d["ref_runtime"] is None:
            d["ref_runtime"] = runtime
            d["pending"] = False
        elif runtime < d["ref_runtime"] or (last is not None and runtime < last):
            # Counter was reset (new controller or reset). Keep the level.
            _LOGGER.warning("Runtime counter went down (%s -> %s); new reference", last, runtime)
            d["ref_level"] = self.level
            d["ref_runtime"] = runtime
            d["day_start"] = runtime
            d["month_start"] = runtime
            d["history"] = []
            # Readings before and after a reset cannot be compared: new series
            d["epoch"] = d.get("epoch", 0) + 1

        # A gauge reading taken while the counter was offline gets this counter value
        readings = d.get("readings") or []
        if readings and readings[-1].get("runtime") is None:
            readings[-1]["runtime"] = runtime
            readings[-1]["epoch"] = d.get("epoch", 0)

        d["last_runtime"] = runtime
        d["last_update"] = now
        self._roll_periods(runtime)
        self._reconcile()
        self._check_low()
        self._save()
        self._notify()

    @callback
    def _roll_periods(self, runtime: float) -> None:
        d = self.data
        now = dt_util.now()
        today = now.date().isoformat()
        month = now.strftime("%Y-%m")
        if d.get("day") != today:
            d["day"] = today
            d["day_start"] = runtime
            d["day_cost_start"] = d.get("total_cost", 0.0)
            d["history"] = [*d.get("history", []), [now.timestamp(), runtime]][-HISTORY_DAYS:]
        if d.get("month") != month:
            d["month"] = month
            d["month_start"] = runtime
            d["month_cost_start"] = d.get("total_cost", 0.0)

    # ----------------------------------------------------------- calculations
    def _clamp(self, liters: float) -> float:
        return round(max(0.0, min(liters, self.capacity)), 1)

    def _liters_for_minutes(self, minutes: float) -> float:
        return max(minutes, 0.0) / 60 * self.flow_rate

    @property
    def pending(self) -> bool:
        return bool(self.data.get("pending"))

    @property
    def level(self) -> float:
        d = self.data
        if d["pending"] or d["ref_runtime"] is None or d["last_runtime"] is None:
            return self._clamp(d["ref_level"])
        used = self._liters_for_minutes(d["last_runtime"] - d["ref_runtime"])
        return self._clamp(d["ref_level"] - used)

    @property
    def percent(self) -> float:
        return round(self.level / self.capacity * 100, 1) if self.capacity else 0.0

    @property
    def height_cm(self) -> float:
        return round(self.level / self.liters_per_cm, 1) if self.liters_per_cm else 0.0

    @property
    def used_today(self) -> float | None:
        d = self.data
        if d.get("day_start") is None or d.get("last_runtime") is None:
            return None
        return round(self._liters_for_minutes(d["last_runtime"] - d["day_start"]), 1)

    @property
    def used_month(self) -> float | None:
        d = self.data
        if d.get("month_start") is None or d.get("last_runtime") is None:
            return None
        return round(self._liters_for_minutes(d["last_runtime"] - d["month_start"]), 1)

    @property
    def runtime_since_reference(self) -> float | None:
        d = self.data
        if d["pending"] or d["ref_runtime"] is None or d["last_runtime"] is None:
            return None
        return round((d["last_runtime"] - d["ref_runtime"]) / 60, 1)

    @property
    def avg_per_day(self) -> float | None:
        d = self.data
        history = d.get("history") or []
        if not history or d.get("last_runtime") is None:
            return None
        ts0, rt0 = history[0]
        days = (dt_util.utcnow().timestamp() - ts0) / 86400
        if days < 1:
            return None
        return round(self._liters_for_minutes(d["last_runtime"] - rt0) / days, 1)

    @property
    def days_remaining(self) -> float | None:
        avg = self.avg_per_day
        if avg is None or avg < 0.1:
            return None
        return round(max(self.level - self.low_alert, 0) / avg)

    # ----------------------------------------------------------------- prices
    @property
    def entity_price(self) -> float | None:
        """Price from the optional price sensor (only a fallback)."""
        if not self.price_entity:
            return None
        state = self.hass.states.get(self.price_entity)
        try:
            return float(state.state) if state else None
        except ValueError:
            return None

    @property
    def default_price(self) -> float | None:
        """Price from the settings, for oil without a known price."""
        value = self._cfg.get(CONF_DEFAULT_PRICE)
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @property
    def fallback_price(self) -> float | None:
        """Price for oil without a delivery price: price sensor, then default price."""
        price = self.entity_price
        return price if price is not None else self.default_price

    @property
    def last_paid_price(self) -> float | None:
        """Price per liter of the newest delivery with a price."""
        for delivery in reversed(self.data.get("deliveries", [])):
            if delivery.get("price") is not None:
                return float(delivery["price"])
        return None

    def _batch_price(self, batch: dict[str, Any]) -> float | None:
        if batch.get("price") is not None:
            return float(batch["price"])
        return self.fallback_price

    @property
    def price(self) -> float | None:
        """Price per liter of the oil that burns now (the oldest batch)."""
        for batch in self.data.get("batches", []):
            if batch["liters"] > BATCH_EPS:
                price = self._batch_price(batch)
                if price is not None:
                    return price
                break
        return self.last_paid_price if self.last_paid_price is not None else self.fallback_price

    def cost(self, liters: float | None) -> float | None:
        price = self.price
        if price is None or liters is None:
            return None
        return round(liters * price, 2)

    def _period_cost(self, key: str, liters: float | None) -> float | None:
        start = self.data.get(key)
        if start is None:
            # Data from before 2026.11.10: estimate until the next day or month
            return self.cost(liters)
        return round(max(self.data.get("total_cost", 0.0) - start, 0.0), 2)

    @property
    def cost_today(self) -> float | None:
        return self._period_cost("day_cost_start", self.used_today)

    @property
    def cost_month(self) -> float | None:
        return self._period_cost("month_cost_start", self.used_month)

    @property
    def tank_value(self) -> float | None:
        total = 0.0
        for batch in self.data.get("batches", []):
            price = self._batch_price(batch)
            if price is None:
                price = self.price
            if price is None:
                return None
            total += batch["liters"] * price
        return round(total, 2)

    @property
    def unpriced_liters(self) -> float:
        """Burned liters with an unknown price, booked at the next priced delivery."""
        return round(self.data.get("unpriced_liters", 0.0), 1)

    # ---------------------------------------------------------------- batches
    @callback
    def _take(self, liters: float, book: bool) -> float:
        """Take liters from the oldest batches. Return the known cost if book."""
        d = self.data
        left = max(liters, 0.0)
        cost = 0.0
        batches = d.setdefault("batches", [])
        for batch in batches:
            if left <= 0:
                break
            take = min(batch["liters"], left)
            if take <= 0:
                continue
            if book:
                price = self._batch_price(batch)
                if price is None:
                    d["unpriced_liters"] = d.get("unpriced_liters", 0.0) + take
                else:
                    cost += take * price
            batch["liters"] -= take
            left -= take
        if left > 0 and book:
            # More burned than the batches hold (level rounding): newest known price
            price = self.price
            if price is None:
                d["unpriced_liters"] = d.get("unpriced_liters", 0.0) + left
            else:
                cost += left * price
        d["batches"] = [b for b in batches if b["liters"] > BATCH_EPS]
        return cost

    @callback
    def _reconcile(self) -> None:
        """Make the batches hold exactly the calculated level (gauge corrections)."""
        d = self.data
        batches = d.setdefault("batches", [])
        total = sum(b["liters"] for b in batches)
        level = self.level
        if total > level + BATCH_EPS:
            self._take(total - level, book=False)
        elif level > total + BATCH_EPS:
            if batches:
                batches[-1]["liters"] += level - total
            else:
                batches.append({"liters": level - total, "price": self.last_paid_price, "date": None})

    @property
    def total_liters(self) -> float:
        return round(self.data.get("total_liters", 0.0), 3)

    @property
    def total_cost(self) -> float:
        return round(self.data.get("total_cost", 0.0), 2)

    @property
    def is_low(self) -> bool:
        return self.level < self.low_alert

    @callback
    def _check_low(self) -> None:
        d = self.data
        if self.is_low and not d.get("low_notified"):
            d["low_notified"] = True
            persistent_notification.async_create(
                self.hass,
                f"{self.entry.title}: approximately {self.level:.0f} L "
                f"({self.height_cm:.0f} cm) left. Order oil.",
                title="Heating oil low",
                notification_id=f"{DOMAIN}_{self.entry.entry_id}_low",
            )
        elif not self.is_low and d.get("low_notified"):
            d["low_notified"] = False

    # ---------------------------------------------------------------- actions
    @callback
    def set_level(self, liters: float) -> None:
        """Set a new reference level. The counter value is stored now or
        when the source sends its next valid value."""
        d = self.data
        d["ref_level"] = self._clamp(liters)
        if self.source_available and d.get("last_runtime") is not None:
            d["ref_runtime"] = d["last_runtime"]
            d["pending"] = False
        else:
            d["pending"] = True
        self._reconcile()
        self._check_low()
        self._save()
        self._notify()

    @callback
    def add_delivery(
        self,
        liters: float,
        price_per_liter: float | None = None,
        total_price: float | None = None,
    ) -> None:
        """Add delivered oil, with the price paid (per liter or in total)."""
        d = self.data
        price = price_per_liter
        if price is None and total_price is not None and liters > 0:
            price = total_price / liters
        paid = price is not None
        if price is None:
            price = self.fallback_price
        if price is not None:
            price = round(float(price), 4)
            # Oil with an unknown price gets the new price
            for batch in d.setdefault("batches", []):
                if batch.get("price") is None:
                    batch["price"] = price
            if d.get("unpriced_liters"):
                d["total_cost"] = d.get("total_cost", 0.0) + d["unpriced_liters"] * price
                d["unpriced_liters"] = 0.0
        today = dt_util.now().date().isoformat()
        d["delivered_since_reading"] = d.get("delivered_since_reading", 0.0) + float(liters)
        d["batches"].append({"liters": float(liters), "price": price, "date": today})
        d["deliveries"] = [
            *d.get("deliveries", []),
            {
                "date": today,
                "liters": round(float(liters), 1),
                "price": price if paid else None,
                "total": round(float(liters) * price, 2) if paid and price is not None else None,
            },
        ][-DELIVERY_HISTORY:]
        self.set_level(self.level + liters)

    @callback
    def set_flow_rate(self, flow: float) -> None:
        """Change the flow rate. The current level stays the same."""
        current = self.level
        self.data["flow_rate"] = round(max(MIN_FLOW_RATE, min(flow, MAX_FLOW_RATE)), 3)
        self.set_level(current)

    # ------------------------------------------------------------ calibration
    @callback
    def add_reading(self, liters: float, gauge_cm: float | None = None) -> dict[str, Any]:
        """Store a gauge reading, set the level from it and recalculate the flow rate."""
        d = self.data
        liters = self._clamp(liters)
        readings: list[dict[str, Any]] = d.setdefault("readings", [])
        runtime = d.get("last_runtime") if self.source_available else None
        epoch = d.get("epoch", 0)
        delivered = d.get("delivered_since_reading", 0.0)
        note = None
        prev = readings[-1] if readings else None
        if (
            prev is not None
            and runtime is not None
            and prev.get("runtime") is not None
            and prev.get("epoch") == epoch
            and runtime - prev["runtime"] < READING_MERGE_HOURS * 60
        ):
            # A correction of the previous reading (no real burner time in between)
            readings.pop()
            delivered += prev.get("delivered", 0.0)
            note = "correction"
            prev = readings[-1] if readings else None
        if (
            prev is not None
            and prev.get("runtime") is not None
            and prev.get("epoch") == epoch
            and prev["liters"] + delivered - liters < -READING_REFILL_LITERS
        ):
            # The level went up without a delivery: a refill that was not entered
            epoch += 1
            d["epoch"] = epoch
            note = "refill without delivery"
        next_id = max((r["id"] for r in readings), default=0) + 1
        readings.append(_reading(next_id, liters, gauge_cm, runtime, delivered, epoch, note=note))
        d["readings"] = readings[-READINGS_KEEP:]
        d["delivered_since_reading"] = 0.0

        result = self._apply_fit()
        self.set_level(liters)
        result["reading_id"] = next_id
        prefix = f"Level set to {liters:.0f} L. "
        result["message"] = prefix + result["message"]
        return result

    @callback
    def delete_reading(self, reading_id: int) -> dict[str, Any]:
        """Delete a wrong gauge reading and recalculate the flow rate."""
        d = self.data
        readings: list[dict[str, Any]] = d.get("readings") or []
        idx = next((i for i, r in enumerate(readings) if r["id"] == reading_id), None)
        if idx is None:
            return {"deleted": False, "calibrated": False, "message": f"Reading {reading_id} not found."}
        removed = readings.pop(idx)
        if removed.get("note") == "refill without delivery":
            # This reading started a new series; without it the series join again
            back = readings[idx - 1]["epoch"] if idx > 0 else removed["epoch"]
            for r in readings[idx:]:
                if r.get("epoch") == removed["epoch"]:
                    r["epoch"] = back
            if d.get("epoch") == removed["epoch"]:
                d["epoch"] = back
        # The liters delivered before the deleted reading belong to the next period
        if idx < len(readings):
            readings[idx]["delivered"] = readings[idx].get("delivered", 0.0) + removed.get("delivered", 0.0)
        else:
            d["delivered_since_reading"] = d.get("delivered_since_reading", 0.0) + removed.get("delivered", 0.0)
        result = self._apply_fit(keep_level=True)
        result["deleted"] = True
        result["message"] = f"Reading of {removed.get('date') or 'the reference'} deleted. " + result["message"]
        self._save()
        self._notify()
        return result

    @callback
    def calibrate_flow(self, liters_now: float, gauge_cm: float | None = None) -> dict[str, Any]:
        """Older action name: the same as a gauge reading."""
        return self.add_reading(liters_now, gauge_cm)

    def _series(self) -> list[list[tuple[float, float]]]:
        """Points (burner hours, liters used) per series, counted from the first reading of the series."""
        groups: dict[int, list[dict[str, Any]]] = {}
        for r in self.data.get("readings") or []:
            if r.get("runtime") is not None:
                groups.setdefault(r.get("epoch", 0), []).append(r)
        out: list[list[tuple[float, float]]] = []
        for rs in groups.values():
            if len(rs) < 2:
                continue
            pts = [(0.0, 0.0)]
            used = 0.0
            for prev, cur in zip(rs, rs[1:]):
                used += prev["liters"] + cur.get("delivered", 0.0) - cur["liters"]
                pts.append(((cur["runtime"] - rs[0]["runtime"]) / 60, used))
            out.append(pts)
        return out

    def fit(self) -> dict[str, Any]:
        """Flow rate from all readings: one slope, one start value per series."""
        sxx = sxy = hours = used = 0.0
        points = 0
        for pts in self._series():
            mx = sum(h for h, _ in pts) / len(pts)
            my = sum(u for _, u in pts) / len(pts)
            sxx += sum((h - mx) ** 2 for h, _ in pts)
            sxy += sum((h - mx) * (u - my) for h, u in pts)
            hours += pts[-1][0]
            used += pts[-1][1]
            points += len(pts)
        flow = sxy / sxx if sxx > 0 else None
        ok = flow is not None and hours >= CALIBRATE_MIN_HOURS and used >= CALIBRATE_MIN_LITERS
        if ok and not (MIN_FLOW_RATE <= flow <= MAX_FLOW_RATE):
            ok = False
        return {
            "calibrated": ok,
            "flow_rate": round(flow, 3) if flow is not None else None,
            "hours": round(hours, 1),
            "used_liters": round(used, 1),
            "readings_used": points,
        }

    def _apply_fit(self, keep_level: bool = False) -> dict[str, Any]:
        res = self.fit()
        old = self.flow_rate
        res["old_flow_rate"] = old
        if res["calibrated"]:
            new = res["flow_rate"]
            if keep_level:
                self.set_flow_rate(new)
            else:
                self.data["flow_rate"] = round(new, 3)
            res["message"] = (
                f"Flow rate {new:.2f} L/h (was {old:.2f}): {res['used_liters']:.0f} L in "
                f"{res['hours']:.1f} h burner time, {res['readings_used']} readings."
            )
        elif res["flow_rate"] is not None and res["hours"] >= CALIBRATE_MIN_HOURS and res["used_liters"] >= CALIBRATE_MIN_LITERS:
            res["message"] = (
                f"Flow rate not changed ({old:.2f} L/h): the readings give {res['flow_rate']:.2f} L/h, "
                f"outside {MIN_FLOW_RATE}-{MAX_FLOW_RATE} L/h. Check or delete a wrong reading."
            )
        else:
            res["message"] = (
                f"Flow rate not changed ({old:.2f} L/h): {res['hours']:.1f} h burner time and "
                f"{res['used_liters']:.0f} L used between the readings. Minimum "
                f"{CALIBRATE_MIN_HOURS:.0f} h and {CALIBRATE_MIN_LITERS:.0f} L."
            )
        return res

    @property
    def readings_view(self) -> list[dict[str, Any]]:
        """Readings with the period since the previous reading, newest first (for the card)."""
        out: list[dict[str, Any]] = []
        prev_by_epoch: dict[int, dict[str, Any]] = {}
        for r in self.data.get("readings") or []:
            item = {
                "id": r["id"],
                "date": r.get("date"),
                "gauge_cm": r.get("gauge_cm"),
                "liters": round(r["liters"], 1),
                "delivered": round(r.get("delivered", 0.0), 1),
                "note": r.get("note"),
                "hours": None,
                "used": None,
                "flow": None,
            }
            e = r.get("epoch", 0)
            prev = prev_by_epoch.get(e)
            if r.get("runtime") is not None:
                if prev is not None:
                    hours = (r["runtime"] - prev["runtime"]) / 60
                    used = prev["liters"] + r.get("delivered", 0.0) - r["liters"]
                    item["hours"] = round(hours, 1)
                    item["used"] = round(used, 1)
                    if hours >= READING_PERIOD_MIN_HOURS:
                        item["flow"] = round(used / hours, 2)
                prev_by_epoch[e] = r
            out.append(item)
        return list(reversed(out))


def _reading(
    rid: int,
    liters: float,
    gauge_cm: float | None,
    runtime: float | None,
    delivered: float,
    epoch: int,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "id": rid,
        "date": dt_util.now().strftime("%Y-%m-%d %H:%M") if note != "reference" else None,
        "liters": round(float(liters), 1),
        "gauge_cm": gauge_cm,
        "runtime": runtime,
        "delivered": round(float(delivered), 1),
        "epoch": epoch,
        "note": note,
    }
