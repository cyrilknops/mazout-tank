/* Heating Oil Tank card — shipped with the oil_tank integration.
 *
 *   type: custom:oil-tank-card
 *   entity: sensor.gasoil_tank_level   # the "Level" sensor of the integration
 *   name: Gasoil tank                   # optional
 *   show_actions: true                  # optional, delivery / gauge input
 */
const CARD_VERSION = "1.0.4";

const fmt = (v, d = 0) =>
  v === null || v === undefined || isNaN(Number(v))
    ? "–"
    : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

class OilTankCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) throw new Error("Set 'entity' to the Level sensor of the oil tank.");
    this._config = { show_actions: true, ...config };
    this._built = false;
  }

  static getStubConfig(hass) {
    const e = Object.values(hass.states).find((s) => s.attributes && s.attributes.oil_tank);
    return { entity: e ? e.entity_id : "" };
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._render();
  }

  _build() {
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { --tank-ok: var(--info-color, #1e88e5); --tank-warn: var(--warning-color, #fb8c00); --tank-bad: var(--error-color, #e53935); }
        ha-card { container-type: inline-size; padding: 16px; display: flex; flex-direction: column; gap: 14px; height: 100%; box-sizing: border-box; }
        .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
        .title { font-size: 1.15rem; font-weight: 500; color: var(--primary-text-color); }
        .badge { font-size: .75rem; padding: 3px 8px; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
        .main { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; align-items: stretch; flex: 1; }
        .stats { display: flex; flex-direction: column; justify-content: space-between; gap: 10px; min-width: 0; }
        .stat .label { font-size: .8rem; color: var(--secondary-text-color); }
        .stat .value { font-size: 1.9rem; line-height: 1.1; font-weight: 500; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
        .stat .value small { font-size: .9rem; font-weight: 400; color: var(--secondary-text-color); margin-left: 2px; }
        .row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
        .mini .label { font-size: .72rem; color: var(--secondary-text-color); }
        .mini .value { font-size: 1rem; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
        .tankwrap { display: flex; align-items: stretch; gap: 6px; cursor: pointer; }
        .tank { position: relative; width: 76px; min-height: 220px; border-radius: 38px; overflow: hidden;
                background: var(--secondary-background-color, rgba(127,127,127,.12));
                border: 2px solid var(--divider-color, rgba(127,127,127,.3)); }
        .fill { position: absolute; left: 0; right: 0; bottom: 0; background: var(--fillc); transition: height .8s ease; }
        @media (prefers-reduced-motion: reduce) { .fill { transition: none; } }
        .mark { position: absolute; left: 0; right: 0; border-top: 2px dashed var(--tank-bad); opacity: .7; }
        .scale { display: flex; flex-direction: column; justify-content: space-between; font-size: .7rem; color: var(--secondary-text-color); padding-block: 2px; font-variant-numeric: tabular-nums; }
        .pct { position: absolute; left: 0; right: 0; text-align: center; font-weight: 600; font-size: .95rem; color: var(--primary-text-color); text-shadow: 0 0 4px var(--card-background-color, #fff); }
        .actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
        .act { display: flex; gap: 6px; align-items: center; }
        .act input { width: 100%; min-width: 0; box-sizing: border-box; padding: 8px; border-radius: 8px; font: inherit;
                     border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color); color: var(--primary-text-color); }
        .act button { padding: 8px 10px; border-radius: 8px; border: 0; cursor: pointer; font: inherit; white-space: nowrap;
                      background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .act button:focus-visible, .act input:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
        .msg { font-size: .8rem; color: var(--secondary-text-color); min-height: 1em; }
        .warn { font-size: .8rem; color: var(--tank-warn); }
        @container (max-width: 340px) { .actions { grid-template-columns: 1fr; } .row { grid-template-columns: 1fr; gap: 4px; } .mini { display: flex; justify-content: space-between; } }
      </style>
      <ha-card>
        <div class="head"><span class="title"></span><span class="badge"></span></div>
        <div class="main">
          <div class="stats">
            <div class="stat"><div class="label">Level</div><div class="value" id="liters"></div></div>
            <div class="stat"><div class="label">Gauge height</div><div class="value" id="cm"></div></div>
            <div class="row">
              <div class="mini"><div class="label">Today</div><div class="value" id="today"></div></div>
              <div class="mini"><div class="label">Avg / day</div><div class="value" id="avg"></div></div>
              <div class="mini"><div class="label">Days left</div><div class="value" id="days"></div></div>
            </div>
          </div>
          <div class="tankwrap" title="Details">
            <div class="scale"><span id="smax"></span><span id="smid"></span><span>0</span></div>
            <div class="tank"><div class="fill"></div><div class="mark"></div><div class="pct"></div></div>
          </div>
        </div>
        <div class="warn" id="pending" hidden></div>
        <div class="actions" id="actions">
          <div class="act"><input id="deliv" type="number" min="1" step="1" placeholder="Delivery (L)" aria-label="Delivered liters"><button id="bdeliv">Add</button></div>
          <div class="act"><input id="gauge" type="number" min="0" step="0.5" placeholder="Gauge (cm)" aria-label="Gauge reading in cm"><button id="bgauge">Set</button></div>
        </div>
        <div class="msg" id="msg"></div>
      </ha-card>`;
    const $ = (id) => root.getElementById(id);
    root.querySelector(".tankwrap").addEventListener("click", () => {
      const ev = new Event("hass-more-info", { bubbles: true, composed: true });
      ev.detail = { entityId: this._config.entity };
      this.dispatchEvent(ev);
    });
    $("bdeliv").addEventListener("click", () => this._call("add_delivery", "liters", $("deliv")));
    $("bgauge").addEventListener("click", () => this._call("set_level", "gauge_cm", $("gauge")));
    this._root = root;
    this._built = true;
  }

  async _call(service, field, input) {
    const value = Number(input.value);
    const msg = this._root.getElementById("msg");
    if (!input.value || isNaN(value) || value < 0) {
      msg.textContent = "Type a number first.";
      return;
    }
    const st = this._hass.states[this._config.entity];
    try {
      await this._hass.callService("oil_tank", service, {
        config_entry_id: st.attributes.config_entry_id,
        [field]: value,
      });
      input.value = "";
      msg.textContent = service === "add_delivery" ? `Added ${fmt(value)} L.` : `Level set from ${fmt(value, 1)} cm.`;
    } catch (err) {
      msg.textContent = `Not done: ${err.message || err}`;
    }
  }

  _render() {
    const r = this._root;
    const st = this._hass.states[this._config.entity];
    const $ = (id) => r.getElementById(id);
    r.querySelector(".title").textContent =
      this._config.name || (st && st.attributes.friendly_name) || "Oil tank";
    if (!st || !st.attributes.oil_tank) {
      $("liters").textContent = "–";
      $("msg").textContent = `Entity ${this._config.entity} is not an oil tank Level sensor.`;
      return;
    }
    const a = st.attributes;
    const liters = Number(st.state);
    const cap = Number(a.capacity) || 1;
    const pct = Math.max(0, Math.min(100, (liters / cap) * 100));
    const low = Number(a.low_alert) || 0;
    const state = liters < low ? "bad" : liters < low * 2 ? "warn" : "ok";
    const color = `var(--tank-${state})`;

    $("liters").innerHTML = `${fmt(liters)}<small>L</small>`;
    $("cm").innerHTML = `${fmt(a.height_cm, 1)}<small>cm</small>`;
    $("today").textContent = a.used_today === null ? "–" : `${fmt(a.used_today, 1)} L`;
    $("avg").textContent = a.average_per_day === null ? "–" : `${fmt(a.average_per_day, 1)} L`;
    $("days").textContent = a.days_remaining === null ? "–" : fmt(a.days_remaining);
    $("smax").textContent = fmt(cap);
    $("smid").textContent = fmt(cap / 2);

    const badge = r.querySelector(".badge");
    badge.textContent = state === "bad" ? "Low" : state === "warn" ? "Order soon" : "Normal";
    badge.style.color = color;

    const fill = r.querySelector(".fill");
    fill.style.setProperty("--fillc", color);
    fill.style.height = `${pct}%`;
    r.querySelector(".mark").style.bottom = `${Math.min(100, (low / cap) * 100)}%`;
    const p = r.querySelector(".pct");
    p.textContent = `${fmt(pct)}%`;
    p.style.bottom = `calc(${Math.min(pct, 88)}% + 6px)`;

    const pend = $("pending");
    if (a.waiting_for_counter) {
      pend.hidden = false;
      pend.textContent = "Waiting for the burner counter. The level is fixed until the counter is online.";
    } else if (!a.source_available) {
      pend.hidden = false;
      pend.textContent = "Burner counter offline. The level shows the last known value.";
    } else {
      pend.hidden = true;
    }
    $("actions").hidden = !this._config.show_actions;
  }
}

/* ===================================================================== *
 * Oil burner card — Buderus Logamatic 2107 via KM271-WiFi (the78mole)
 *
 *   type: custom:oil-burner-card
 *   name: Ketel                         # optional
 *   tank: sensor.gasoil_tank_level      # optional, auto-detected
 *   entities: { ... }                   # optional, override any default below
 * ===================================================================== */
const BURNER_DEFAULTS = {
  burner: "binary_sensor.kessel_betrieb_1_stufe_2",
  burner_control: "binary_sensor.brenneransteuerung",
  boiler_temp: "sensor.kesselvorlaufisttemperatur",
  boiler_target: "sensor.kesselvorlaufsolltemperatur",
  switch_on: "sensor.brennereinschalttemperatur",
  switch_off: "sensor.brennerausschalttemperatur",
  exhaust: "sensor.abgastemperatur",
  outside: "sensor.aussentemperatur",
  outside_damped: "sensor.gedaempfte_aussentemperatur",
  hw_temp: "sensor.warmwasseristtemperatur",
  hw_target: "sensor.warmwassersolltemperatur",
  hw_loading: "binary_sensor.ladepumpenbetrieb",
  flow_temp: "sensor.hk1_vorlaufisttemperatur",
  flow_target: "sensor.hk1_vorlaufsolltemperatur",
  room_temp: "sensor.hk1_raumisttemperatur",
  room_target: "sensor.hk1_raumsolltemperatur",
  pump: "sensor.hk1_pumpenleistung",
  summer: "binary_sensor.hk1_sommer_modus",
  runtime: "sensor.brennerlaufzeit_1",
  day_setpoint: "number.heizkreis_1_raumsolltemperatur_tag",
  night_setpoint: "number.heizkreis_1_raumsolltemperatur_nacht",
  hw_setpoint: "number.warmwassersolltemperatur_tag",
  hc_mode: "select.km271_for_friends_43b394_heizkreis_1_betriebsmodus",
  hw_mode: "select.km271_for_friends_43b394_warmwasser_betriebsmodus",
};
const BURNER_FAULTS = [
  ["binary_sensor.fehler_brennerstoerung", "Burner failure"],
  ["binary_sensor.fehler_kesselfuehler", "Boiler sensor"],
  ["binary_sensor.fehler_zusatzfuehler", "Additional sensor"],
  ["binary_sensor.fehler_kessel_bleibt_kalt", "Boiler stays cold"],
  ["binary_sensor.fehler_abgasfuehler", "Exhaust gas sensor"],
  ["binary_sensor.fehler_abgas_ueber_grenzwert", "Exhaust gas over limit"],
  ["binary_sensor.fehler_sicherungskette_ausgeloest", "Safety chain released"],
  ["binary_sensor.fehler_externe_stoerung", "External fault"],
  ["binary_sensor.hk1_fehler_vorlauffuehler", "Flow sensor (HC1)"],
  ["binary_sensor.hk1_fb_fehlerhaft", "Remote control fault"],
  ["binary_sensor.hk1_keine_kommunikation_mit_fb", "No remote control link"],
  ["binary_sensor.ww_fehler_fuehler", "Hot water sensor"],
  ["binary_sensor.ww_fehler_ww_bleibt_kalt", "Hot water stays cold"],
  ["binary_sensor.ww_fehler_anode", "Anode fault"],
  ["binary_sensor.ww_fehler_desinfektion", "Disinfection fault"],
  ["binary_sensor.alarm_brenner", "Burner alarm"],
  ["binary_sensor.alarm_abgasfuehler", "Exhaust sensor alarm"],
  ["binary_sensor.alarm_kesselvorlauffuehler", "Boiler flow sensor alarm"],
];
const MODE_LABELS = { Nacht: "Night", Tag: "Day", Auto: "Auto", Aus: "Off", Ein: "On" };
// The KM271 sends 255 when no exhaust gas sensor is connected
const NO_SENSOR = 255;

class OilBurnerCard extends HTMLElement {
  setConfig(config) {
    this._config = { name: "Ketel", ...config };
    this._e = { ...BURNER_DEFAULTS, ...(config.entities || {}) };
    this._pending = {};
    this._msg = "";
    this._sig = "";
  }

  static getStubConfig() {
    return { name: "Ketel" };
  }

  getCardSize() {
    return 10;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._root) this._build();
    const ids = [...Object.values(this._e), ...BURNER_FAULTS.map((f) => f[0]), this._tankId()];
    const sig = ids.map((i) => (hass.states[i] ? hass.states[i].state : "")).join("|") +
      JSON.stringify(this._pending) + this._msg;
    if (sig !== this._sig) {
      this._sig = sig;
      this._render();
    }
  }

  _tankId() {
    if (this._config.tank) return this._config.tank;
    const t = this._hass && Object.values(this._hass.states).find((s) => s.attributes && s.attributes.oil_tank);
    return t ? t.entity_id : "";
  }

  _st(key) {
    return this._hass.states[this._e[key]];
  }

  _num(key) {
    const s = this._st(key);
    if (!s) return null;
    const v = Number(s.state);
    return isNaN(v) ? null : v;
  }

  _on(key) {
    const s = this._st(key);
    return !!s && s.state === "on";
  }

  _t(v, d = 0) {
    return v === null ? "–" : `${fmt(v, d)}°`;
  }

  _build() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { --flame: var(--state-climate-heat-color, #ff8100); --bad: var(--error-color, #db4437); --ok: var(--success-color, #43a047);  --sch-hot: #e4572e; --sch-cold: #3d8be5; --sch-oil: #b7822f; --sch-flame-core: #ffd54f;
          --sch-idle: var(--divider-color, rgba(127,127,127,.35)); --sch-part: var(--card-background-color, #fff); --sch-line: var(--secondary-text-color); }
        .sch { display: block; width: 100%; height: auto; }
        .sch .part { fill: var(--sch-part); stroke: var(--sch-line); stroke-width: 2; }
        .sch .pipe { fill: none; stroke-width: 6; stroke-linecap: round; stroke-linejoin: round; }
        .sch .pipe.thin { stroke-width: 3; }
        .sch text { font-family: inherit; }
        .sch .sm { font-size: 13px; fill: var(--secondary-text-color); }
        .sch .b, .sch tspan.b { font-weight: 600; fill: var(--primary-text-color); }
        .sch .lbl { font-size: 10px; letter-spacing: .08em; fill: var(--secondary-text-color); }
        .sch .big { font-size: 32px; font-weight: 500; fill: var(--primary-text-color); }
        .sch .val { font-size: 18px; font-weight: 500; fill: var(--primary-text-color); }
        .sch .hit { cursor: pointer; }
        .sch .hit:hover .part { stroke: var(--primary-color); }
        ha-card { container-type: inline-size; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
        .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
        .title { font-size: 1.15rem; font-weight: 500; color: var(--primary-text-color); }
        .pill { display: inline-flex; align-items: center; gap: 4px; font-size: .78rem; padding: 3px 10px 3px 6px; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
        .pill ha-icon { --mdc-icon-size: 16px; }
        .boiler { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 16px; align-items: center; }
        .big { cursor: pointer; }
        .big .v { font-size: 2.6rem; line-height: 1; font-weight: 500; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
        .big .l { font-size: .8rem; color: var(--secondary-text-color); margin-top: 4px; }
        .band { position: relative; height: 10px; border-radius: 5px; background: var(--secondary-background-color, rgba(127,127,127,.15)); }
        .band .zone { position: absolute; top: 0; bottom: 0; border-radius: 5px; background: color-mix(in srgb, var(--flame) 30%, transparent); }
        .band .tick { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--secondary-text-color); }
        .band .now { position: absolute; top: -5px; width: 12px; height: 20px; margin-left: -6px; border-radius: 6px; background: var(--primary-text-color); border: 2px solid var(--card-background-color, #fff); box-sizing: border-box; }
        .bandl { display: flex; justify-content: space-between; font-size: .75rem; color: var(--secondary-text-color); margin-top: 8px; font-variant-numeric: tabular-nums; gap: 8px; flex-wrap: wrap; }
        .tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
        .tile { padding: 10px; border-radius: 12px; background: var(--secondary-background-color, rgba(127,127,127,.08)); cursor: pointer; min-width: 0; }
        .tile .l { font-size: .75rem; color: var(--secondary-text-color); display: flex; align-items: center; gap: 4px; }
        .tile .l ha-icon { --mdc-icon-size: 14px; }
        .tile .v { font-size: 1.25rem; font-weight: 500; color: var(--primary-text-color); font-variant-numeric: tabular-nums; margin-top: 2px; }
        .tile .s { font-size: .75rem; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
        .sect { font-size: .8rem; font-weight: 500; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: .06em; margin-bottom: -6px; }
        .ctrl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
        .step { display: flex; flex-direction: column; gap: 4px; padding: 10px; border-radius: 12px; border: 1px solid var(--divider-color, rgba(127,127,127,.25)); min-width: 0; }
        .step .l { font-size: .75rem; color: var(--secondary-text-color); }
        .step .row { display: flex; align-items: center; justify-content: space-between; gap: 4px; }
        .step .val { font-size: 1.2rem; font-weight: 500; font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
        .step.changed { border-color: var(--primary-color); }
        .step.changed .val { color: var(--primary-color); }
        button { font: inherit; cursor: pointer; }
        .pm { width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--divider-color, #ccc); background: none; color: var(--primary-text-color); font-size: 1.1rem; line-height: 1; }
        .pm:disabled { opacity: .35; cursor: default; }
        .modes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
        .seg { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
        .seg .l { font-size: .75rem; color: var(--secondary-text-color); }
        .seg .opts { display: flex; border: 1px solid var(--divider-color, #ccc); border-radius: 10px; overflow: hidden; }
        .seg .opts button { flex: 1; padding: 7px 4px; border: 0; background: none; color: var(--primary-text-color); min-width: 0; }
        .seg .opts button + button { border-left: 1px solid var(--divider-color, #ccc); }
        .seg .opts button.cur { background: var(--secondary-background-color, rgba(127,127,127,.15)); font-weight: 500; }
        .seg .opts button.new { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .apply { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px; border-radius: 12px; background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
        .apply .t { font-size: .85rem; color: var(--primary-text-color); }
        .apply .b { display: flex; gap: 6px; }
        .apply button { padding: 7px 12px; border-radius: 8px; border: 0; }
        .apply .go { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .apply .no { background: none; color: var(--primary-text-color); border: 1px solid var(--divider-color, #ccc); }
        .faults { display: flex; flex-wrap: wrap; gap: 6px; }
        .fault { font-size: .8rem; padding: 4px 10px; border-radius: 999px; color: var(--bad); border: 1px solid var(--bad); }
        .okline { font-size: .85rem; color: var(--secondary-text-color); display: flex; align-items: center; gap: 6px; }
        .okline ha-icon { --mdc-icon-size: 18px; color: var(--ok); }
        .msg { font-size: .8rem; color: var(--secondary-text-color); }
        button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
        @container (max-width: 460px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } .ctrl { grid-template-columns: 1fr; } .modes { grid-template-columns: 1fr; } }
      </style>
      <ha-card><div id="body"></div></ha-card>`;
    this._root.addEventListener("click", (ev) => this._click(ev));
  }

  _click(ev) {
    const el = ev.target.closest("[data-act]");
    if (!el) return;
    const act = el.dataset.act;
    if (act === "info") return this._moreInfo(el.dataset.id);
    if (act === "step") return this._step(el.dataset.key, Number(el.dataset.dir));
    if (act === "mode") return this._mode(el.dataset.key, el.dataset.opt);
    if (act === "apply") return this._apply();
    if (act === "cancel") {
      this._pending = {};
      this._msg = "";
      return this._refresh();
    }
  }

  _refresh() {
    this._sig = "";
    this.hass = this._hass;
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId };
    this.dispatchEvent(ev);
  }

  _step(key, dir) {
    const s = this._st(key);
    if (!s) return;
    const a = s.attributes;
    const step = Number(a.step) || 0.5;
    const cur = key in this._pending ? this._pending[key] : Number(s.state);
    const next = Math.round((cur + dir * step) / step) * step;
    if (next < a.min || next > a.max) return;
    if (Math.abs(next - Number(s.state)) < 1e-9) delete this._pending[key];
    else this._pending[key] = next;
    this._msg = "";
    this._refresh();
  }

  _mode(key, opt) {
    const s = this._st(key);
    if (!s) return;
    if (opt === s.state) delete this._pending[key];
    else this._pending[key] = opt;
    this._msg = "";
    this._refresh();
  }

  async _apply() {
    const keys = Object.keys(this._pending);
    let done = 0;
    try {
      for (const key of keys) {
        const id = this._e[key];
        const value = this._pending[key];
        if (id.startsWith("number.")) {
          await this._hass.callService("number", "set_value", { entity_id: id, value });
        } else {
          await this._hass.callService("select", "select_option", { entity_id: id, option: value });
        }
        delete this._pending[key];
        done++;
      }
      this._msg = `Sent ${done} change${done === 1 ? "" : "s"} to the boiler controller.`;
    } catch (err) {
      this._msg = `Sent ${done} of ${keys.length}. Error: ${err.message || err}`;
    }
    this._refresh();
  }

  _tile(label, icon, value, sub, id) {
    return `<div class="tile" data-act="info" data-id="${id || ""}">
      <div class="l"><ha-icon icon="${icon}"></ha-icon>${label}</div>
      <div class="v">${value}</div><div class="s">${sub || "&nbsp;"}</div></div>`;
  }

  _stepper(key, label) {
    const s = this._st(key);
    if (!s) return "";
    const a = s.attributes;
    const changed = key in this._pending;
    const v = changed ? this._pending[key] : Number(s.state);
    const d = (Number(a.step) || 1) < 1 ? 1 : 0;
    return `<div class="step ${changed ? "changed" : ""}"><div class="l">${label}</div>
      <div class="row">
        <button class="pm" data-act="step" data-key="${key}" data-dir="-1" aria-label="Lower ${label}" ${v - (a.step || 1) < a.min ? "disabled" : ""}>−</button>
        <span class="val">${fmt(v, d)}°</span>
        <button class="pm" data-act="step" data-key="${key}" data-dir="1" aria-label="Raise ${label}" ${v + (a.step || 1) > a.max ? "disabled" : ""}>+</button>
      </div></div>`;
  }

  _segment(key, label) {
    const s = this._st(key);
    if (!s) return "";
    const pend = this._pending[key];
    const opts = (s.attributes.options || []).map((o) => {
      const cls = pend === o ? "new" : !pend && s.state === o ? "cur" : pend && s.state === o ? "cur" : "";
      return `<button class="${cls}" data-act="mode" data-key="${key}" data-opt="${o}">${MODE_LABELS[o] || o}</button>`;
    }).join("");
    return `<div class="seg"><div class="l">${label}</div><div class="opts">${opts}</div></div>`;
  }

  /* Flat installation schematic. State colors only, no animation. */
  _schematic(burnerOn, tank) {
    const e = this._e;
    const n = (k) => this._num(k);
    const t = (v, d = 0) => this._t(v, d);
    const flow = n("flow_temp"), pump = n("pump"), hw = n("hw_temp");
    const pumpOn = pump !== null && pump > 0;
    const hwLoading = this._on("hw_loading");
    const flowHot = flow !== null && flow >= 35;
    const ex = n("exhaust");
    const hcMode = this._st("hc_mode"), hwMode = this._st("hw_mode");
    const C = {
      hot: "var(--sch-hot)", cold: "var(--sch-cold)", idle: "var(--sch-idle)",
      oil: "var(--sch-oil)", flame: "var(--flame)",
    };
    const flowC = flowHot ? C.hot : C.idle;
    const retC = pumpOn ? C.cold : C.idle;
    const loadC = hwLoading ? C.hot : C.idle;
    const oilC = burnerOn ? C.oil : C.idle;

    // Tank fill
    let tankFill = "", tankTxt1 = "–", tankTxt2 = "", tankId = "", lowY = null;
    if (tank && tank.attributes.oil_tank) {
      const a = tank.attributes;
      const pct = Math.max(0, Math.min(1, Number(tank.state) / (Number(a.capacity) || 1)));
      const hFill = 106 * pct;
      const low = Number(a.low_alert) / (Number(a.capacity) || 1);
      tankFill = `<rect x="22" y="${278 - hFill}" width="76" height="${hFill}" rx="6" fill="${Number(tank.state) < Number(a.low_alert) ? "var(--bad)" : C.oil}" opacity=".85"/>`;
      lowY = 278 - 106 * low;
      tankTxt1 = `${fmt(Number(tank.state))} L`;
      tankTxt2 = `${fmt(a.percent)}% · ${fmt(a.height_cm, 1)} cm`;
      tankId = tank.entity_id;
    }
    // Hot water tint: warmer color when hotter
    const hwTint = hw === null ? 0 : Math.max(0, Math.min(1, (hw - 20) / 40));
    const modeTxt = [
      hcMode ? `Heating ${MODE_LABELS[hcMode.state] || hcMode.state}` : "",
      hwMode ? `hot water ${MODE_LABELS[hwMode.state] || hwMode.state}` : "",
      this._on("summer") ? "summer" : "",
    ].filter(Boolean).join(" · ");

    return `
    <svg class="sch" viewBox="0 0 600 322" role="img" aria-label="Heating installation">
      <text class="sm" x="20" y="22">${modeTxt}</text>
      <g data-act="info" data-id="${e.outside}" class="hit">
        <text class="sm" x="580" y="22" text-anchor="end">Outside <tspan class="b">${t(n("outside"))}</tspan> · damped ${t(n("outside_damped"))}</text>
      </g>

      <!-- pipes (under the parts) -->
      <path d="M100 200 H115 V238 H130" class="pipe thin" stroke="${oilC}"/>
      <path d="M280 100 H500 V120" class="pipe" stroke="${flowC}"/>
      <path d="M550 190 V212 H280" class="pipe" stroke="${retC}"/>
      <path d="M280 240 H400" class="pipe" stroke="${loadC}"/>
      <path d="M400 264 H280" class="pipe" stroke="${hwLoading ? C.cold : C.idle}"/>

      <!-- chimney -->
      <g data-act="info" data-id="${e.exhaust}" class="hit">
        <rect x="208" y="34" width="24" height="46" class="part"/>
        <text class="sm" x="240" y="52">Exhaust ${ex === null || ex === NO_SENSOR ? "–" : t(ex)}</text>
      </g>

      <!-- boiler -->
      <g data-act="info" data-id="${e.boiler_temp}" class="hit">
        <rect x="170" y="80" width="110" height="190" rx="8" class="part" ${burnerOn ? 'style="fill:color-mix(in srgb, var(--flame) 10%, var(--sch-part))"' : ""}/>
        <text class="lbl" x="225" y="104" text-anchor="middle">BOILER</text>
        <text class="big" x="225" y="140" text-anchor="middle">${t(n("boiler_temp"))}</text>
        <text class="sm" x="225" y="160" text-anchor="middle">target ${t(n("boiler_target"))}</text>
        <text class="sm" x="225" y="178" text-anchor="middle">on ${t(n("switch_on"))} · off ${t(n("switch_off"))}</text>
      </g>

      <!-- burner + flame -->
      <g data-act="info" data-id="${e.burner}" class="hit">
        <rect x="130" y="224" width="40" height="30" rx="4" class="part"/>
        ${burnerOn
          ? `<path d="M171 239 C 190 221, 216 225, 236 239 C 216 253, 190 257, 171 239 Z" fill="${C.flame}"/>
             <path d="M171 239 C 186 230, 202 232, 214 239 C 202 246, 186 248, 171 239 Z" fill="var(--sch-flame-core)"/>`
          : `<circle cx="176" cy="239" r="3" fill="${C.idle}"/>`}
        <text class="sm" x="150" y="272" text-anchor="middle">Burner</text>
        <text class="sm b" x="150" y="288" text-anchor="middle" ${burnerOn ? 'style="fill:var(--flame)"' : ""}>${burnerOn ? "On" : "Off"}</text>
      </g>

      <!-- oil tank -->
      <g data-act="info" data-id="${tankId}" class="hit">
        <text class="lbl" x="60" y="164" text-anchor="middle">OIL TANK</text>
        <rect x="20" y="170" width="80" height="110" rx="8" class="part"/>
        ${tankFill}
        ${lowY !== null ? `<line x1="22" x2="98" y1="${lowY}" y2="${lowY}" stroke="var(--bad)" stroke-dasharray="4 3" stroke-width="1.5"/>` : ""}
        <text class="val" x="60" y="300" text-anchor="middle">${tankTxt1}</text>
        <text class="sm" x="60" y="316" text-anchor="middle">${tankTxt2}</text>
      </g>

      <!-- heating pump on the flow pipe -->
      <g data-act="info" data-id="${e.pump}" class="hit">
        <circle cx="360" cy="100" r="13" class="part" style="stroke:${pumpOn ? "var(--primary-color)" : "var(--sch-idle)"}"/>
        <path d="M354 93 L368 100 L354 107 Z" fill="${pumpOn ? "var(--primary-color)" : "var(--sch-idle)"}"/>
        <text class="sm" x="360" y="76" text-anchor="middle">Pump ${pump === null ? "–" : fmt(pump) + "%"}</text>
      </g>
      <g data-act="info" data-id="${e.flow_temp}" class="hit">
        <text class="sm" x="432" y="90" text-anchor="middle">Flow <tspan class="b">${t(flow)}</tspan> → ${t(n("flow_target"))}</text>
      </g>

      <!-- radiator -->
      <g data-act="info" data-id="${e.room_temp}" class="hit">
        <rect x="490" y="120" width="70" height="70" rx="4" class="part"/>
        ${[502, 514, 526, 538, 550].map((x) => `<line x1="${x}" x2="${x}" y1="128" y2="182" stroke="${flowHot && pumpOn ? C.hot : "var(--sch-idle)"}" stroke-width="3" stroke-linecap="round"/>`).join("")}
        <text class="sm" x="490" y="234">Room <tspan class="b">${t(n("room_temp"), 1)}</tspan></text>
        <text class="sm" x="490" y="250">target ${t(n("room_target"), 1)}</text>
      </g>

      <!-- hot water loading pump -->
      <g data-act="info" data-id="${e.hw_loading}" class="hit">
        <circle cx="330" cy="240" r="11" class="part" style="stroke:${hwLoading ? "var(--primary-color)" : "var(--sch-idle)"}"/>
        <path d="M325 234 L337 240 L325 246 Z" fill="${hwLoading ? "var(--primary-color)" : "var(--sch-idle)"}"/>
      </g>

      <!-- hot water cylinder -->
      <g data-act="info" data-id="${e.hw_temp}" class="hit">
        <rect x="380" y="220" width="76" height="92" rx="30" class="part"
          style="fill:color-mix(in srgb, var(--sch-hot) ${Math.round(hwTint * 28)}%, var(--sch-part))"/>
        <text class="lbl" x="418" y="246" text-anchor="middle">HOT WATER</text>
        <text class="val" x="418" y="272" text-anchor="middle">${t(hw)}</text>
        <text class="sm" x="418" y="290" text-anchor="middle">target ${t(n("hw_target"))}</text>
      </g>
    </svg>`;
  }

  _render() {
    const h = this._hass;
    const body = this._root.getElementById("body");
    const e = this._e;
    const burnerOn = this._on("burner") || this._on("burner_control");
    const faults = BURNER_FAULTS.filter(([id]) => h.states[id] && h.states[id].state === "on");
    const offline = !this._st("boiler_temp") || this._st("boiler_temp").state === "unavailable";

    const pill = faults.length
      ? `<span class="pill" style="color:var(--bad)"><ha-icon icon="mdi:alert"></ha-icon>Fault</span>`
      : offline
        ? `<span class="pill" style="color:var(--secondary-text-color)"><ha-icon icon="mdi:lan-disconnect"></ha-icon>Offline</span>`
        : burnerOn
          ? `<span class="pill" style="color:var(--flame)"><ha-icon icon="mdi:fire"></ha-icon>Burner on</span>`
          : `<span class="pill" style="color:var(--secondary-text-color)"><ha-icon icon="mdi:fire-off"></ha-icon>Standby</span>`;

    // Boiler temperature band
    const bt = this._num("boiler_temp"), tgt = this._num("boiler_target");
    const on = this._num("switch_on"), off = this._num("switch_off");
    const lo = 20, hi = 90, pos = (v) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))}%`;
    const band = `
      <div class="band">
        ${on !== null && off !== null ? `<div class="zone" style="left:${pos(on)};width:calc(${pos(off)} - ${pos(on)})"></div>` : ""}
        ${tgt !== null ? `<div class="tick" style="left:${pos(tgt)}" title="Target"></div>` : ""}
        ${bt !== null ? `<div class="now" style="left:${pos(bt)}"></div>` : ""}
      </div>
      <div class="bandl"><span>Starts at ${this._t(on)}</span><span>Target ${this._t(tgt)}</span><span>Stops at ${this._t(off)}</span></div>`;

    const ex = this._num("exhaust");
    const exTxt = ex === null || ex === NO_SENSOR ? "–" : this._t(ex);

    // Oil data from the tank integration
    const tank = h.states[this._tankId()];
    let oil = "";
    if (tank && tank.attributes.oil_tank) {
      const a = tank.attributes;
      const hoursToday = a.used_today !== null && a.flow_rate ? a.used_today / a.flow_rate : null;
      const costId = this._tankId().replace(/_level$/, "_cost_today");
      const cost = h.states[costId] && !isNaN(Number(h.states[costId].state)) ? Number(h.states[costId].state) : null;
      oil = `<div class="sect">Today</div><div class="tiles">
        ${this._tile("Burner time", "mdi:timer-outline", hoursToday === null ? "–" : `${fmt(hoursToday, 1)} h`, `total ${fmt((this._num("runtime") || 0) / 60)} h`, e.runtime)}
        ${this._tile("Oil used", "mdi:water", a.used_today === null ? "–" : `${fmt(a.used_today, 1)} L`, a.average_per_day === null ? "avg –" : `avg ${fmt(a.average_per_day, 1)} L/day`, this._tankId())}
        ${this._tile("Cost", "mdi:currency-eur", cost === null ? "–" : `€ ${fmt(cost, 2)}`, "", costId)}
        ${this._tile("Tank", "mdi:storage-tank", `${fmt(Number(tank.state))} L`, `${fmt(a.percent)}% · ${fmt(a.height_cm, 1)} cm`, this._tankId())}
      </div>`;
    }

    const nPend = Object.keys(this._pending).length;
    const summer = this._on("summer");

    body.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:16px">
        <div class="head"><span class="title">${this._config.name}</span>${pill}</div>

        ${this._config.schematic ? this._schematic(burnerOn, tank) : `<div class="boiler">
          <div class="big" data-act="info" data-id="${e.boiler_temp}">
            <div class="v">${this._t(bt)}</div><div class="l">Boiler · exhaust ${exTxt}</div>
          </div>
          <div>${band}</div>
        </div>

        <div class="tiles">
          ${this._tile("Outside", "mdi:thermometer", this._t(this._num("outside")), `damped ${this._t(this._num("outside_damped"))}${summer ? " · summer" : ""}`, e.outside)}
          ${this._tile("Hot water", "mdi:water-boiler", this._t(this._num("hw_temp")), `target ${this._t(this._num("hw_target"))}${this._on("hw_loading") ? " · loading" : ""}`, e.hw_temp)}
          ${this._tile("Heating flow", "mdi:radiator", this._t(this._num("flow_temp")), `target ${this._t(this._num("flow_target"))} · pump ${fmt(this._num("pump"))}%`, e.flow_temp)}
          ${this._tile("Room", "mdi:home-thermometer", this._t(this._num("room_temp"), 1), `target ${this._t(this._num("room_target"), 1)}`, e.room_temp)}
        </div>`}

        ${oil}

        <div class="sect">Settings</div>
        <div class="ctrl">
          ${this._stepper("day_setpoint", "Room day")}
          ${this._stepper("night_setpoint", "Room night")}
          ${this._stepper("hw_setpoint", "Hot water")}
        </div>
        <div class="modes">
          ${this._segment("hc_mode", "Heating mode")}
          ${this._segment("hw_mode", "Hot water mode")}
        </div>
        ${nPend ? `<div class="apply"><span class="t">${nPend} change${nPend === 1 ? "" : "s"}. Each change writes to the boiler controller.</span>
          <span class="b"><button class="no" data-act="cancel">Cancel</button><button class="go" data-act="apply">Apply</button></span></div>` : ""}
        ${this._msg ? `<div class="msg">${this._msg}</div>` : ""}

        <div class="sect">Faults</div>
        ${faults.length
          ? `<div class="faults">${faults.map(([id, l]) => `<span class="fault" data-act="info" data-id="${id}">${l}</span>`).join("")}</div>`
          : `<div class="okline"><ha-icon icon="mdi:check-circle"></ha-icon>No faults</div>`}
      </div>`;
  }
}

if (!customElements.get("oil-tank-card")) {
  customElements.define("oil-tank-card", OilTankCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "oil-tank-card",
    name: "Oil tank",
    description: "Heating oil tank level with gauge height, use and days left.",
    preview: true,
  });
  console.info(`%c OIL-TANK-CARD %c ${CARD_VERSION} `, "background:#a34a24;color:#fff", "");
}
if (!customElements.get("oil-burner-card")) {
  customElements.define("oil-burner-card", OilBurnerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "oil-burner-card",
    name: "Oil burner (Buderus KM271)",
    description: "Burner state, boiler and hot water temperatures, settings with confirm, oil use and faults.",
    preview: false,
  });
}
