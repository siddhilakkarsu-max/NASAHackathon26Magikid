// Pin a kit, change the mission, see what changed. Loaded after kit.js and reads its globals
// (state, esc, num, post, readForm). compareKits() is pure so tests can run it under node.
//
// Debug URL params, for headless screenshots where nothing can be clicked:
//   kit.html?compare=long_stay            pins a kit built from {archetype: "long_stay"} on load
//   kit.html?compare_vehicle=pressurized_rover
//                                         pins the page's own form with that traveller instead
// Both can be combined. The page then builds its normal kit from the form, so the diff shows.
"use strict";

// [key, label, unit, digits, read(manifest), direction]  direction: +1 more is worse, -1 less is worse, 0 neutral
const COMPARE_FIGURES = [
  ["items", "Items", "", 0, (m) => m.summary?.items, 0],
  ["critical", "Critical items", "", 0, (m) => m.summary?.critical, 0],
  ["rules", "Rules triggered", "", 0, (m) => m.summary?.rules_triggered, 0],
  ["load", "Hand-carried load", "kg", 1, (m) => m.carry?.load_kg, 1],
  ["o2", "Suit O2 for the route", "kg", 2, (m) => m.context?.route?.o2_used_kg, 1],
  ["o2_pct", "Suit O2, share of supply", "%", 0, (m) => m.context?.route?.o2_pct, 1],
  ["o2_usable", "Suit O2 usable after reserve", "kg", 2, (m) => m.context?.route?.o2_usable_kg, -1],
  ["energy", "Vehicle energy for the route", "kWh", 1, (m) => m.context?.route?.energy_used_kwh, 1],
  ["energy_pct", "Vehicle energy, share of battery", "%", 0, (m) => m.context?.route?.energy_pct, 1],
  ["recharge_sols", "Recharge", "sols", 1, (m) => m.context?.route?.recharge_sols, 1],
  ["recharge_h", "Recharge", "h", 1, (m) => m.context?.route?.recharge_h, 1],
  ["sunlight", "Sunlight", "%", 0, (m) => m.context?.route?.sunlight_pct, -1],
  ["reserve", "Reserve held back", "%", 0, (m) => m.context?.route?.reserve_pct, -1],
  ["dose", "Surface dose", "mSv", 0, (m) => m.budget?.radiation?.surface_dose_msv, 1],
];

// a = pinned manifest, b = current manifest. Returns plain data, no HTML.
function compareKits(a, b) {
  const round = (v, d) => Math.round(v * 10 ** d) / 10 ** d;
  const val = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const figures = [];
  for (const [key, label, unit, digits, read, dir] of COMPARE_FIGURES) {
    const x = val(read(a)), y = val(read(b));
    if (x == null && y == null) continue;
    const delta = x != null && y != null ? round(y - x, digits) : null;
    const changed = delta == null || delta !== 0;
    figures.push({ key, label, unit, digits, pinned: x, now: y, delta: delta === 0 ? 0 : delta, changed, worse: delta != null && dir !== 0 && delta * dir > 0 });
  }
  const brief = (i) => ({ id: i.id, name: i.name, category: i.category_label || i.category || "", qty: i.qty, priority: i.priority });
  const byId = (list) => new Map((list || []).map((i) => [i.id, i]));
  const ia = byId(a.items), ib = byId(b.items);
  const added = [...ib.values()].filter((i) => !ia.has(i.id)).map(brief);
  const removed = [...ia.values()].filter((i) => !ib.has(i.id)).map(brief);
  const qty = [...ib.values()].filter((i) => ia.has(i.id) && ia.get(i.id).qty !== i.qty)
    .map((i) => ({ ...brief(i), qty_pinned: ia.get(i.id).qty, qty_now: i.qty }));
  const ra = byId(a.rules), rb = byId(b.rules);
  const rule = (r) => ({ id: r.id, title: r.title });
  const rules_on = [...rb.values()].filter((r) => !ra.has(r.id)).map(rule);
  const rules_off = [...ra.values()].filter((r) => !rb.has(r.id)).map(rule);
  const same = !figures.some((f) => f.changed) && !added.length && !removed.length && !qty.length && !rules_on.length && !rules_off.length;
  return { same, figures, added, removed, qty, rules_on, rules_off };
}

// short label for a manifest, e.g. "Long-stay base / on foot 4.8 km / 4 crew / 500 sols"
function kitLabel(m, vehicleLabels) {
  const c = m.context || {};
  const short = { astronaut: "on foot", pressurized_rover: "crew rover", small_rover: "robotic rover", perseverance: "Perseverance" };
  const veh = c.vehicle ? (short[c.vehicle] || (vehicleLabels || {})[c.vehicle] || c.vehicle) : "";
  const route = c.route ? `${veh} ${Number(c.route.distance_km).toFixed(1).replace(/\.0$/, "")} km` : "";
  return [c.archetype_label, route, c.crew != null ? `${c.crew} crew` : "", c.stay_sols != null ? `${Math.round(c.stay_sols)} sols` : ""].filter(Boolean).join(" / ");
}

if (typeof module !== "undefined" && module.exports) module.exports = { compareKits, kitLabel, COMPARE_FIGURES };

if (typeof document !== "undefined") (function () {
  const KEY = "marswalk.kit.pin";
  const sheet = document.getElementById("sheet");
  if (!sheet || typeof state === "undefined") return;
  const vehLabels = () => (typeof VEHICLE_LABEL !== "undefined" ? VEHICLE_LABEL : {});

  const loadPin = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch (_) { return null; } };
  let pin = loadPin();

  function savePin(m) {
    pin = { label: kitLabel(m, vehLabels()), at: Date.now(), manifest: JSON.parse(JSON.stringify(m)) };
    try { sessionStorage.setItem(KEY, JSON.stringify(pin)); } catch (_) { /* storage full or blocked: keep the pin for this page only */ }
  }
  function clearPin() { pin = null; try { sessionStorage.removeItem(KEY); } catch (_) {} }

  const MINUS = "\u2212";
  const fmt = (v, d, unit) => (v == null ? '<span class="dim">n/a</span>' : `${num(v, d)}${unit ? `<small>${esc(unit)}</small>` : ""}`);
  function fmtDelta(f) {
    if (f.delta == null) return '<span class="dim">n/a</span>';
    if (f.delta === 0) return '<span class="dim">0</span>';
    const unit = f.unit === "%" ? "pts" : f.unit;
    return `${f.delta > 0 ? "+" : MINUS}${num(Math.abs(f.delta), f.digits)}${unit ? `<small>${esc(unit)}</small>` : ""}`;
  }

  function itemList(title, list, mark, line) {
    if (!list.length) return "";
    const LIMIT = 8;
    const row = (i) => `<li><span class="mk">${mark}</span><span class="nm">${esc(i.name)}<span>${esc(i.category)}</span></span><span class="q">${line(i)}</span></li>`;
    const more = list.length > LIMIT ? `<details class="more"><summary>${list.length - LIMIT} more</summary><ul>${list.slice(LIMIT).map(row).join("")}</ul></details>` : "";
    return `<div class="cmp-list"><h3>${esc(title)} <span class="n">${list.length}</span></h3><ul>${list.slice(0, LIMIT).map(row).join("")}</ul>${more}</div>`;
  }
  function ruleList(title, list, mark) {
    if (!list.length) return "";
    return `<div class="cmp-list"><h3>${esc(title)} <span class="n">${list.length}</span></h3><ul>${list.map((r) =>
      `<li><span class="mk">${mark}</span><span class="nm"><span class="rid">${esc(r.id)}</span> ${esc(r.title)}</span></li>`).join("")}</ul></div>`;
  }

  function renderCompare(m) {
    const d = compareKits(pin.manifest, m);
    const time = new Date(pin.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const pair = `<div class="cmp-pair">
      <div><span class="k">Pinned <span class="mono">${esc(time)}</span></span><b>${esc(pin.label)}</b></div>
      <div><span class="k">Now</span><b>${esc(kitLabel(m, vehLabels()))}</b></div></div>`;
    let body;
    if (d.same) body = `<p class="cmp-same">Same kit as the pinned one.</p>`;
    else {
      const rows = d.figures.map((f) => `<tr class="${f.changed ? "" : "same"}"><td class="l">${esc(f.label)}</td>
        <td class="v">${fmt(f.pinned, f.digits, f.unit)}</td><td class="v">${fmt(f.now, f.digits, f.unit)}</td>
        <td class="v d${f.worse ? " worse" : ""}">${fmtDelta(f)}</td></tr>`).join("");
      const lists = [
        itemList("Added", d.added, "+", (i) => `x${i.qty}`),
        itemList("Removed", d.removed, MINUS, (i) => `x${i.qty}`),
        itemList("Quantity changed", d.qty, "\u00b1", (i) => `x${i.qty_pinned} \u2192 x${i.qty_now}`),
        ruleList("Rules newly triggered", d.rules_on, "+"),
        ruleList("Rules no longer triggered", d.rules_off, MINUS),
      ].join("");
      body = `<table class="cmp-tbl"><thead><tr><th></th><th>Pinned</th><th>Now</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table>
        ${lists ? `<div class="cmp-lists">${lists}</div>` : `<p class="cmp-same">Same items and rules; only the figures above moved.</p>`}`;
    }
    return `<section class="sec cmp" id="kitCompare"><h2>Compared with pinned kit <button class="link" id="unpin">Unpin</button></h2>${pair}${body}</section>`;
  }

  function decorate() {
    const tools = sheet.querySelector(".head .tools");
    const m = state.manifest;
    if (!tools || !m) return;
    let btn = document.getElementById("pinKit");
    if (!btn) {
      btn = document.createElement("button");
      btn.className = "ghost"; btn.id = "pinKit"; btn.type = "button";
      tools.insertBefore(btn, tools.firstChild);
      btn.onclick = () => { savePin(state.manifest); decorate(); };
    }
    btn.textContent = pin ? "Re-pin" : "Pin for comparison";
    btn.title = pin ? `Replace the pinned kit (${pin.label}) with this one` : "Keep this kit to compare against after you change the mission";
    const old = document.getElementById("kitCompare");
    if (old) old.remove();
    if (!pin || !pin.manifest) return;
    const anchor = sheet.querySelector(".lede") || sheet.querySelector(".head");
    anchor.insertAdjacentHTML("afterend", renderCompare(m));
    document.getElementById("unpin").onclick = () => { clearPin(); decorate(); };
  }

  // kit.js replaces the whole sheet on every render; a missing pin button means a fresh render
  new MutationObserver(() => { if (!document.getElementById("pinKit")) decorate(); }).observe(sheet, { childList: true });
  decorate();

  const q = new URLSearchParams(location.search);
  if (q.has("compare") || q.has("compare_vehicle")) {
    const arch = q.get("compare"), veh = q.get("compare_vehicle");
    const pinDebug = async () => {
      let ctx = { archetype: arch };
      if (veh) {
        ctx = readForm();
        if (arch) { ctx = { ...ctx, archetype: arch }; delete ctx.crew; delete ctx.stay_sols; delete ctx.power; delete ctx.goals; }
        ctx.vehicle = veh;
        if (ctx.route_request) ctx.route_request.vehicle = veh;
      }
      try { savePin(await post("/api/gear/kit", { context: ctx })); decorate(); } catch (e) { console.warn("compare pin failed", e); }
    };
    // wait for kit.js to fill the form (the first render) so readForm() sees real values
    const start = () => (state.manifest ? pinDebug() : setTimeout(start, 200));
    start();
  }
})();
