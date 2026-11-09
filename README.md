# Heating Oil Tank (mazout-tank)

Home Assistant integration that calculates the heating-oil level from the burner runtime counter
(for example "Brennerlaufzeit 1" from a Buderus Logamatic 2107 with a KM271-WiFi module).

## Method

The integration stores one reference point: a level (L) and the counter value at that time.

```
level = reference level − (counter now − reference counter) ÷ 60 × flow rate (L/h)
```

It does not add up changes. A restart, an offline sensor, a value of 0 or an impossible jump
cannot change the level.

## Installation

HACS: add this repository as a custom repository (type "Integration"), install, restart.
Manual: copy `custom_components/oil_tank` to `/config/custom_components/`, restart.

Then: Settings › Devices & services › Add integration › **Heating Oil Tank**.

| Setting | Example |
|---|---|
| Burner runtime counter | `sensor.brennerlaufzeit_1` (min, h or s) |
| Oil price sensor (optional) | sensor with the price per liter |
| Tank capacity | 4000 L |
| Liters per cm | 28.6 (35 cm = 1000 L) |
| Low level alert | 500 L |
| Burner flow rate | G115/21 ≈ 2.3, G115/28 ≈ 3.0, G115/34 ≈ 3.8 L/h |
| Gauge reading now | 48 cm |

## Entities

Level (L), level %, gauge height (cm), used today, used this month, average use per day (7 days),
days remaining, cost today, cost this month, tank value, burner time since reference,
low level, burner counter status, burner flow rate (editable),
consumption (L, total) and total cost (€).

## Energy dashboard

Settings › Dashboards › Energy › Gas consumption › Add gas source:

- Gas usage: `sensor.<name>_consumption` (device class gas, liters, total increasing)
- Cost: "Use an entity tracking the total costs" → `sensor.<name>_total_cost`

The total cost adds liters × oil price at the moment of burning, so price changes stay correct in the history.

## Actions

| Action | Use |
|---|---|
| `oil_tank.add_delivery` | After a delivery: liters on the delivery note |
| `oil_tank.set_level` | Set the level from the gauge (`gauge_cm`) or in liters |
| `oil_tank.calibrate_flow` | After ≥ 20 h burner time and ≥ 50 L use: read the gauge; the integration calculates the real L/h |

## Cards

The integration adds two cards automatically.

Tank card:

```yaml
type: custom:oil-tank-card
entity: sensor.gasoil_tank_level
```

Burner card for a Buderus Logamatic 2107 with KM271-WiFi (default entity names of the78mole firmware, German):
burner state, boiler temperature with switch-on/off band, hot water, heating flow, room, oil use today,
setpoints and modes with a confirm step (each change writes to the controller EEPROM), and faults.

```yaml
type: custom:oil-burner-card
name: Ketel
schematic: true        # optional: installation schematic instead of the temperature tiles
# entities:            # override any default, for example
#   hc_mode: select.my_km271_heizkreis_1_betriebsmodus
```
