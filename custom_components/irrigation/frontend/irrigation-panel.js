/**
 * Irrigation sidebar panel and dashboard card.
 *
 * Zones are found through the entity registry, so renamed entities keep
 * working. Every command goes through the normal valve and number actions.
 */

const MARK_URL = new URL("./mark.svg", import.meta.url).href;

const MIN_DURATION = 10;
const MAX_DURATION = 7200;
const SAVE_DELAY_MS = 500;
const CHECK_DELAY_MS = 1000;

// The palette from docs/BRAND.md, with the tints it defines for dark surfaces.
const STYLES = `
  :host {
    --irr-slate: #121C2B;
    --irr-blue: #0284C7;
    --irr-green: #2C5E43;
    --irr-amber: #F59E0B;
    --irr-page: #EEF2F7;
    --irr-surface: #FFFFFF;
    --irr-line: #D3DCE7;
    --irr-text: #121C2B;
    --irr-muted: #4A5A70;
    --irr-active: #0284C7;
    --irr-on-active: #FFFFFF;
    display: block;
    color: var(--irr-text);
    font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, sans-serif));
  }
  :host([dark]) {
    --irr-page: #121C2B;
    --irr-surface: #1C2940;
    --irr-line: #2B3B55;
    --irr-text: #FFFFFF;
    --irr-muted: #9FB0C7;
    --irr-active: #38BDF8;
    --irr-on-active: #121C2B;
  }
  button {
    font: inherit;
    cursor: pointer;
    border: none;
    border-radius: 10px;
  }
  button:focus-visible {
    outline: 2px solid var(--irr-active);
    outline-offset: 2px;
  }
  button:disabled {
    cursor: default;
    opacity: 0.5;
  }
  .group + .group {
    margin-top: 24px;
  }
  .group-title {
    margin: 0 0 10px;
    font-size: 15px;
    font-weight: 600;
    color: var(--irr-muted);
  }
  .zones {
    display: grid;
    gap: 12px;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  }
  .zone {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border: 1px solid var(--irr-line);
    border-radius: 14px;
    background: var(--irr-surface);
  }
  .zone[running] {
    border-color: var(--irr-active);
  }
  .top {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .dot {
    flex: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--irr-muted);
  }
  .zone[running] .dot {
    background: var(--irr-active);
  }
  .name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    font-size: 16px;
    font-weight: 600;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .status {
    flex: none;
    font-size: 14px;
    color: var(--irr-muted);
    font-variant-numeric: tabular-nums;
  }
  .zone[running] .status {
    font-weight: 600;
    color: var(--irr-active);
  }
  .track {
    height: 8px;
    overflow: hidden;
    border-radius: 4px;
    background: var(--irr-line);
  }
  .fill {
    width: 0;
    height: 100%;
    border-radius: 4px;
    background: var(--irr-active);
    transition: width 1s linear;
  }
  .controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .stepper {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .step {
    width: 36px;
    height: 36px;
    font-size: 20px;
    line-height: 1;
    color: var(--irr-text);
    background: var(--irr-page);
  }
  .duration {
    min-width: 54px;
    text-align: center;
    font-size: 15px;
    font-variant-numeric: tabular-nums;
  }
  .action {
    min-width: 88px;
    height: 40px;
    padding: 0 18px;
    font-weight: 600;
    color: var(--irr-on-active);
    background: var(--irr-active);
  }
  .zone[running] .action {
    color: var(--irr-text);
    background: transparent;
    box-shadow: inset 0 0 0 2px var(--irr-active);
  }
  .error {
    margin: 0;
    padding: 8px 10px;
    border-radius: 8px;
    font-size: 14px;
    color: var(--irr-slate);
    background: var(--irr-amber);
  }
  .empty {
    margin: 0;
    padding: 16px;
    color: var(--irr-muted);
  }
  @media (prefers-reduced-motion: reduce) {
    .fill {
      transition: none;
    }
  }
`;

const PANEL_STYLES = `
  :host {
    min-height: 100vh;
    background: var(--irr-page);
  }
  header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 20px;
    color: #FFFFFF;
    background: var(--irr-slate);
  }
  header img {
    width: 34px;
    height: 34px;
  }
  h1 {
    flex: 1;
    margin: 0;
    font-size: 20px;
    font-weight: 600;
  }
  .menu {
    width: 36px;
    height: 36px;
    font-size: 20px;
    color: #FFFFFF;
    background: transparent;
  }
  .stop-all {
    height: 36px;
    padding: 0 14px;
    font-weight: 600;
    color: var(--irr-slate);
    background: var(--irr-amber);
  }
  main {
    max-width: 1100px;
    margin: 0 auto;
    padding: 20px 16px 32px;
  }
`;

const CARD_STYLES = `
  ha-card {
    padding: 16px;
  }
  .title {
    margin: 0 0 12px;
    font-size: 18px;
    font-weight: 600;
  }
`;

function formatTime(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, "0");
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}`
    : `${minutes}:${secs}`;
}

function stepDuration(value, direction) {
  // One minute at a time, or 10 seconds below a minute
  const size = value + direction * 60 < 60 ? 10 : 60;
  const next = direction > 0 ? value + size : value - size;
  return Math.min(MAX_DURATION, Math.max(MIN_DURATION, Math.round(next / size) * size));
}

/** Explain a failed command, using the reason in the action's error if there is one. */
function failureText(start, message) {
  const reason = message?.replace(/^Zone \d+ didn't \w+: (ERR )?/, "");
  if (start && reason === "zone at maximum runtime") {
    return "This zone reached its 2-hour limit, so it can't restart for up to 10 minutes.";
  }
  const detail = reason ? `Reason: ${reason}.` : "Check the connection to irrigationd.";
  return start
    ? `The zone didn't start. ${detail}`
    : `The zone didn't stop and may still be running. ${detail}`;
}

/** Shorten default names, and drop the device name Home Assistant prefixes. */
function zoneLabel(state, zone) {
  const device = zone.deviceName;
  let label = state?.attributes.friendly_name || `Zone ${zone.zone}`;
  if (device && label.startsWith(`${device} `)) label = label.slice(device.length + 1);
  return label.replace(/^Irrigation Zone (\d+)$/, "Zone $1");
}

/** Group this integration's zones by controller, ordered by zone number. */
function findControllers(hass) {
  const zones = new Map();
  const durations = new Map();
  for (const entry of Object.values(hass.entities || {})) {
    if (entry.platform !== "irrigation") continue;
    const state = hass.states[entry.entity_id];
    const zone = state?.attributes.zone;
    if (zone === undefined) continue;
    const key = `${entry.device_id}:${zone}`;
    if (entry.entity_id.startsWith("valve.")) zones.set(key, { entry, zone });
    if (entry.entity_id.startsWith("number.")) durations.set(key, entry.entity_id);
  }

  const deviceName = (id) => hass.devices?.[id]?.name_by_user || hass.devices?.[id]?.name;
  const controllers = new Map();
  for (const [key, { entry, zone }] of zones) {
    const deviceId = entry.device_id;
    if (!controllers.has(deviceId)) controllers.set(deviceId, []);
    controllers.get(deviceId).push({
      key,
      zone,
      valveId: entry.entity_id,
      numberId: durations.get(key),
      deviceName: deviceName(deviceId),
    });
  }
  return [...controllers.entries()].map(([deviceId, list]) => ({
    deviceId,
    name: deviceName(deviceId),
    zones: list.sort((a, b) => a.zone - b.zone),
  }));
}

/** One zone's row. Built once and then patched, so clicks are never lost. */
class ZoneRow {
  constructor(owner, zone) {
    this.owner = owner;
    this.zone = zone;
    this.pendingDuration = null;
    this.saveTimer = null;
    this.errorText = "";
    this.busyText = "";

    this.el = document.createElement("section");
    this.el.className = "zone";
    this.el.innerHTML = `
      <div class="top">
        <span class="dot"></span>
        <span class="name"></span>
        <span class="status" role="status"></span>
      </div>
      <div class="track"><div class="fill"></div></div>
      <div class="controls">
        <div class="stepper">
          <button class="step minus" type="button">&minus;</button>
          <span class="duration"></span>
          <button class="step plus" type="button">+</button>
        </div>
        <button class="action" type="button"></button>
      </div>
      <p class="error" hidden></p>
    `;
    const find = (selector) => this.el.querySelector(selector);
    this.name = find(".name");
    this.status = find(".status");
    this.fill = find(".fill");
    this.duration = find(".duration");
    this.minus = find(".minus");
    this.plus = find(".plus");
    this.action = find(".action");
    this.error = find(".error");

    this.minus.addEventListener("click", () => this.adjust(-1));
    this.plus.addEventListener("click", () => this.adjust(1));
    this.action.addEventListener("click", () => this.toggle());
  }

  get state() {
    return this.owner.hass.states[this.zone.valveId];
  }

  get savedDuration() {
    const number = this.owner.hass.states[this.zone.numberId];
    const value = Number(number?.state);
    return Number.isFinite(value) ? value : null;
  }

  update() {
    const state = this.state;
    const unavailable = !state || state.state === "unavailable";
    const running = state?.state === "open";
    const remaining = Number(state?.attributes.remaining) || 0;
    const total = Number(state?.attributes.configured_duration) || 0;
    const duration = this.pendingDuration ?? this.savedDuration;
    const label = zoneLabel(state, this.zone);

    this.el.toggleAttribute("running", running);
    this.name.textContent = label;
    this.name.title = label;
    if (unavailable) this.status.textContent = "Unavailable";
    else if (this.busyText) this.status.textContent = this.busyText;
    else this.status.textContent = running ? `${formatTime(remaining)} left` : "Idle";

    const done = running && total ? ((total - remaining) / total) * 100 : 0;
    this.fill.style.width = `${Math.min(100, Math.max(0, done))}%`;

    this.duration.textContent = duration === null ? "–" : formatTime(duration);
    this.duration.title = "Default run time";
    this.minus.disabled = duration === null || duration <= MIN_DURATION;
    this.plus.disabled = duration === null || duration >= MAX_DURATION;
    this.minus.setAttribute("aria-label", `Shorter run time for ${label}`);
    this.plus.setAttribute("aria-label", `Longer run time for ${label}`);

    this.action.textContent = running ? "Stop" : "Start";
    this.action.setAttribute("aria-label", `${running ? "Stop" : "Start"} ${label}`);
    this.action.disabled = unavailable || Boolean(this.busyText);

    const message = unavailable
      ? "Can't reach irrigationd, so this zone's state is unknown. A running zone still closes when its time ends."
      : this.errorText;
    this.error.hidden = !message;
    this.error.textContent = message;
  }

  adjust(direction) {
    const current = this.pendingDuration ?? this.savedDuration;
    if (current === null) return;
    this.pendingDuration = stepDuration(current, direction);
    this.update();
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.saveDuration(), SAVE_DELAY_MS);
  }

  async saveDuration() {
    const value = this.pendingDuration;
    try {
      await this.owner.hass.callService("number", "set_value", {
        entity_id: this.zone.numberId,
        value,
      });
      this.errorText = "";
    } catch (err) {
      this.errorText = `Couldn't save the run time: ${err.message}`;
    }
    if (this.pendingDuration === value) this.pendingDuration = null;
    this.update();
  }

  async toggle() {
    const start = this.state?.state !== "open";
    // A changed run time has to be saved before the zone starts with it
    if (start && this.pendingDuration !== null) {
      clearTimeout(this.saveTimer);
      await this.saveDuration();
    }
    await this.send(start);
  }

  /**
   * Send a command, then check the zone really changed.
   */
  async send(start) {
    this.busyText = start ? "Starting…" : "Stopping…";
    this.errorText = "";
    this.update();
    try {
      await this.owner.hass.callService("valve", start ? "open_valve" : "close_valve", {
        entity_id: this.zone.valveId,
      });
      await new Promise((resolve) => setTimeout(resolve, CHECK_DELAY_MS));
      if ((this.state?.state === "open") !== start) {
        this.errorText = failureText(start);
      }
    } catch (err) {
      this.errorText = failureText(start, err.message);
    }
    this.busyText = "";
    this.update();
  }
}

/** Shared rendering for the panel and the card. */
class ZoneList {
  constructor(owner, root) {
    this.owner = owner;
    this.root = root;
    this.rows = new Map();
    this.signature = "";
  }

  get rowList() {
    return [...this.rows.values()];
  }

  update() {
    const controllers = findControllers(this.owner.hass);
    const signature = JSON.stringify(controllers);
    if (signature !== this.signature) {
      this.signature = signature;
      this.rebuild(controllers);
    }
    for (const row of this.rows.values()) row.update();
  }

  rebuild(controllers) {
    const rows = new Map();
    this.root.replaceChildren();
    if (!controllers.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No zones found. Add the Irrigation Controller integration to get started.";
      this.root.append(empty);
    }
    for (const controller of controllers) {
      const group = document.createElement("div");
      group.className = "group";
      if (controllers.length > 1 && controller.name) {
        const title = document.createElement("h2");
        title.className = "group-title";
        title.textContent = controller.name;
        group.append(title);
      }
      const zones = document.createElement("div");
      zones.className = "zones";
      for (const zone of controller.zones) {
        const row = this.rows.get(zone.key) ?? new ZoneRow(this.owner, zone);
        row.zone = zone;
        rows.set(zone.key, row);
        zones.append(row.el);
      }
      group.append(zones);
      this.root.append(group);
    }
    this.rows = rows;
  }
}

class IrrigationPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>${STYLES}${PANEL_STYLES}</style>
      <header>
        <button class="menu" type="button" aria-label="Open sidebar" hidden>&#9776;</button>
        <img src="${MARK_URL}" alt="">
        <h1>Irrigation</h1>
        <button class="stop-all" type="button" hidden>Stop all</button>
      </header>
      <main></main>
    `;
    this.menu = this.shadowRoot.querySelector(".menu");
    this.stopAll = this.shadowRoot.querySelector(".stop-all");
    this.list = new ZoneList(this, this.shadowRoot.querySelector("main"));
    this.menu.addEventListener("click", () => {
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
    });
    this.stopAll.addEventListener("click", () => {
      for (const row of this.list.rowList) {
        if (row.state?.state === "open") row.send(false);
      }
    });
  }

  set hass(hass) {
    this._hass = hass;
    this.toggleAttribute("dark", Boolean(hass.themes?.darkMode));
    this.list.update();
    this.stopAll.hidden = !this.list.rowList.some((row) => row.state?.state === "open");
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this.menu.hidden = !narrow;
  }
}

class IrrigationZonesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>${STYLES}${CARD_STYLES}</style>
      <ha-card>
        <h2 class="title" hidden></h2>
        <div class="list"></div>
      </ha-card>
    `;
    this.title_ = this.shadowRoot.querySelector(".title");
    this.list = new ZoneList(this, this.shadowRoot.querySelector(".list"));
  }

  setConfig(config) {
    this.title_.textContent = config.title || "";
    this.title_.hidden = !config.title;
  }

  set hass(hass) {
    this._hass = hass;
    this.toggleAttribute("dark", Boolean(hass.themes?.darkMode));
    this.list.update();
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    return 2 + this.list.rows.size * 3;
  }

  static getStubConfig() {
    return { title: "Irrigation" };
  }
}

if (!customElements.get("irrigation-panel")) {
  customElements.define("irrigation-panel", IrrigationPanel);
}
if (!customElements.get("irrigation-zones-card")) {
  customElements.define("irrigation-zones-card", IrrigationZonesCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "irrigation-zones-card")) {
  window.customCards.push({
    type: "irrigation-zones-card",
    name: "Irrigation Zones",
    description: "Start and stop zones and set their run times.",
  });
}
