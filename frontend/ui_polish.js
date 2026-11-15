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

// ---- second pass: quieter sharp-photo outline, a shorter left bar, one set of route buttons, a first hint ----
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };

  // 1. The sharp-photo box outline: thin dashed line, and only when zoomed in enough to matter
  function quietBox(entity) {
    if (!entity?.polyline || entity.__quiet) return;
    entity.__quiet = true;
    entity.polyline.width = 1.2;
    entity.polyline.material = new Cesium.PolylineDashMaterialProperty({
      color: Cesium.Color.ORANGE.withAlpha(0.55), dashLength: 14 });
    entity.polyline.distanceDisplayCondition = new Cesium.DistanceDisplayCondition(0, 1.2e6);
  }
  viewer.entities.collectionChanged.addEventListener((_, added) => {     // boxEntity is assigned after add()
    if (added.length) setTimeout(() => { if (typeof boxEntity !== "undefined" && boxEntity) quietBox(boxEntity); }, 0);
  });
  if (typeof boxEntity !== "undefined" && boxEntity) quietBox(boxEntity);

  // 2. Left bar: Game lives with Results; Sources, Flythrough, Tour and Help go under "More"
  const rail = $("gmRail");
  if (rail) {
    const find = (t) => [...rail.querySelectorAll("button")].find(b => b.title === t || b.dataset.section === t);
    find("gameSection")?.remove();
    const moved = [find("sourcesSection"), find("10-second flythrough of every feature"), find("Autoplay tour"), find("Help")]
      .filter(Boolean);
    if (moved.length) {
      const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      icon.setAttribute("viewBox", "0 0 24 24"); icon.setAttribute("aria-hidden", "true");
      icon.innerHTML = '<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>';
      const menu = el("div", { id: "uiMore", hidden: true, role: "menu" });
      const more = el("button", { type: "button", title: "More", id: "uiMoreBtn" }, icon, el("span", { textContent: "More" }));
      more.setAttribute("aria-haspopup", "menu");
      more.setAttribute("aria-expanded", "false");
      const close = () => { menu.hidden = true; more.setAttribute("aria-expanded", "false"); more.classList.remove("on"); };
      more.onclick = (e) => {
        e.stopPropagation();
        menu.hidden = !menu.hidden;
        more.setAttribute("aria-expanded", String(!menu.hidden));
        more.classList.toggle("on", !menu.hidden);
      };
      for (const b of moved) {
        b.setAttribute("role", "menuitem");
        b.addEventListener("click", close);
        menu.append(b);
      }
      rail.append(more);
      document.body.append(menu);
      document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) close(); });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) { close(); more.focus(); } });
    }
  }

  // 3. While the "routes ready" card shows, hide the duplicate Play route / Walker's view box
  const ready = $("uiReady");
  if (ready) new MutationObserver(() => document.body.classList.toggle("uiReadyOn", !ready.hidden))
    .observe(ready, { attributes: true, attributeFilter: ["hidden"] });

  // 5. A first hint under the search bar, until the user does something
  const hint = el("button", { id: "uiHint", type: "button" },
    el("span", { textContent: "Try: " }), el("b", { textContent: "find clay where water once flowed" }));
  hint.title = "Ask the planner assistant";
  hint.onclick = () => { hint.remove(); window.marsAssistant?.send("find clay where water once flowed"); };
  $("map").append(hint);
  const done = () => hint.remove();
  document.querySelector("#marsSearch input")?.addEventListener("input", done, { once: true });
  $("runMission")?.addEventListener("click", done, { once: true });
  new MutationObserver(() => { if (document.body.classList.contains("chat") || document.body.classList.contains("touring")) done(); })
    .observe(document.body, { attributes: true, attributeFilter: ["class"] });
})();
