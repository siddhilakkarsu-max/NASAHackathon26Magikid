// Declutter: the planner's panels show controls and live status first; explanations wait behind a small ⓘ.
//
// Loaded last (defer). It changes only what is shown, never the planner's text or behaviour:
//   * REMOVE: lines that repeat what a heading, label or placeholder already says are hidden for good.
//   * TIPS:   useful notes are folded behind an ⓘ on the nearest label or heading; click it to read them.
//             Notes that double as status lines (moon status, sharp-photo box) are folded only while they show
//             their default explanation; errors and step-by-step instructions stay visible.
//   * Mission results: the "mineral maps cover N% of this area" notes fold behind "ⓘ N data notes".
// The text stays in index.html, so tests still find it; folded notes are display:none (also for screen readers)
// until their ⓘ is opened. Each ⓘ has aria-expanded and aria-controls pointing at its notes.
(() => {
  "use strict";
  if (window.marsDeclutter) return;
  const $ = (id) => document.getElementById(id);
  const txt = (n) => (n?.textContent || "").replace(/\s+/g, " ").trim();

  const style = document.createElement("style");
  style.textContent = `
    .dc-gone { display: none !important; }
    .dc-tip:not(.dc-open) { display: none !important; }
    .dc-tip.dc-open { animation: dcIn .22s ease-out; }
    @keyframes dcIn { from { opacity: 0; transform: translateY(-3px); } to { opacity: 1; transform: none; } }
    .dc-i { display: inline-grid !important; place-items: center; width: 17px !important; height: 17px !important;
            min-height: 0 !important; margin: 0 0 0 6px !important; padding: 0 !important; border-radius: 50% !important;
            border: 1px solid #ffffff40 !important; background: transparent !important; color: #c9b8ab !important;
            font: italic 700 11px/1 Georgia, serif !important; letter-spacing: 0 !important; text-transform: none !important;
            vertical-align: 1px; cursor: pointer; flex: none; }
    .dc-i:hover { border-color: #e0703a !important; color: #fff !important; background: #e0703a33 !important; }
    .dc-i[aria-expanded="true"] { background: #e0703a !important; border-color: #e0703a !important; color: #fff !important; }
    .dc-i.dc-wide { width: auto !important; padding: 0 7px !important; border-radius: 9px !important;
                    font-family: inherit !important; font-size: 10.5px !important; font-weight: 600 !important;
                    line-height: 17px !important; font-style: normal !important; }
    .dc-i[hidden] { display: none !important; }
    summary .dc-i { margin-left: 8px !important; }
    @media (prefers-reduced-motion: reduce) { .dc-tip.dc-open { animation: none; } }`;
  document.head.append(style);

  // Lines that only repeat the heading / label / placeholder next to them
  const REMOVE = [
    ["#panelPlace > p.small, #panel > p.small", /^Plan a mission, or open Mars global maps to explore/],
    ["#missionSetup > p.small", /^Describe what you want to visit/],
    ["#conditionsPanel > p.small", /^Shared by mission planning, weather layers and globe lighting/],
    ["#globalMaps > p.small", /^Choose one planet-wide view/],
    ["#regionalMaps > p.small", /^Inspect the selected area's terrain/],
  ];
  // Useful notes, folded behind an ⓘ on an anchor. `only`: fold only while the text matches (status lines).
  const TIPS = [
    { sel: "#regionHint", anchor: () => $("regionPicker") },
    // #areaStatus also carries live loading progress and errors ("couldn't load… retry"): fold only its default note
    { sel: "#areaStatus", anchor: () => $("regionPicker"), only: /^Plan anywhere on Mars:/ },
    { sel: "#lightingNote", anchor: () => $("globeLighting")?.closest("label") },
    { sel: "#moonSyncNote", anchor: () => $("moonControls")?.querySelector(":scope > summary") },
    { sel: "#moonStatus", anchor: () => $("moonControls")?.querySelector(":scope > summary"),
      only: /^(Real sizes and distances|Moons hidden\.)/ },
    { sel: "#dustHazeNote", anchor: () => $("showDustHaze")?.closest("label") },
    { sel: "#regionalMaps > p.small", anchor: (n) => prevMatching(n, "h2"), match: /^Photo boxes can overlay/ },
    { sel: "#boxInfo", anchor: (n) => prevMatching(n, "h2"), only: /^Click "Box a sharp area"/ },
    { sel: "#murrayLayers > div.small", anchor: (n) => n.parentElement.querySelector(":scope > .murrayHead"),
      match: /^The photo tile grid follows/ },
    { sel: "#gameSectionNote", anchor: () => $("gameSection")?.querySelector(":scope > summary") },
  ];
  function prevMatching(n, sel) {
    for (let x = n.previousElementSibling; x; x = x.previousElementSibling) if (x.matches(sel)) return x;
    return null;
  }

  // one ⓘ per anchor; it opens/closes every tip attached to that anchor
  const toggles = new WeakMap();      // anchor -> { button, tips:Set }
  let uid = 0;
  function toggleFor(anchor, label = "i", wide = false) {
    let t = toggles.get(anchor);
    if (t && t.button.isConnected) return t;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dc-i" + (wide ? " dc-wide" : "");
    button.textContent = label;
    button.setAttribute("aria-expanded", "false");
    button.title = "More about this";
    button.setAttribute("aria-label", "More about " + (txt(anchor).slice(0, 40) || "this"));
    button.addEventListener("click", (e) => {
      e.preventDefault();             // inside a <summary>: don't open/close the section; inside a <label>: no toggle
      e.stopPropagation();
      const open = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(open));
      for (const tip of t.tips) if (tip.isConnected) tip.classList.toggle("dc-open", open);
    });
    // next to the anchor's words: inside a section title, or before a full-width dropdown/field in a label
    const host = anchor.matches("summary") ? (anchor.querySelector(".secLabel") || anchor) : anchor;
    const field = anchor.matches("label") && anchor.querySelector("select, textarea, input:not([type=checkbox]):not([type=radio])");
    field ? field.before(button) : host.append(button);
    t = { button, tips: new Set() };
    toggles.set(anchor, t);
    return t;
  }
  function fold(tip, anchor) {
    if (!anchor) return;
    const t = toggleFor(anchor);
    if (!tip.id) tip.id = "dcTip" + ++uid;
    t.tips.add(tip);
    tip.classList.add("dc-tip");
    tip.classList.toggle("dc-open", t.button.getAttribute("aria-expanded") === "true");
    t.button.setAttribute("aria-controls", [...t.tips].filter(x => x.isConnected).map(x => x.id).join(" "));
    t.button.hidden = false;
  }
  function unfold(tip, anchor) {
    tip.classList.remove("dc-tip", "dc-open");
    const t = anchor && toggles.get(anchor);
    if (!t) return;
    t.tips.delete(tip);
    if (![...t.tips].some(x => x.isConnected && x.classList.contains("dc-tip"))) t.button.hidden = true;
  }

  // Mission results: the per-area data notes ("Mineral maps cover 73% of this area…") behind one toggle
  function foldNotices() {
    const out = $("mResult");
    if (!out) return;
    // advanced-mode notes (.adv, .adv-only) are hidden by the planner itself unless asked for: leave them alone
    const notes = [...out.querySelectorAll(':scope > [data-mission-notice="true"]')]
      .filter(n => !n.matches(".adv, .adv-only") && txt(n));
    const summary = out.firstElementChild;
    if (!notes.length || !summary || notes.includes(summary)) return;
    let t = toggles.get(summary);
    if (!t || !t.button.isConnected) {
      t = toggleFor(summary, `${notes.length} data note${notes.length > 1 ? "s" : ""}`, true);
    }
    for (const n of notes) {
      if (!n.id) n.id = "dcTip" + ++uid;
      t.tips.add(n);
      n.classList.add("dc-tip");
    }
    t.button.setAttribute("aria-controls", notes.map(n => n.id).join(" "));
  }

  let busy = false;
  function apply() {
    busy = true;
    try {
      for (const [sel, re] of REMOVE) for (const n of document.querySelectorAll(sel)) if (re.test(txt(n))) n.classList.add("dc-gone");
      for (const tip of TIPS) {
        for (const n of document.querySelectorAll(tip.sel)) {
          if (tip.match && !tip.match.test(txt(n))) continue;
          const anchor = tip.anchor(n);
          if (!txt(n) || (tip.only && !tip.only.test(txt(n)))) unfold(n, anchor);
          else fold(n, anchor);
        }
      }
      foldNotices();
    } finally {
      busy = false;
    }
  }

  // panels are rebuilt and status lines rewritten as the user works: re-apply on the next frame after changes
  let queued = false;
  const schedule = () => {
    if (busy || queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; apply(); });
  };
  const panel = $("panel");
  if (panel) new MutationObserver(schedule).observe(panel, { childList: true, subtree: true, characterData: true });
  apply();

  window.marsDeclutter = { apply };
})();
