// UI polish, loaded last: a real Mars logo, a progress bar and "routes ready" card for missions, point details as a
// readable card, scrollable layer chips, and the active rail item marked. Only adds to the page; every control
// keeps working the same way without this file.
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
  const map = $("map");
  const touring = () => document.body.classList.contains("touring");

  // Logo: the Mars disk; click = whole planet
  const logo = document.querySelector("#gmRail .logo");
  if (logo) {
    logo.replaceChildren(el("img", { src: "mars-disk.webp", alt: "" }));
    logo.setAttribute("role", "button");
    logo.tabIndex = 0;
    logo.title = "Marswalk Planner: show the whole planet";
    const whole = () => $("wholeMars")?.click();
    logo.addEventListener("click", whole);
    logo.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); whole(); } });
  }

  // Planning: a thin progress bar on top of the map and a status pill under the search bar
  const bar = el("div", { id: "uiProgress", hidden: true });
  const pill = el("div", { id: "uiPill", hidden: true, role: "status" });
  map.append(bar, pill);
  const run = $("runMission");
  let planning = false, before = null;
  function syncPlanning() {
    const busy = !!run?.disabled;
    if (busy === planning) return;
    planning = busy;
    bar.hidden = !busy;
    pill.hidden = !busy || touring();
    if (busy) { before = mission; pill.textContent = "Planning your Marswalk…"; }
    else setTimeout(() => announce(before), 400);
  }
  if (run) new MutationObserver(syncPlanning).observe(run, { attributes: true, attributeFilter: ["disabled"] });
  new MutationObserver(() => { if (planning && !touring()) pill.textContent = $("mStatus")?.innerText.split("\n")[0].slice(0, 90) || pill.textContent; })
    .observe($("mStatus"), { childList: true, subtree: true, characterData: true });

  // Routes ready: a card at the bottom with the best route and the next steps
  const card = el("div", { id: "uiReady", hidden: true, role: "status" });
  map.append(card);
  let hideTimer = 0;
  function announce(prev) {
    const c = mission?.candidates;
    if (!c?.length || mission === prev || touring()) return;
    const r = c[0].route || {}, s = c[0].safety || {};
    const btn = (text, fn, cls = "") => el("button", { type: "button", textContent: text, className: cls,
      onclick: () => { fn(); card.hidden = true; } });
    card.replaceChildren(
      el("div", { className: "t" }, `${c.length} safe route${c.length > 1 ? "s" : ""} found`),
      el("div", { className: "s" }, `Best: ${r.distance_km} km · ${r.round_trip_h} h round trip` +
        (s.shelter_min != null ? ` · shelter ≤ ${Math.round(s.shelter_min)} min` : "")),
      el("div", { className: "b" },
        btn("See results", () => document.querySelector('#gmRail button[data-section="missionResults"]')?.click()),
        btn("Play route", () => { if (!$("playRoute").disabled) $("playRoute").click(); }, "ghost"),
        btn("Walker's view", () => { if (!$("walkerView").hidden) $("walkerView").click(); }, "ghost")),
      el("button", { type: "button", className: "x", textContent: "×", title: "Dismiss", onclick: () => { card.hidden = true; } }));
    card.hidden = false;
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { card.hidden = true; }, 12000);
  }

  // Point details: one row per "name: value" line, in a card
  const info = $("info");
  if (info) {
    let busy = false;
    new MutationObserver(() => {
      if (busy || !info.textContent.includes(":") || info.querySelector(".kv")) return;
      busy = true;
      const lines = info.innerText.split("\n").map(s => s.trim()).filter(Boolean);
      const rows = lines.map(l => {
        const i = l.indexOf(":");
        if (i <= 0 || i > 28) return el("div", { className: "head", textContent: l });
        return el("div", { className: "kv" }, el("span", { textContent: l.slice(0, i) }), el("b", { textContent: l.slice(i + 1).trim() }));
      });
      info.replaceChildren(...rows);
      info.classList.add("card");
      busy = false;
    }).observe(info, { childList: true, subtree: true, characterData: true });
  }

  // Layer chips: scroll sideways with the mouse wheel; fade at the edge when there are more
  const chips = $("gmChips");
  if (chips) {
    chips.addEventListener("wheel", e => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { chips.scrollLeft += e.deltaY; e.preventDefault(); }
    }, { passive: false });
    const fade = () => chips.classList.toggle("more", chips.scrollLeft + chips.clientWidth < chips.scrollWidth - 4);
    chips.addEventListener("scroll", fade);
    new ResizeObserver(fade).observe(chips);
    fade();
  }
})();
