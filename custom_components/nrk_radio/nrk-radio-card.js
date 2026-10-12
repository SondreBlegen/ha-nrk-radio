/*
 * NRK Radio card — browse a series (or the whole NRK library), play or queue
 * episodes on a speaker, and see what's playing and what's next.
 *
 *   type: custom:nrk-radio-card
 *   show: series/nyhetsmorgen        # optional: lock the card to one series/podcast
 *   speaker: media_player.kitchen    # optional: always play here (else a dropdown)
 *   entity: media_player.nrk_radio   # optional
 *   title: Morgennytt                # optional
 *
 * Served and loaded by the nrk_radio integration; no resource to add.
 */

const PREFIX = "media-source://nrk_radio";
const ACTIVE = ["playing", "paused", "buffering"];

const STRINGS = {
  en: {
    search: "Search NRK Radio", back: "Back", speaker: "Speaker", keep: "Keep playing",
    keepHint: "When the queue ends, continue with the next episode",
    nothing: "Nothing playing", next: "Up next", clear: "Clear queue", play: "Play",
    queue: "Add to queue", queued: "Queued", remove: "Remove from queue", pause: "Pause",
    resume: "Resume", loading: "Loading…", empty: "Nothing here", noResults: "No results",
    error: "Could not load from NRK", missing: "NRK Radio is not set up",
  },
  nb: {
    search: "Søk i NRK Radio", back: "Tilbake", speaker: "Høyttaler", keep: "Fortsett å spille",
    keepHint: "Når køen er tom, fortsett med neste episode",
    nothing: "Ingenting spilles", next: "Neste", clear: "Tøm kø", play: "Spill",
    queue: "Legg i kø", queued: "I kø", remove: "Fjern fra kø", pause: "Pause",
    resume: "Fortsett", loading: "Laster…", empty: "Ingenting her", noResults: "Ingen treff",
    error: "Fikk ikke hentet fra NRK", missing: "NRK Radio er ikke satt opp",
  },
};

const ICONS = {
  play: "M8,5.14V19.14L19,12.14L8,5.14Z",
  pause: "M14,19H18V5H14M6,19H10V5H6V19Z",
  add: "M3 16H10V14H3M18 14V10H16V14H12V16H16V20H18V16H22V14M14 6H3V8H14M14 10H3V12H14V10Z",
  queued: "M15,6H3V8H15V6M15,10H3V12H15V10M3,16H11V14H3V16M17,6V14.18C16.69,14.07 16.35,14 16,14A3,3 0 0,0 13,17A3,3 0 0,0 16,20A3,3 0 0,0 19,17V8H22V6H17Z",
  remove: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  prev: "M6,18V6H8V18H6M9.5,12L18,6V18L9.5,12Z",
  next: "M16,18H18V6H16M6,18L14.5,12L6,6V18Z",
  stop: "M18,18H6V6H18V18Z",
  back: "M20,11V13H8L13.5,18.5L12.08,19.92L4.16,12L12.08,4.08L13.5,5.5L8,11H20Z",
  chevron: "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
  folder: "M10,4H4C2.89,4 2,4.89 2,6V18A2,2 0 0,0 4,20H20A2,2 0 0,0 22,18V8C22,6.89 21.1,6 20,6H12L10,4Z",
  radio: "M20,6A2,2 0 0,1 22,8V20A2,2 0 0,1 20,22H4A2,2 0 0,1 2,20V8C2,7.15 2.53,6.42 3.28,6.13L15.71,1L16.47,2.83L8.83,6H20M20,8H4V12H16V10H18V12H20V8M7,14A3,3 0 0,0 4,17A3,3 0 0,0 7,20A3,3 0 0,0 10,17A3,3 0 0,0 7,14Z",
};

const CSS = `
  :host { display: block; }
  [hidden] { display: none !important; }
  ha-card { overflow: hidden; }
  .header { display: flex; align-items: center; gap: 12px; padding: 16px 16px 8px; }
  .header img { width: 56px; height: 56px; border-radius: 8px; object-fit: cover; flex: none; }
  .header h2 { margin: 0; font-size: 1.25rem; font-weight: 500; line-height: 1.3; flex: 1; min-width: 0; }
  .controls { display: grid; grid-template-columns: 1fr auto; gap: 8px 12px; align-items: center; padding: 0 16px 8px; }
  .controls label { color: var(--secondary-text-color); font-size: 0.9rem; }
  select, input[type=search] {
    font: inherit; color: var(--primary-text-color); background: var(--input-fill-color, var(--secondary-background-color));
    border: 1px solid var(--divider-color); border-radius: 8px; padding: 8px 10px; width: 100%; box-sizing: border-box;
  }
  .speaker-fixed { font-weight: 500; text-align: right; }
  .keep { display: flex; align-items: center; justify-content: space-between; grid-column: 1 / -1; }
  .keep small { display: block; color: var(--secondary-text-color); font-size: 0.8rem; }
  .now { margin: 4px 16px 8px; padding: 10px; border-radius: 12px; background: var(--secondary-background-color);
         display: grid; grid-template-columns: 48px 1fr; gap: 4px 12px; align-items: center; }
  .now img { width: 48px; height: 48px; border-radius: 6px; object-fit: cover; grid-row: span 2; }
  .now .title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .now .artist, .upnext { color: var(--secondary-text-color); font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .now .buttons { grid-column: 1 / -1; display: flex; align-items: center; justify-content: center; gap: 4px; }
  .upnext { grid-column: 1 / -1; display: flex; align-items: center; gap: 8px; }
  .upnext span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .search { padding: 0 16px 8px; }
  .nav { display: flex; align-items: center; gap: 4px; padding: 0 8px; min-height: 40px; }
  .nav .crumb { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .list { max-height: var(--nrk-radio-list-height, 480px); overflow-y: auto; padding: 0 8px 8px; }
  .row { display: flex; align-items: center; gap: 12px; padding: 6px 8px; border-radius: 10px; min-height: 52px; }
  .row.expand { cursor: pointer; }
  .row.expand:hover { background: var(--secondary-background-color); }
  .row.current { background: rgba(var(--rgb-primary-color, 3, 169, 244), 0.12); }
  .row img, .row .noimg { width: 44px; height: 44px; border-radius: 6px; object-fit: cover; flex: none; background: var(--secondary-background-color); }
  .row .noimg { display: flex; align-items: center; justify-content: center; color: var(--secondary-text-color); }
  .row .text { flex: 1; min-width: 0; }
  .row .t { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.3; }
  .row .badge { color: var(--primary-color); font-size: 0.8rem; font-weight: 500; }
  .row .actions { display: flex; align-items: center; flex: none; }
  button.icon { border: none; background: none; color: var(--primary-text-color); cursor: pointer; width: 40px; height: 40px;
                border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; padding: 0; }
  button.icon:hover { background: var(--secondary-background-color); }
  button.icon.primary { color: var(--primary-color); }
  button.icon[disabled] { opacity: 0.4; cursor: default; }
  button.text { border: none; background: none; color: var(--primary-color); cursor: pointer; font: inherit; font-size: 0.85rem; padding: 4px 6px; }
  svg { width: 24px; height: 24px; fill: currentColor; }
  .chev { color: var(--secondary-text-color); }
  .msg { color: var(--secondary-text-color); padding: 16px; text-align: center; }
`;

function svg(path) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"></path></svg>`;
}

function refOf(mediaContentId) {
  return mediaContentId.startsWith(PREFIX) ? mediaContentId.slice(PREFIX.length).replace(/^\//, "") : mediaContentId;
}

class NrkRadioCard extends HTMLElement {
  static getStubConfig() {
    return { show: "series/nyhetsmorgen" };
  }

  setConfig(config) {
    this._config = { entity: "media_player.nrk_radio", ...config };
    this._stack = [];
    this._query = "";
    this._results = null;
    this._built = false;
    this._loadedFor = null;
    if (this.shadowRoot) this.shadowRoot.innerHTML = "";
  }

  getCardSize() {
    return 8;
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
        <div class="header"><img hidden><h2></h2></div>
        <div class="controls">
          <label>${t.speaker}</label><div class="speaker"></div>
          <div class="keep"><div>${t.keep}<small>${t.keepHint}</small></div><ha-switch></ha-switch></div>
        </div>
        <div class="now" hidden>
          <img><div class="title"></div><div class="artist"></div>
          <div class="buttons">
            <button class="icon" data-act="prev" title="Previous">${svg(ICONS.prev)}</button>
            <button class="icon primary" data-act="playpause">${svg(ICONS.pause)}</button>
            <button class="icon" data-act="next" title="Next">${svg(ICONS.next)}</button>
            <button class="icon" data-act="stop" title="Stop">${svg(ICONS.stop)}</button>
          </div>
          <div class="upnext" hidden><span></span><button class="text" data-act="clear">${t.clear}</button></div>
        </div>
        <div class="search" ${this._config.show ? "hidden" : ""}><input type="search" placeholder="${t.search}"></div>
        <div class="nav" hidden><button class="icon" data-act="back" title="${t.back}">${svg(ICONS.back)}</button><span class="crumb"></span></div>
        <div class="list"><div class="msg">${t.loading}</div></div>
      </ha-card>`;
    this._el = (sel) => root.querySelector(sel);

    root.querySelector(".now .buttons").addEventListener("click", (ev) => this._control(ev));
    root.querySelector(".upnext").addEventListener("click", (ev) => this._control(ev));
    root.querySelector(".nav").addEventListener("click", () => this._back());
    root.querySelector("ha-switch").addEventListener("change", (ev) => {
      const on = ev.target.checked;
      this._call("switch", on ? "turn_on" : "turn_off", {}, this._sibling("switch", "switch.nrk_radio_keep_playing"));
    });
    const input = root.querySelector("input[type=search]");
    input.addEventListener("input", () => {
      clearTimeout(this._debounce);
      this._debounce = setTimeout(() => this._search(input.value.trim()), 350);
    });
    root.querySelector(".list").addEventListener("click", (ev) => this._rowClick(ev));
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
      this._render();
    } catch (err) {
      this._showMessage(`${this._t.error}: ${err.message || err}`);
    }
  }

  _showMessage(text) {
    const list = this._el(".list");
    list.innerHTML = "";
    const div = document.createElement("div");
    div.className = "msg";
    div.textContent = text;
    list.appendChild(div);
  }

  _render() {
    const node = this._results || this._stack[this._stack.length - 1];
    if (!node) return;
    const header = this._stack[0];
    this._el(".header h2").textContent = this._config.title || (this._config.show ? header.title : "NRK Radio");
    const img = this._el(".header img");
    img.hidden = !(this._config.show && header.thumbnail);
    if (!img.hidden) img.src = header.thumbnail;

    const nav = this._el(".nav");
    nav.hidden = !(this._results || this._stack.length > 1);
    this._el(".nav .crumb").textContent = node.title;

    const children = node.children || [];
    if (!children.length) {
      this._showMessage(this._results ? this._t.noResults : this._t.empty);
      return;
    }
    const list = this._el(".list");
    list.innerHTML = "";
    for (const child of children) {
      const row = document.createElement("div");
      row.className = "row" + (child.can_expand ? " expand" : "");
      row.dataset.id = child.media_content_id;
      row.dataset.ref = refOf(child.media_content_id);
      row.dataset.live = child.media_class === "channel" ? "1" : "";
      const thumb = child.thumbnail ? document.createElement("img") : document.createElement("div");
      if (child.thumbnail) {
        thumb.src = child.thumbnail;
        thumb.loading = "lazy";
      } else {
        thumb.className = "noimg";
        thumb.innerHTML = svg(child.media_class === "channel" ? ICONS.radio : ICONS.folder);
      }
      const text = document.createElement("div");
      text.className = "text";
      const title = document.createElement("div");
      title.className = "t";
      title.textContent = child.title;
      const badge = document.createElement("div");
      badge.className = "badge";
      text.append(title, badge);
      const actions = document.createElement("div");
      actions.className = "actions";
      row.append(thumb, text, actions);
      row._child = child;
      list.appendChild(row);
    }
    list.scrollTop = 0;
    this._updateRows();
  }

  _player() {
    return this._hass.states[this._config.entity];
  }

  _queueInfo() {
    const player = this._player();
    const queue = player?.attributes.queue || [];
    const pos = player?.attributes.queue_position ?? -1;
    return { player, queue, pos, active: player && ACTIVE.includes(player.state) && this._onOurSpeaker(player) };
  }

  _onOurSpeaker(player) {
    return !this._config.speaker || player.attributes.speaker === this._config.speaker;
  }

  _update() {
    if (!this._built) return;
    const t = this._t;
    const { player, queue, pos, active } = this._queueInfo();
    if (!player) {
      this._showMessage(t.missing);
      return;
    }

    // Speaker: fixed by config, or a dropdown over the integration's select.
    const box = this._el(".speaker");
    if (this._config.speaker) {
      const name = this._hass.states[this._config.speaker]?.attributes.friendly_name || this._config.speaker;
      if (box.textContent !== name) { box.className = "speaker speaker-fixed"; box.textContent = name; }
    } else {
      const selectId = this._sibling("select", "select.nrk_radio_speaker");
      const sel = this._hass.states[selectId];
      let el = box.querySelector("select");
      if (!el) {
        el = document.createElement("select");
        el.addEventListener("change", () => this._call("select", "select_option", { option: el.value }, selectId));
        box.appendChild(el);
      }
      const options = sel?.attributes.options || [];
      if (el.dataset.opts !== options.join("|")) {
        el.innerHTML = "";
        for (const o of options) { const opt = document.createElement("option"); opt.textContent = o; el.appendChild(opt); }
        el.dataset.opts = options.join("|");
      }
      if (sel && el.value !== sel.state) el.value = sel.state;
    }

    const sw = this._el("ha-switch");
    const keep = this._hass.states[this._sibling("switch", "switch.nrk_radio_keep_playing")];
    sw.checked = keep?.state === "on";

    // Now playing
    const now = this._el(".now");
    now.hidden = !active;
    if (active) {
      const a = player.attributes;
      this._el(".now .title").textContent = a.media_title || "";
      this._el(".now .artist").textContent = a.media_channel || a.media_artist || "";
      const img = this._el(".now img");
      if (a.entity_picture && img.getAttribute("src") !== a.entity_picture) img.src = a.entity_picture;
      this._el('[data-act="playpause"]').innerHTML = svg(player.state === "playing" ? ICONS.pause : ICONS.play);
      const upcoming = queue.slice(pos + 1);
      const upnext = this._el(".upnext");
      upnext.hidden = !upcoming.length;
      if (upcoming.length) {
        upnext.querySelector("span").textContent =
          `${t.next}: ${upcoming[0].title}` + (upcoming.length > 1 ? ` (+${upcoming.length - 1})` : "");
      }
    }
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
      row.querySelector(".badge").textContent = queuePos !== undefined ? `${t.queued} #${queuePos - pos}` : "";
      const actions = row.querySelector(".actions");
      if (actions.dataset.state === state) continue;
      actions.dataset.state = state;
      const buttons = {
        none: "",
        play: `<button class="icon primary" data-act="play" title="${t.play}">${svg(ICONS.play)}</button>`,
        add: `<button class="icon primary" data-act="add" title="${t.queue}">${svg(ICONS.add)}</button>`,
        queued: `<button class="icon" data-act="remove" title="${t.remove}">${svg(ICONS.remove)}</button>`,
        pause: `<button class="icon primary" data-act="pause" title="${t.pause}">${svg(ICONS.pause)}</button>`,
        resume: `<button class="icon primary" data-act="resume" title="${t.resume}">${svg(ICONS.play)}</button>`,
      }[state];
      actions.innerHTML = buttons + (child.can_expand ? `<span class="chev">${svg(ICONS.chevron)}</span>` : "");
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
    const extra = this._config.speaker ? { speaker: this._config.speaker } : {};
    const media = { media_content_id: row.dataset.id, media_content_type: "music", extra };
    if (act === "play") this._call("media_player", "play_media", media);
    else if (act === "add") this._call("media_player", "play_media", { ...media, enqueue: "add" });
    else if (act === "pause") this._call("media_player", "media_pause");
    else if (act === "resume") this._call("media_player", "media_play");
    else if (act === "remove") {
      const { queue, pos } = this._queueInfo();
      const index = queue.findIndex((item, i) => i > pos && item.id === row.dataset.ref);
      if (index > pos) this._call("nrk_radio", "remove_from_queue", { position: index });
    }
  }

  _control(ev) {
    const act = ev.target.closest("button")?.dataset.act;
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
