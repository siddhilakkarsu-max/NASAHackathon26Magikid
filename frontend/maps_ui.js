// Map-first layout, like a street map: the map fills the window; an icon rail on the left opens the planner's
// panel as a slide-out drawer at the right section; round buttons on the map (zoom, north, whole planet);
// one-tap layer chips under the search bar; and a chat assistant (POST /api/assistant) that asks what it needs and
// drives the map. Loaded after index.html's main script and map_help.js; it only presses the planner's own controls.
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
  const svg = (paths) => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.innerHTML = paths; return s; };
  const ICON = {
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    chat: '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/>',
    route: '<circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="6" r="2.2"/><path d="M8 18h6.5a3.5 3.5 0 0 0 0-7h-5a3.5 3.5 0 0 1 0-7H16"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    layers: '<path d="M12 3 2.5 8 12 13l9.5-5z"/><path d="m2.5 12.5 9.5 5 9.5-5"/><path d="m2.5 16.5 9.5 5 9.5-5"/>',
    grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1"/><rect x="13.5" y="3.5" width="7" height="7" rx="1"/><rect x="3.5" y="13.5" width="7" height="7" rx="1"/><rect x="13.5" y="13.5" width="7" height="7" rx="1"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    pin: '<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.5v.6"/><circle cx="12" cy="16.8" r=".6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>', minus: '<path d="M5 12h14"/>',
    compass: '<path d="M12 3 15 12h-6z" fill="#e0703a" stroke="#e0703a"/><path d="M12 21 9 12h6z"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 2.6 14.6 0 17M12 3.5c-2.6 2.4-2.6 14.6 0 17"/>',
    radiation: '<circle cx="12" cy="12" r="1.8"/><path d="M12 4a8 8 0 0 1 6.9 4l-4.3 2.5M5.1 8A8 8 0 0 1 12 4v5M8.6 19.4l2.5-4.4M15.4 19.4 12.9 15"/>',
    thermo: '<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/>',
    wind: '<path d="M3 9h11a2.5 2.5 0 1 0-2.5-2.5M3 15h14a2.5 2.5 0 1 1-2.5 2.5M3 12h7"/>',
    gem: '<path d="M6 4h12l3 5-9 11L3 9z"/><path d="M3 9h18M9 4l3 16 3-16"/>',
    tracks: '<path d="M6 21c0-6 4-7 4-12S8 3 8 3M16 21c0-6-2-7-2-12s2-6 2-6"/>',
    photo: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-8 8"/>',
    rocket: '<path d="M14.5 4.5c2.6-1.3 5-1.2 5-1.2s.1 2.4-1.2 5l-5.6 5.6-3.6-3.6z"/><path d="m9.1 10.3-3.4-.4-2.2 2.2 3.8 1.2M13.7 14.9l.4 3.4-2.2 2.2-1.2-3.8"/><circle cx="15.4" cy="8.6" r="1.4"/><path d="M6.5 17.5 4 20M8.5 18.5l-1.5 1.5M5.5 15.5 4 17"/>',
    gamepad: '<path d="M7 7h10a4.5 4.5 0 0 1 4.4 5.5l-.9 4a2.5 2.5 0 0 1-4.3 1.1L14.5 16h-5l-1.7 1.6a2.5 2.5 0 0 1-4.3-1.1l-.9-4A4.5 4.5 0 0 1 7 7z"/><path d="M8 10v3M6.5 11.5h3"/><circle cx="15.5" cy="10.8" r=".7"/><circle cx="17" cy="12.6" r=".7"/>',
    foldmap: '<path d="M3.5 6.5 9 4l6 2.5L20.5 4v13.5L15 20l-6-2.5-5.5 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>',
    scan: '<path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><circle cx="11" cy="11" r="3.2"/><path d="m13.4 13.4 3.1 3.1"/>',
    book: '<path d="M12 6.5C10 5 6.5 4.5 3.5 5v13c3-.5 6.5 0 8.5 1.5 2-1.5 5.5-2 8.5-1.5V5c-3-.5-6.5 0-8.5 1.5z"/><path d="M12 6.5v13"/>',
    pin2: '<path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="3"/><circle cx="12" cy="10" r="1.2"/>',
    key: '<circle cx="8" cy="15" r="3.5"/><path d="m10.5 12.5 8-8M16 7l2.5 2.5M14 9l2 2"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  };
  document.body.classList.add("gm");
  const map = $("map"), panel = $("panel");

  // ------------------------------------------------------------- drawer + rail ----
  const closeX = el("button", { id: "drawerClose", type: "button", textContent: "×", title: "Close panel" });
  closeX.setAttribute("aria-label", "Close panel");
  closeX.onclick = () => drawer(false);
  panel.prepend(closeX);
  const rail = el("nav", { id: "gmRail" });
  rail.setAttribute("aria-label", "Planner tools");
  document.body.append(rail);
  let openSection = null;
  // Each rail button shows ONLY its own section (plus what that section needs, e.g. the region picker for Plan);
  // Menu shows the whole panel.
  const COMPANIONS = { missionSetup: ["panelPlace", "mStatus"], globalMaps: ["mapKey"], regionalMaps: ["mapKey"] };
  function solo(sectionId) {
    for (const n of panel.querySelectorAll(".soloKeep")) n.classList.remove("soloKeep");
    if (!sectionId || sectionId === "all") { delete panel.dataset.solo; return; }
    panel.dataset.solo = sectionId;
    for (const id of [sectionId, ...(COMPANIONS[sectionId] || [])]) $(id)?.classList.add("soloKeep");
  }
  function drawer(on, sectionId = null) {
    document.body.classList.toggle("drawer", on);
    openSection = on ? sectionId || "all" : null;
    solo(on ? openSection : null);
    for (const b of rail.querySelectorAll("button[data-section]")) b.classList.toggle("on", on && b.dataset.section === openSection);
    if (on && sectionId && sectionId !== "all") {
      const sec = $(sectionId);
      if (sec) {
        sec.hidden = false;
        sec.open = true;
        setTimeout(() => sec.scrollIntoView({ block: "start", behavior: "smooth" }), 230);
      }
    } else if (on) panel.scrollTop = 0;
    setTimeout(() => window.viewer?.scene.requestRender(), 250);
  }
  const railBtn = (icon, label, onclick, section) => {
    const b = el("button", { type: "button", title: label, onclick }, svg(ICON[icon]), el("span", { textContent: label }));
    if (section) b.dataset.section = section;
    rail.append(b);
    return b;
  };
  const toggle = (section) => () => (openSection === section ? drawer(false) : drawer(true, section));
  rail.append(el("div", { className: "logo", title: "Marswalk Planner" }));
  railBtn("menu", "Menu", toggle("all"), "all");
  railBtn("chat", "Assistant", () => chat.open(true));
  railBtn("route", "Plan", toggle("missionSetup"), "missionSetup");
  const resultsBtn = railBtn("list", "Results", toggle("missionResults"), "missionResults");
  railBtn("layers", "Layers", toggle("globalMaps"), "globalMaps");
  railBtn("grid", "Area data", toggle("regionalMaps"), "regionalMaps");
  railBtn("clock", "Time", toggle("conditionsPanel"), "conditionsPanel");
  railBtn("pin", "Point info", toggle("pointDetails"), "pointDetails");
  railBtn("gamepad", "Game", toggle("gameSection"), "gameSection");
  railBtn("book", "Sources", toggle("sourcesSection"), "sourcesSection");
  rail.append(el("div", { className: "grow" }));
  railBtn("help", "Help", () => window.openMapManual?.());
  const syncResults = () => {
    resultsBtn.disabled = $("missionResults").hidden;
    const game = rail.querySelector('button[data-section="gameSection"]');
    if (game) game.disabled = !$("gameSection") || $("gameSection").hidden;
  };
  new MutationObserver(syncResults).observe($("missionResults"), { attributes: true, attributeFilter: ["hidden"] });
  syncResults();
  // A click on the map shows the point's values: open the drawer there, like a place card.
  const info = $("info");
  if (info) new MutationObserver(() => {
    if (/Click the map/.test(info.textContent) || openSection === "pointDetails") return;
    if (!document.body.classList.contains("drawer")) drawer(true, "pointDetails");
  }).observe(info, { childList: true, subtree: true, characterData: true });

  // ------------------------------------------------- panel design (team mock-up) ----
  // Chamfered section cards with a line icon, thin spaced capitals and a V chevron; "MARSWALK PLANNER" between
  // copper rules. The region picker and its buttons are grouped as #panelPlace; the sources button and its list
  // become #sourcesSection so each can be shown alone from the rail.
  const fonts = el("link", { rel: "stylesheet",
    href: "https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&display=swap" });
  document.head.append(fonts);
  const h1 = panel.querySelector("h1");
  if (h1) h1.textContent = "Marswalk Planner";
  (() => {
    const start = $("helpOpen") || h1, end = $("missionSetup");
    if (!start || !end || $("panelPlace")) return;
    const group = el("div", { id: "panelPlace" });
    let n = start.nextSibling;
    const move = [];
    while (n && n !== end) { move.push(n); n = n.nextSibling; }
    end.before(group);
    group.append(...move);
  })();
  (() => {
    const b = $("sourcesButton"), list = $("sourcesPanel");
    if (!b || !list || $("sourcesSection")) return;
    const wrap = el("div", { id: "sourcesSection", className: "sourcesCard" });
    b.before(wrap);
    wrap.append(b, list);
  })();
  const SECTION_ICONS = { missionSetup: "rocket", manual: "route", missionResults: "list", gameSection: "gamepad",
    conditionsPanel: "sun", globalMaps: "foldmap", regionalMaps: "pin2", mapKey: "key", pointDetails: "scan" };
  function decorate() {
    for (const [id, icon] of Object.entries(SECTION_ICONS)) {
      const s = document.querySelector(`#${id} > summary`);
      if (!s || s.querySelector(".secIcon")) continue;
      const label = el("span", { className: "secLabel" });
      label.append(...[...s.childNodes].filter(n => !(n.classList && n.classList.contains("secHelp"))));
      s.prepend(el("span", { className: "secIcon" }, svg(ICON[icon])), label);
    }
    const sb = $("sourcesButton");
    if (sb && !sb.querySelector(".secIcon")) {
      const label = el("span", { className: "secLabel", textContent: sb.textContent.trim() });
      sb.replaceChildren(el("span", { className: "secIcon" }, svg(ICON.book)), label);
    }
  }
  decorate();
  new MutationObserver(() => { decorate(); syncResults(); }).observe(panel, { childList: true });

  // ----------------------------------------------------------- map buttons ----
  const camera = () => viewer.camera;
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const ctl = el("div", { id: "gmControls" });
  const btn = (icon, title, onclick, cls = "") => {
    const b = el("button", { type: "button", title, onclick, className: cls }, svg(ICON[icon]));
    b.setAttribute("aria-label", title);
    return b;
  };
  const height = () => camera().positionCartographic.height;
  ctl.append(
    btn("compass", "Point north", () => camera().flyTo({ destination: camera().positionWC.clone(),
      orientation: { heading: 0, pitch: camera().pitch, roll: 0 }, duration: reduced() ? 0 : 0.8 }), "solo"),
    btn("globe", "Whole Mars", () => $("wholeMars").click(), "solo"),
    el("div", { className: "stack" },
      btn("plus", "Zoom in", () => camera().zoomIn(height() * 0.5)),
      btn("minus", "Zoom out", () => camera().zoomOut(height() * 0.8))));
  map.append(ctl);

  // ----------------------------------------------------------- layer chips ----
  function layerSelect(id) {
    if (id.startsWith("map:") || [...($("globalWeather")?.children || [])].some(o => o.value === id)) return $("globalLayer");
    return $("regionalLayer");
  }
  function setLayer(id) {
    if (!id) {
      for (const s of ["regionalLayer", "globalLayer"]) if ($(s).value) { $(s).value = ""; $(s).dispatchEvent(new Event("change")); }
      return true;
    }
    const s = layerSelect(id);
    if (![...s.options].some(o => o.value === id && !o.disabled)) return false;
    s.value = id;
    s.dispatchEvent(new Event("change"));
    return true;
  }
  const currentLayer = () => plannerLayout.globalChoice() || $("layer").value;
  const chipsBar = el("div", { id: "gmChips" });
  const CHIPS = [
    ["radiation", "Radiation", "radiation_dose"], ["thermo", "Temperature", "global_temperature"],
    ["wind", "Wind", "wind_direction"], ["gem", "Minerals", "science"], ["sun", "Sunlight", "illumination"],
    ["photo", "Sharp photos", "map:ctx"],
    ["tracks", "Rover tracks", () => $("showTracks").click(), () => $("showTracks").checked],
  ];
  const chipEls = CHIPS.map(([icon, label, act, isOn]) => {
    const b = el("button", { type: "button" }, svg(ICON[icon]), label);
    b.onclick = () => {
      if (typeof act === "function") act();
      else if (!setLayer(currentLayer() === act ? "" : act)) chat.say(`${label} isn't available for this area yet: pick a region first.`);
      setTimeout(syncChips, 50);
    };
    b._on = typeof act === "function" ? isOn : () => currentLayer() === act;
    chipsBar.append(b);
    return b;
  });
  function syncChips() { for (const b of chipEls) b.classList.toggle("on", !!b._on()); }
  $("layer").addEventListener("change", () => setTimeout(syncChips, 0));
  for (const s of ["globalLayer", "regionalLayer", "showTracks"]) $(s).addEventListener("change", () => setTimeout(syncChips, 0));
  camera().moveEnd.addEventListener(syncChips);
  map.append(chipsBar);

  // --------------------------------------------------------------- assistant ----
  const search = $("marsSearch");
  const log = el("div", { className: "log", role: "log" });
  const chipBox = el("div", { className: "chips" });
  const replyIn = el("input", { type: "text", placeholder: "Reply or ask anything…", autocomplete: "off" });
  replyIn.setAttribute("aria-label", "Message to the planner assistant");
  const form = el("form", {}, replyIn, el("button", { type: "submit", textContent: "Send" }));
  const box = el("section", { id: "gmChat", hidden: true },
    el("header", {}, svg(ICON.chat), el("span", { textContent: "Planner assistant" }),
      el("button", { type: "button", textContent: "×", title: "Close", onclick: () => chat.open(false) })),
    log, chipBox, form);
  box.setAttribute("aria-label", "Planner assistant");
  (search || map).append(box);
  const history = [];
  let memo = {}, busy = false;

  function add(role, text, cls = "") {
    const m = el("div", { className: `msg ${role === "user" ? "user" : "bot"} ${cls}`, textContent: text });
    log.append(m);
    log.scrollTop = log.scrollHeight;
    return m;
  }
  function setChips(list) {
    chipBox.replaceChildren(...(list || []).map(t => el("button", { type: "button", textContent: t, onclick: () => chat.send(t) })));
  }
  function state() {
    const places = window.marsSearchPlaces ? window.marsSearchPlaces().map(p => p.name) : [];
    return { region: $("region").selectedOptions[0]?.textContent || "", hour: +$("hour").value,
             vehicle: $("mVehicle").value, priority: $("mPriority").value, ls: +$("ls").value,
             has_mission: !!mission?.candidates?.length, candidates: mission?.candidates?.length || 0,
             selected_route: mission?.candidates?.length ? selected + 1 : null, places };
  }
  const setInput = (id, v) => { const n = $(id); n.value = v; n.dispatchEvent(new Event("input", { bubbles: true }));
                                n.dispatchEvent(new Event("change", { bubbles: true })); };
  async function act(a) {
    switch (a.type) {
      case "set_goal": $("goal").value = a.goal || ""; break;
      case "set_time": setInput("hour", a.hour); break;
      case "set_season": setInput("ls", a.ls); break;
      case "set_vehicle": setInput("mVehicle", a.vehicle); break;
      case "set_priority": setInput("mPriority", a.priority); break;
      case "go_to": {
        const want = String(a.place || "").toLowerCase();
        const p = (window.marsSearchPlaces?.() || []).find(x => x.name.toLowerCase() === want)
               || (window.marsSearchPlaces?.() || []).find(x => x.name.toLowerCase().includes(want));
        if (p) p.act(); else add("bot", `I couldn't find "${a.place}" on the map.`);
        break;
      }
      case "plan_mission": $("runMission").click(); break;
      case "walker_view": if (!$("walkerView").hidden) $("walkerView").click(); break;
      case "play_route": if (!$("playRoute").disabled) $("playRoute").click(); break;
      case "select_option": if (mission?.candidates?.[a.n - 1]) selectRoute(a.n - 1); break;
      case "show_layer": if (!setLayer(a.layer || "")) add("bot", "That layer isn't available for this area: pick a region first."); break;
      case "whole_mars": $("wholeMars").click(); break;
      case "open_help": window.openMapManual?.(); break;
    }
    syncChips();
  }
  async function waitForMission(before) {
    const note = add("bot", "Planning… (about 10–40 seconds)", "wait");
    const t0 = Date.now();
    while (Date.now() - t0 < 180000) {
      await new Promise(r => setTimeout(r, 1000));
      if (mission && mission !== before && mission.candidates) break;
      const status = $("mStatus").textContent;
      if (!$("runMission").disabled && Date.now() - t0 > 3000 && status && !mission?.candidates) {
        note.remove();
        add("bot", `The planner says: ${status}`);
        return;
      }
    }
    note.remove();
    const c = mission?.candidates;
    if (!c?.length || mission === before) {
      add("bot", "No safe route came back for that. Try another place, goal or vehicle.");
      return;
    }
    const best = c[0], r = best.route || {}, s = best.safety || {};
    const lines = [`Found ${c.length} route${c.length > 1 ? "s" : ""}. The best one is ${r.distance_km} km, about ` +
                   `${r.round_trip_h} h there and back.`];
    if (s.shelter_text) lines.push(`Storm shelter: ${s.shelter_text}.`);
    if (s.walkback_text) lines.push(`If the vehicle breaks: ${s.walkback_text}.`);
    lines.push("Want to play the route, or stand on the ground with Walker's view?");
    add("bot", lines.join("\n"));
    setChips(["Walker's view", "Play route", "Show radiation", "Try the afternoon"]);
  }

  const chat = {
    open(on = true) {
      box.hidden = !on;
      document.body.classList.toggle("chat", on);
      if (on) {
        if (!log.children.length) {
          add("bot", "Hi! Tell me what you want to do on Mars, like \"find clay where water once flowed\", and I'll " +
                     "plan a safe Marswalk. Ask me to fly somewhere, show radiation, or play your route.");
          setChips(["Find clay where water once flowed", "Go to Gale crater", "Show radiation", "How to use this map"]);
        }
        replyIn.focus();
      }
    },
    say(text) { chat.open(true); add("bot", text); },
    async send(text) {
      text = String(text || "").trim();
      if (!text || busy) return;
      chat.open(true);
      busy = true;
      add("user", text);
      history.push({ role: "user", text });
      setChips([]);
      const thinking = add("bot", "…", "wait");
      let out;
      try {
        const res = await fetch("/api/assistant", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: history.slice(-20), state: state(), memo }) });
        if (!res.ok) throw new Error(`server error ${res.status}`);
        out = await res.json();
      } catch (e) {
        thinking.remove();
        add("bot", `I couldn't reach the planner (${e.message}).`);
        busy = false;
        return;
      }
      thinking.remove();
      memo = out.memo || memo;
      add("bot", out.reply);
      history.push({ role: "assistant", text: out.reply });
      setChips(out.chips);
      const before = mission;
      for (const a of out.actions || []) await act(a);
      busy = false;
      if (out.wait_for_mission) waitForMission(before);
    },
  };
  form.onsubmit = (e) => { e.preventDefault(); const t = replyIn.value; replyIn.value = ""; chat.send(t); };
  window.marsAssistant = chat;
})();
