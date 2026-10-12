/*
 * NRK Radio card — the episodes of a series or podcast (or the whole NRK
 * library), with play / add-to-queue per episode, styled like Mushroom tiles.
 *
 *   type: custom:nrk-radio-card
 *   show: podcast/fantorangens_vitseshow  # optional: lock to one series/podcast
 *   speaker: media_player.kitchen         # optional: always play here (else a dropdown)
 *   episodes: 5                           # optional: rows shown before "Show all"
 *   entity: media_player.nrk_radio        # optional
 *   title: Vitser                         # optional
 *
 * Served and loaded by the nrk_radio integration; no resource to add.
 */

// Own scope: nothing here may collide with other cards' globals.
(() => {
const PREFIX = "media-source://nrk_radio";
const ACTIVE = ["playing", "paused", "buffering"];
const DATED = /^(\d\d\.\d\d\.\d\d) · (.*)$/;

const STRINGS = {
  en: {
    search: "Search NRK Radio", back: "Back", speaker: "Speaker", keep: "Keep playing",
    keepHint: "Next episode when the queue ends", queuedN: (n) => `${n} queued`, clear: "Clear queue",
    play: "Play", queue: "Add to queue", queued: "Queued", remove: "Remove from queue", pause: "Pause",
    resume: "Resume", prev: "Previous", next: "Next", stop: "Stop", loading: "Loading…",
    empty: "Nothing here", noResults: "No results", error: "Could not load from NRK",
    missing: "NRK Radio is not set up", showAll: (n) => `Show all (${n})`, showFewer: "Show fewer",
  },
  nb: {
    search: "Søk i NRK Radio", back: "Tilbake", speaker: "Høyttaler", keep: "Fortsett å spille",
    keepHint: "Neste episode når køen er tom", queuedN: (n) => `${n} i kø`, clear: "Tøm kø",
    play: "Spill", queue: "Legg i kø", queued: "I kø", remove: "Fjern fra kø", pause: "Pause",
    resume: "Fortsett", prev: "Forrige", next: "Neste", stop: "Stopp", loading: "Laster…",
    empty: "Ingenting her", noResults: "Ingen treff", error: "Fikk ikke hentet fra NRK",
    missing: "NRK Radio er ikke satt opp", showAll: (n) => `Vis alle (${n})`, showFewer: "Vis færre",
  },
};

const ICONS = {
  play: "M8,5.14V19.14L19,12.14L8,5.14Z",
  pause: "M14,19H18V5H14M6,19H10V5H6V19Z",
  add: "M3 16H10V14H3M18 14V10H16V14H12V16H16V20H18V16H22V14M14 6H3V8H14M14 10H3V12H14V10Z",
  remove: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  prev: "M6,18V6H8V18H6M9.5,12L18,6V18L9.5,12Z",
  next: "M16,18H18V6H16M6,18L14.5,12L6,6V18Z",
  stop: "M18,18H6V6H18V18Z",
  back: "M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z",
  chevron: "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
  expand: "M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z",
  collapse: "M7.41,15.41L12,10.83L16.59,15.41L18,14L12,8L6,14L7.41,15.41Z",
  folder: "M10,4H4C2.89,4 2,4.89 2,6V18A2,2 0 0,0 4,20H20A2,2 0 0,0 22,18V8C22,6.89 21.1,6 20,6H12L10,4Z",
  radio: "M20,6A2,2 0 0,1 22,8V20A2,2 0 0,1 20,22H4A2,2 0 0,1 2,20V8C2,7.15 2.53,6.42 3.28,6.13L15.71,1L16.47,2.83L8.83,6H20M20,8H4V12H16V10H18V12H20V8M7,14A3,3 0 0,0 4,17A3,3 0 0,0 7,20A3,3 0 0,0 10,17A3,3 0 0,0 7,14Z",
  speaker: "M12,12A3,3 0 0,0 9,15A3,3 0 0,0 12,18A3,3 0 0,0 15,15A3,3 0 0,0 12,12M12,20A5,5 0 0,1 7,15A5,5 0 0,1 12,10A5,5 0 0,1 17,15A5,5 0 0,1 12,20M12,4A2,2 0 0,1 14,6A2,2 0 0,1 12,8C10.89,8 10,7.1 10,6C10,4.89 10.89,4 12,4M17,2H7C5.89,2 5,2.89 5,4V20A2,2 0 0,0 7,22H17A2,2 0 0,0 19,20V4C19,2.89 18.1,2 17,2Z",
  playlist: "M19,9H2V11H19V9M19,5H2V7H19V5M2,15H15V13H2V15M17,13V19L22,16L17,13Z",
  clearQueue: "M2,6V8H14V6H2M2,10V12H11V10H2M14.17,10.76L12.76,12.17L15.59,15L12.76,17.83L14.17,19.24L17,16.41L19.83,19.24L21.24,17.83L18.41,15L21.24,12.17L19.83,10.76L17,13.59L14.17,10.76M2,14V16H11V14H2Z",
};

// Mushroom's tile metrics: 12px padding, round 36-40px shape icon, 14/12px text.
const CSS = `
  :host { display: block; --nrk-accent: var(--primary-color); --nrk-accent-rgb: var(--token-rgb-primary, 106, 116, 211); }
  [hidden] { display: none !important; }
  ha-card { position: relative; isolation: isolate; overflow: hidden; }
  .tile { display: flex; align-items: center; gap: 12px; padding: 12px; min-height: 40px; }
  .tile + .tile { padding-top: 0; }
  .shape { width: 40px; height: 40px; flex: none; border-radius: 50%; overflow: hidden;
           display: flex; align-items: center; justify-content: center;
           background: rgba(var(--rgb-primary-text-color, 234, 235, 238), 0.06);
           color: var(--secondary-text-color); }
  .shape img { width: 100%; height: 100%; object-fit: cover; }
  .shape.accent { background: rgba(var(--nrk-accent-rgb), 0.2); color: var(--nrk-accent); }
  .info { flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; }
  .primary { font-size: var(--card-primary-font-size, 14px); font-weight: var(--card-primary-font-weight, 500);
             line-height: var(--card-primary-line-height, 20px); color: var(--primary-text-color);
             letter-spacing: 0.1px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .secondary { font-size: var(--card-secondary-font-size, 12px); font-weight: var(--card-secondary-font-weight, 400);
               line-height: var(--card-secondary-line-height, 16px); color: var(--secondary-text-color);
               letter-spacing: 0.4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .actions { display: flex; align-items: center; flex: none; gap: 2px; }
  button.icon { border: none; background: none; color: var(--primary-text-color); cursor: pointer;
                width: 36px; height: 36px; border-radius: 12px; padding: 0;
                display: inline-flex; align-items: center; justify-content: center; }
  button.icon:hover { background: rgba(var(--rgb-primary-text-color, 234, 235, 238), 0.08); }
  button.icon:active { transform: scale(0.94); }
  svg { width: 24px; height: 24px; fill: currentColor; }
  .shape svg { width: 22px; height: 22px; }
  select, input[type=search] {
    font: inherit; font-size: 14px; color: var(--primary-text-color);
    background: rgba(var(--rgb-primary-text-color, 234, 235, 238), 0.06);
    border: none; border-radius: 12px; padding: 0 12px; height: 40px; box-sizing: border-box; }
  select { max-width: 55%; }
  input[type=search] { width: 100%; }
  .search { padding: 0 12px 12px; }
  .divider { height: 1px; margin: 0 12px; background: var(--divider-color); }
  .nav { display: flex; align-items: center; gap: 4px; padding: 8px 12px 0 4px; }
  .nav .primary { flex: 1; }
  .list { padding: 4px 0 0; }
  .row { cursor: default; border-radius: 12px; }
  .row.expand { cursor: pointer; }
  .row.current .primary { color: var(--nrk-accent); }
  .row.current .shape { box-shadow: 0 0 0 2px var(--nrk-accent); }
  .row .queued { color: var(--nrk-accent); font-weight: 500; }
  .chev { color: var(--secondary-text-color); display: inline-flex; }
  .more { display: flex; align-items: center; justify-content: center; gap: 4px; width: 100%;
          border: none; background: none; cursor: pointer; padding: 4px 12px 12px;
          color: var(--secondary-text-color); font: inherit; font-size: 12px; letter-spacing: 0.4px; }
  .more svg { width: 18px; height: 18px; }
  .msg { color: var(--secondary-text-color); padding: 12px 12px 16px; font-size: 12px; text-align: center; }
`;

function svg(path) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"></path></svg>`;
}

function refOf(mediaContentId) {
  return mediaContentId.startsWith(PREFIX) ? mediaContentId.slice(PREFIX.length).replace(/^\//, "") : mediaContentId;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function shape(thumbnail, iconPath) {
  const box = el("div", "shape");
  if (thumbnail) {
    const img = el("img");
    img.loading = "lazy";
    img.src = thumbnail;
    box.appendChild(img);
  } else {
    box.innerHTML = svg(iconPath);
  }
  return box;
}

class NrkRadioCard extends HTMLElement {
  static getStubConfig() {
    return { show: "series/nyhetsmorgen" };
  }

  setConfig(config) {
    this._config = { entity: "media_player.nrk_radio", episodes: 5, ...config };
    this._stack = [];
    this._query = "";
    this._results = null;
    this._expanded = false;
    this._built = false;
    this._loadedFor = null;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
  }

  getCardSize() {
    return 2 + Math.min(this._config?.episodes || 5, 8);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    if (this._loadedFor !== this._config.entity && hass.states[this._config.entity]) {
      this._loadedFor = this._config.entity;
      this._open(this._config.show ? `${PREFIX}/${this._config.show}` : PREFIX);
    }
    this._update();
  }

  get _t() {
    const lang = (this._hass?.locale?.language || this._hass?.language || "en").toLowerCase();
    return ["nb", "nn", "no"].some((l) => lang.startsWith(l)) ? STRINGS.nb : STRINGS.en;
  }

  /* Helper entities belong to the same integration; find them rather than assume ids. */
  _sibling(domain, fallback) {
    const entities = this._hass.entities || {};
    const player = entities[this._config.entity];
    const match = Object.values(entities).find(
      (e) => e.platform === "nrk_radio" && e.entity_id.startsWith(`${domain}.`) &&
             (!player || e.device_id === player.device_id),
    );
    return match ? match.entity_id : fallback;
  }

  _build() {
    const t = this._t;
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>${CSS}</style>
      <ha-card>
        <div class="tile head">
          <div class="shape accent">${svg(ICONS.radio)}</div>
          <div class="info"><div class="primary"></div><div class="secondary"></div></div>
          <div class="actions">
            <button class="icon" data-act="prev" title="${t.prev}">${svg(ICONS.prev)}</button>
            <button class="icon" data-act="playpause">${svg(ICONS.play)}</button>
            <button class="icon" data-act="next" title="${t.next}">${svg(ICONS.next)}</button>
            <button class="icon" data-act="stop" title="${t.stop}">${svg(ICONS.stop)}</button>
          </div>
        </div>
        <div class="tile speaker" hidden>
          <div class="shape">${svg(ICONS.speaker)}</div>
          <div class="info"><div class="primary">${t.speaker}</div></div>
          <select></select>
        </div>
        <div class="tile keep">
          <div class="shape">${svg(ICONS.playlist)}</div>
          <div class="info"><div class="primary">${t.keep}</div><div class="secondary">${t.keepHint}</div></div>
          <button class="icon" data-act="clear" title="${t.clear}" hidden>${svg(ICONS.clearQueue)}</button>
          <ha-switch></ha-switch>
        </div>
        <div class="search" ${this._config.show ? "hidden" : ""}><input type="search" placeholder="${t.search}"></div>
        <div class="divider"></div>
        <div class="nav" hidden>
          <button class="icon" data-act="back" title="${t.back}">${svg(ICONS.back)}</button>
          <div class="primary crumb"></div>
        </div>
        <div class="list"><div class="msg">${t.loading}</div></div>
        <button class="more" hidden></button>
      </ha-card>`;
    this._el = (sel) => root.querySelector(sel);

    this._el(".head .actions").addEventListener("click", (ev) => this._control(ev));
    this._el('[data-act="clear"]').addEventListener("click", (ev) => this._control(ev));
    this._el(".nav").addEventListener("click", () => this._back());
    this._el(".more").addEventListener("click", () => { this._expanded = !this._expanded; this._render(); });
    this._el("ha-switch").addEventListener("change", (ev) => {
      const on = ev.target.checked;
      this._call("switch", on ? "turn_on" : "turn_off", {}, this._sibling("switch", "switch.nrk_radio_keep_playing"));
    });
    this._el(".speaker select").addEventListener("change", (ev) =>
      this._call("select", "select_option", { option: ev.target.value }, this._sibling("select", "select.nrk_radio_speaker")));
    const input = this._el("input[type=search]");
    input.addEventListener("input", () => {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(() => this._search(input.value.trim()), 350);
    });
    this._el(".list").addEventListener("click", (ev) => this._rowClick(ev));
    this._built = true;
  }

  async _open(mediaContentId) {
    this._showMessage(this._t.loading);
    try {
      const node = await this._hass.callWS({
        type: "media_player/browse_media",
        entity_id: this._config.entity,
        media_content_id: mediaContentId,
      });
      this._stack.push(node);
      this._expanded = false;
      this._render();
    } catch (err) {
      this._showMessage(`${this._t.error}: ${err.message || err.code || err}`);
    }
  }

  _back() {
    if (this._results) {
      this._results = null;
      this._el("input[type=search]").value = "";
    } else if (this._stack.length > 1) {
      this._stack.pop();
    }
    this._expanded = false;
    this._render();
  }

  async _search(query) {
    this._query = query;
    if (query.length < 2) {
      this._results = null;
      this._render();
      return;
    }
    this._showMessage(this._t.loading);
    try {
      const res = await this._hass.callWS({
        type: "media_player/search_media",
        entity_id: this._config.entity,
        search_query: query,
      });
      if (query !== this._query) return; // a newer search is on its way
      this._results = { title: `“${query}”`, children: res.result || [] };
      this._expanded = false;
      this._render();
    } catch (err) {
      this._showMessage(`${this._t.error}: ${err.message || err}`);
    }
  }

  _showMessage(text) {
    const list = this._el(".list");
    list.replaceChildren(el("div", "msg", text));
    this._el(".more").hidden = true;
  }

  _render() {
    const t = this._t;
    const node = this._results || this._stack[this._stack.length - 1];
    if (!node) return;
    const top = this._stack[0];

    // Header shape: the show's art when locked to a show, otherwise the radio icon.
    const headShape = this._el(".head .shape");
    if (this._config.show && top.thumbnail && !headShape.querySelector("img")) {
      headShape.replaceWith(shape(top.thumbnail));
    }
    this._el(".head .primary").textContent = this._config.title || (this._config.show ? top.title : "NRK Radio");

    this._el(".nav").hidden = !(this._results || this._stack.length > 1);
    this._el(".nav .crumb").textContent = node.title;

    const children = node.children || [];
    if (!children.length) {
      this._showMessage(this._results ? t.noResults : t.empty);
      return;
    }
    const limit = Number(this._config.episodes) || 0;
    const shown = this._expanded || !limit ? children : children.slice(0, limit);

    const rows = shown.map((child) => {
      const row = el("div", "tile row" + (child.can_expand ? " expand" : ""));
      row.dataset.id = child.media_content_id;
      row.dataset.ref = refOf(child.media_content_id);
      row.dataset.live = child.media_class === "channel" ? "1" : "";
      const dated = DATED.exec(child.title);
      const info = el("div", "info");
      info.append(el("div", "primary", dated ? dated[2] : child.title), el("div", "secondary"));
      row.dataset.sub = dated ? dated[1] : "";
      row.append(
        shape(child.thumbnail, child.media_class === "channel" ? ICONS.radio : ICONS.folder),
        info,
        el("div", "actions"),
      );
      row._child = child;
      return row;
    });
    this._el(".list").replaceChildren(...rows);

    const more = this._el(".more");
    more.hidden = !limit || children.length <= limit;
    more.innerHTML = this._expanded
      ? `${t.showFewer} ${svg(ICONS.collapse)}`
      : `${t.showAll(children.length)} ${svg(ICONS.expand)}`;
    this._updateRows();
  }

  _player() {
    return this._hass.states[this._config.entity];
  }

  _queueInfo() {
    const player = this._player();
    const queue = player?.attributes.queue || [];
    const pos = player?.attributes.queue_position ?? -1;
    const onOurs = !this._config.speaker || player?.attributes.speaker === this._config.speaker;
    return { player, queue, pos, active: Boolean(player && ACTIVE.includes(player.state) && onOurs) };
  }

  _speakerName() {
    const id = this._config.speaker || this._player()?.attributes.speaker;
    return this._hass.states[id]?.attributes.friendly_name || id || "";
  }

  _update() {
    if (!this._built) return;
    const t = this._t;
    const { player, queue, pos, active } = this._queueInfo();
    if (!player) {
      this._showMessage(t.missing);
      return;
    }

    // Header: what's playing (and how much is queued), or which speaker we'd play on.
    const upcoming = active ? queue.length - pos - 1 : 0;
    const playing = player.attributes.media_title || "";
    this._el(".head .secondary").textContent = active
      ? `${player.state === "playing" ? "▶" : "❚❚"} ${playing}` + (upcoming > 0 ? ` · ${t.queuedN(upcoming)}` : "")
      : this._speakerName();
    for (const act of ["prev", "next", "stop"]) this._el(`[data-act="${act}"]`).hidden = !active;
    const pp = this._el('[data-act="playpause"]');
    pp.innerHTML = svg(active && player.state === "playing" ? ICONS.pause : ICONS.play);
    pp.title = active && player.state === "playing" ? t.pause : t.play;
    pp.hidden = !active && !this._config.show; // idle + locked show: one tap plays it

    // Speaker: fixed by config, or a dropdown over the integration's select.
    const tile = this._el(".speaker");
    tile.hidden = Boolean(this._config.speaker);
    if (!tile.hidden) {
      const sel = this._hass.states[this._sibling("select", "select.nrk_radio_speaker")];
      const box = tile.querySelector("select");
      const options = sel?.attributes.options || [];
      if (box.dataset.opts !== options.join("|")) {
        box.replaceChildren(...options.map((o) => el("option", null, o)));
        box.dataset.opts = options.join("|");
      }
      if (sel && box.value !== sel.state) box.value = sel.state;
    }

    const keep = this._hass.states[this._sibling("switch", "switch.nrk_radio_keep_playing")];
    this._el("ha-switch").checked = keep?.state === "on";
    this._el('[data-act="clear"]').hidden = upcoming <= 0;
    this._el(".keep .secondary").textContent =
      upcoming > 0 ? `${t.next}: ${queue[pos + 1].title}` + (upcoming > 1 ? ` (+${upcoming - 1})` : "") : t.keepHint;

    this._updateRows();
  }

  _updateRows() {
    const list = this._el(".list");
    if (!list || !this._hass) return;
    const t = this._t;
    const { player, queue, pos, active } = this._queueInfo();
    const current = active && queue[pos] ? queue[pos].id : null;
    const queued = new Map();
    queue.forEach((item, i) => { if (i > pos) queued.set(item.id, i); });

    for (const row of list.querySelectorAll(".row")) {
      const child = row._child;
      const ref = row.dataset.ref;
      const isCurrent = ref === current;
      const queuePos = queued.get(ref);
      // Shows are expandable *and* playable: they get the button, the row opens them.
      let state;
      if (!child.can_play) state = "none";
      else if (isCurrent) state = player.state === "playing" ? "pause" : "resume";
      else if (queuePos !== undefined) state = "queued";
      else if (active && !row.dataset.live) state = "add";
      else state = "play";

      row.classList.toggle("current", isCurrent);
      const sub = row.querySelector(".secondary");
      sub.replaceChildren();
      if (queuePos !== undefined) sub.append(el("span", "queued", `${t.queued} #${queuePos - pos}`));
      if (row.dataset.sub) sub.append((queuePos !== undefined ? " · " : "") + row.dataset.sub);
      sub.hidden = !sub.textContent;

      const actions = row.querySelector(".actions");
      if (actions.dataset.state === state) continue;
      actions.dataset.state = state;
      const button = {
        none: "",
        play: `<button class="icon" data-act="play" title="${t.play}">${svg(ICONS.play)}</button>`,
        add: `<button class="icon" data-act="add" title="${t.queue}">${svg(ICONS.add)}</button>`,
        queued: `<button class="icon" data-act="remove" title="${t.remove}">${svg(ICONS.remove)}</button>`,
        pause: `<button class="icon" data-act="pause" title="${t.pause}">${svg(ICONS.pause)}</button>`,
        resume: `<button class="icon" data-act="resume" title="${t.resume}">${svg(ICONS.play)}</button>`,
      }[state];
      actions.innerHTML = button + (child.can_expand ? `<span class="chev">${svg(ICONS.chevron)}</span>` : "");
    }
  }

  _rowClick(ev) {
    const row = ev.target.closest(".row");
    if (!row) return;
    const button = ev.target.closest("button");
    if (!button) {
      if (row._child.can_expand) {
        this._results = null;
        this._el("input[type=search]").value = "";
        this._open(row.dataset.id);
      }
      return;
    }
    const act = button.dataset.act;
    if (act === "play") this._play(row.dataset.id);
    else if (act === "add") this._play(row.dataset.id, "add");
    else if (act === "pause") this._call("media_player", "media_pause");
    else if (act === "resume") this._call("media_player", "media_play");
    else if (act === "remove") {
      const { queue, pos } = this._queueInfo();
      const index = queue.findIndex((item, i) => i > pos && item.id === row.dataset.ref);
      if (index > pos) this._call("nrk_radio", "remove_from_queue", { position: index });
    }
  }

  _play(mediaContentId, enqueue) {
    const data = {
      media_content_id: mediaContentId,
      media_content_type: "music",
      extra: this._config.speaker ? { speaker: this._config.speaker } : {},
    };
    if (enqueue) data.enqueue = enqueue;
    this._call("media_player", "play_media", data);
  }

  _control(ev) {
    const act = ev.target.closest("button")?.dataset.act;
    if (act === "playpause" && !this._queueInfo().active) {
      // Nothing of ours playing: start the show (newest episode, or episode 1 of a serial).
      this._play(`${PREFIX}/${this._config.show}`);
      return;
    }
    const service = {
      prev: "media_previous_track", next: "media_next_track", stop: "media_stop",
      playpause: "media_play_pause", clear: "clear_playlist",
    }[act];
    if (service) this._call("media_player", service);
  }

  _call(domain, service, data = {}, entityId = this._config.entity) {
    this._hass.callService(domain, service, data, { entity_id: entityId }).catch((err) => {
      this.dispatchEvent(new CustomEvent("hass-notification", {
        bubbles: true, composed: true, detail: { message: err.message || String(err) },
      }));
    });
  }
}

if (!customElements.get("nrk-radio-card")) {
  customElements.define("nrk-radio-card", NrkRadioCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "nrk-radio-card",
    name: "NRK Radio",
    description: "Episodes of an NRK series or podcast, with play and queue buttons.",
    preview: false,
  });
}
})();
