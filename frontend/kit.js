// Gear manifest page. Talks to /api/gear/* (the kit) and /api/regions (targets and vehicles for the route).
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const CARRIER = { worn: "Worn", astronaut: "Hand-carried", cart: "Hand cart", rover: "Rover", vehicle: "Vehicle", base: "At base", deployed: "Deployed" };
const GROUP = { core: "Every mission", safety: "Safety", terrain: "Terrain", science: "Science", mission: "Mission", planner: "Planner" };
const GOAL_LABEL = { biosignatures: "Biosignatures", geology: "Geology", subsurface: "Subsurface", water_ice: "Water ice", atmosphere: "Atmosphere",
  seismic: "Seismic", radiation: "Radiation", isru: "Resource production", construction: "Construction" };
const HAZARD_LABEL = { pit: "Pit or skylight", cliff: "Cliff", dunes: "Dunes", canyon_walls: "Canyon walls", night_ops: "Night work", dust_storm_season: "Dust storm season" };
const VEHICLE_LABEL = { astronaut: "Astronaut on foot", pressurized_rover: "Pressurized crew rover", small_rover: "Robotic rover (Curiosity class)", perseverance: "Perseverance rover" };

const state = { meta: null, regions: [], manifest: null, mode: "build", filters: { carrier: "all", priority: "all", q: "", rule: null }, publishedAt: null, poll: null };

// ---------------------------------------------------------------- formatting
const num = (v, d = 1) => (v == null || Number.isNaN(v) ? "n/a" : Number(v).toFixed(d).replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1"));
function kg(v) {
  if (v == null) return "n/a";
  const d = v >= 100 ? 0 : v >= 10 ? 1 : 2;
  return num(v, d) + " kg";
}
const plural = (n, w) => `${n} ${n === 1 ? w : w === "person" ? "people" : w + "s"}`;

function badge(conf) {
  return `<span class="conf c-${conf.tag}" title="${esc(conf.label + ": " + conf.meaning)}">${conf.tag}</span>`;
}

// ---------------------------------------------------------------- API
async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : (j.detail?.message || JSON.stringify(j.detail || j)); } catch (_) {}
    const e = new Error(msg); e.status = r.status; throw e;
  }
  return r.json();
}
const post = (url, body) => getJSON(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ---------------------------------------------------------------- form
function buildChips(el, names, labels) {
  el.innerHTML = names.map((n) => `<label><input type="checkbox" value="${n}"><span>${esc(labels[n] || n)}</span></label>`).join("");
}
const checked = (el) => $$("input:checked", el).map((i) => i.value);
function setChecked(el, values) { $$("input", el).forEach((i) => { i.checked = values.includes(i.value); }); }

function applyArchetype(id) {
  const a = state.meta.archetypes.find((x) => x.id === id);
  if (!a) return;
  $("#archetypeHint").textContent = a.summary + (a.basis === "assumed" ? " Defaults for this type are planning assumptions, not published figures." : "");
  $("#crew").value = String(a.crew);
  $("#stay").value = a.stay_sols;
  $("#power").value = a.power;
  setChecked($("#goals"), a.goals);
  setChecked($("#hazards"), id === "cave" ? ["pit"] : []);
}

function fillTargets(selectEl, latEl, lonEl, targets, pick) {
  selectEl.innerHTML = targets.map((t, i) => `<option value="${i}">${esc(t.name)}</option>`).join("") + '<option value="custom">Custom coordinates</option>';
  const set = (t) => { latEl.value = t.lat.toFixed(4); lonEl.value = t.lon.toFixed(4); };
  selectEl.value = String(Math.min(pick, targets.length - 1));
  if (targets.length) set(targets[Math.min(pick, targets.length - 1)]);
  selectEl.onchange = () => { if (selectEl.value !== "custom") set(targets[+selectEl.value]); };
  [latEl, lonEl].forEach((e) => (e.oninput = () => { selectEl.value = "custom"; }));
}

function currentRegion() { return state.regions.find((r) => r.region === $("#region").value); }
function refreshTargets() {
  const r = currentRegion();
  const ts = r ? r.targets : [];
  fillTargets($("#base"), $("#baseLat"), $("#baseLon"), ts, 0);
  fillTargets($("#target"), $("#targetLat"), $("#targetLon"), ts, 1);
}

function readForm() {
  const ctx = {
    archetype: $("#archetype").value, crew: +$("#crew").value, stay_sols: +$("#stay").value, eva_hours: +$("#evaHours").value,
    power: $("#power").value, goals: checked($("#goals")), hazards: checked($("#hazards")),
  };
  if ($("#useRoute").checked && state.regions.length) {
    const lat = (id) => parseFloat($(id).value), ok = [lat("#baseLat"), lat("#baseLon"), lat("#targetLat"), lat("#targetLon")].every(Number.isFinite);
    if (ok) {
      ctx.vehicle = $("#vehicle").value;
      ctx.region = $("#region").value;
      ctx.route_request = {
        region: ctx.region, vehicle: ctx.vehicle, local_hour: +$("#hour").value, budget_hours: +$("#budget").value,
        base: { lat: lat("#baseLat"), lon: lat("#baseLon") }, target: { lat: lat("#targetLat"), lon: lat("#targetLon") },
      };
    }
  }
  return ctx;
}

// show the published mission's inputs in the (read-only) form so it matches the kit beside it
function syncForm(c) {
  if ([...$("#archetype").options].some((o) => o.value === c.archetype)) $("#archetype").value = c.archetype;
  $("#archetypeHint").textContent = (state.meta.archetypes.find((a) => a.id === c.archetype) || {}).summary || "";
  $("#crew").value = String(c.crew);
  $("#stay").value = c.stay_sols;
  $("#evaHours").value = c.eva_hours;
  $("#power").value = c.power;
  setChecked($("#goals"), c.goals);
  setChecked($("#hazards"), c.hazards);
}

function prefillFromURL() {
  const q = new URLSearchParams(location.search);
  const pair = (v) => (v || "").split(",").map(parseFloat);
  if (q.get("archetype") && state.meta.archetypes.some((a) => a.id === q.get("archetype"))) { $("#archetype").value = q.get("archetype"); applyArchetype(q.get("archetype")); }
  if (q.get("crew")) $("#crew").value = q.get("crew");
  if (q.get("stay")) $("#stay").value = q.get("stay");
  if (q.get("region") && $("#region").querySelector(`option[value="${q.get("region")}"]`)) { $("#region").value = q.get("region"); refreshTargets(); }
  if (q.get("vehicle") && $("#vehicle").querySelector(`option[value="${q.get("vehicle")}"]`)) $("#vehicle").value = q.get("vehicle");
  const setPt = (v, a, b, s) => { const [la, lo] = pair(v); if (Number.isFinite(la) && Number.isFinite(lo)) { $(a).value = la.toFixed(4); $(b).value = lo.toFixed(4); $(s).value = "custom"; } };
  setPt(q.get("base"), "#baseLat", "#baseLon", "#base");
  setPt(q.get("target"), "#targetLat", "#targetLon", "#target");
  if (q.get("hour")) $("#hour").value = q.get("hour");
  if (q.get("budget")) $("#budget").value = q.get("budget");
  if (q.get("rule")) { state.filters.rule = q.get("rule").toUpperCase(); state.openFiltered = true; }
  return q.has("archetype") || q.has("base");
}

// ---------------------------------------------------------------- rendering
function renderFigures(m) {
  const s = m.summary, c = m.carry, b = m.budget.radiation, cc = s.confidence_counts;
  const supported = cc.V + cc.P + cc.E;
  const pct = Math.min(100, (c.load_kg / c.cap_kg) * 100);
  return `<div class="figures">
    <div class="fig"><div class="k">Items</div><div class="v">${s.items}</div>
      <div class="s">${s.critical} critical, ${s.recommended} recommended, ${s.optional} optional</div></div>
    <div class="fig"><div class="k">Hand-carried, per team</div><div class="v">${num(c.load_kg)}<small>kg</small></div>
      <div class="meter ${c.over_cap ? "over" : ""}"><i style="width:${pct}%"></i></div>
      <div class="s">of ${num(c.cap_kg)} kg for ${plural(c.team_size, "person")}${c.moved.length ? `; ${c.moved.length} items moved to a vehicle` : ""}${c.items_without_mass ? `; ${c.items_without_mass} unweighed` : ""}</div></div>
    <div class="fig"><div class="k">Surface dose</div><div class="v">${num(b.surface_dose_msv, 0)}<small>mSv</small></div>
      <div class="s">${num(b.career_pct)}% of the 600 mSv career limit, surface only</div></div>
    <div class="fig"><div class="k">Rules triggered</div><div class="v">${s.rules_triggered}<small>of ${s.rules_checked}</small></div>
      <div class="s">each one is listed below with its evidence</div></div>
    <div class="fig"><div class="k">Specified from a source</div><div class="v">${supported}<small>of ${s.items}</small></div>
      <div class="s">${cc.I + cc.N} inferred or with no published spec</div></div>
  </div>`;
}

function renderRules(m) {
  const rows = m.rules.map((r) => `<tr>
    <td class="id">${esc(r.id)}<small>${esc(GROUP[r.group] || r.group)}</small></td>
    <td class="t"><b>${esc(r.title)}</b><span>${esc(r.detail)}</span></td>
    <td class="ob">${r.threshold === "always" ? '<span class="dim">always applies</span>'
      : r.observed ? `<b>${esc(r.observed)}</b>${r.threshold ? `<br>against ${esc(r.threshold)}` : ""}` : ""}</td>
    <td>${badge(r.confidence)}</td>
    <td class="ct">${r.items.length ? `<button class="link" data-rule="${esc(r.id)}">${plural(r.items.length, "item")}</button>` : ""}</td></tr>`).join("");
  return `<section class="sec"><h2>Why this kit <span class="n">${m.rules.length} rules triggered</span></h2>
    <p class="intro">Each rule reads something the planner already knows, such as the route's slope or hours, and adds gear for it. The letter shows how well the rule's threshold is supported. Select a rule's item count to show only its items below.</p>
    <table class="rules"><thead><tr><th>Rule</th><th>What tripped it</th><th>Value</th><th></th><th></th></tr></thead><tbody>${rows}</tbody></table></section>`;
}

function renderItem(e) {
  const rules = e.rules.map((r) => `<button class="chip" data-rule="${esc(r)}" title="Show items from rule ${esc(r)}">${esc(r)}</button>`).join("");
  const isVeh = e.carried_by === "vehicle";
  const mass = e.per_use_kg != null
    ? `<span class="mass" title="One crew member, one EVA. The whole-stay amount is in the consumables budget.">${kg(e.per_use_kg)}<small>/EVA</small></span>`
    : e.id === "c_cabin" ? `<span class="mass none" title="Sized in the consumables budget below">see budget</span>`
    : e.total_mass_kg == null
    ? `<span class="mass none" title="No published mass">n/a</span>`
    : `<span class="mass" ${isVeh ? 'title="Vehicle mass, not added to the kit total"' : ""}>${kg(e.total_mass_kg)}</span>`;
  const reasons = e.reasons.map((r) => `<li class="why"><span class="rid">${esc(r.rule)}</span><span>${esc(r.why)}</span>${r.observed ? `<span class="ob">${esc(r.observed)}${r.threshold && r.threshold !== "always" ? " against " + esc(r.threshold) : ""}</span>` : ""}</li>`).join("");
  const facts = [
    e.mass_kg != null ? ["Unit mass", `${kg(e.mass_kg)} <span style="color:var(--text-3)">(${esc(e.mass_basis)})</span>`] : ["Unit mass", `<span style="color:var(--text-3)">not published</span>`],
    e.power_w ? ["Power", esc(e.power_w)] : null,
    e.rate ? ["Rate", esc(e.rate)] : null,
    ["Carried", esc(CARRIER[e.carried_by] || e.carried_by) + (e.moved_note ? ` <span style="color:var(--text-3)">- ${esc(e.moved_note)}</span>` : "")],
    e.planner_vehicle ? ["Planner vehicle", `<span class="mono">${esc(e.planner_vehicle)}</span>`] : null,
  ].filter(Boolean).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  const srcs = e.sources.length
    ? e.sources.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("")
    : `<li style="color:var(--text-3)">No source. This is a proposal, not a published specification.</li>`;
  return `<details class="item p-${e.priority}" data-id="${esc(e.id)}" data-carrier="${esc(e.carried_by)}" data-priority="${e.priority}" data-rules="${esc(e.rules.join(" "))}" data-q="${esc((e.name + " " + e.summary + " " + e.note).toLowerCase())}">
    <summary><span class="bar" title="${esc(e.priority_label)}"></span>
      <span class="nm"><b>${esc(e.name)}</b><span class="sm">${esc(e.summary)}</span></span>
      <span class="qty">x${e.qty}</span><span class="car">${esc(CARRIER[e.carried_by] || e.carried_by)}</span>${mass}
      ${badge(e.confidence)}<span class="rl">${rules}</span><span class="chev"></span></summary>
    <div class="detail">
      <div><h4>Why it is here</h4><ul>${reasons}</ul>${e.note ? `<h4>Notes</h4><p class="note">${esc(e.note)}</p>` : ""}</div>
      <div><h4>Specification</h4><dl class="facts">${facts}</dl>
        <h4>Evidence</h4><p class="meaning">${badge(e.confidence)}<span><b>${esc(e.confidence.label)}.</b> ${esc(e.confidence.meaning)}</span></p>
        <h4>Sources</h4><ul class="srcs">${srcs}</ul></div>
    </div></details>`;
}

function renderManifest(m) {
  const mb = m.mass.by_carrier_kg;
  const massLine = Object.keys(mb).length
    ? Object.entries(mb).map(([k, v]) => `${esc(CARRIER[k] || k).toLowerCase()} <b>${kg(v)}</b>`).join(" &middot; ")
    : "no items with a published mass";
  const groups = m.groups.map((g) => {
    const gm = g.items.filter((i) => i.carried_by !== "vehicle" && i.total_mass_kg != null).reduce((a, i) => a + i.total_mass_kg, 0);
    return `<div class="cat" data-cat="${esc(g.id)}"><h3>${esc(g.label)} <span class="n">${g.items.length}</span><span class="m">${gm ? kg(gm) + " known" : ""}</span></h3>${g.items.map(renderItem).join("")}</div>`;
  }).join("");
  const seg = (name, opts) => `<div class="seg" data-seg="${name}" role="group">${opts.map(([v, l]) => `<button data-v="${v}" aria-pressed="${state.filters[name] === v}">${l}</button>`).join("")}</div>`;
  return `<section class="sec"><h2>Manifest <span class="n" id="shown"></span></h2>
    <p class="intro">Left edge: rust is critical, sand is recommended, hatched is optional. The letter is how well the item's specification is supported. Quantities are for the whole mission.</p>
    <div class="bar-tools">
      ${seg("priority", [["all", "All"], ["critical", "Critical"], ["recommended", "Recommended"], ["optional", "Optional"]])}
      ${seg("carrier", [["all", "Anyone"], ["worn", "Worn"], ["astronaut", "Hand-carried"], ["rover", "Rover"], ["base", "Base"], ["deployed", "Deployed"], ["vehicle", "Vehicles"]])}
      <span class="rule-filter" id="ruleFilter" hidden>Rule <span class="mono" id="ruleFilterId"></span> <button class="link" id="clearRule">clear</button></span>
      <input type="search" id="q" placeholder="Find an item" aria-label="Find an item" value="${esc(state.filters.q)}">
    </div>
    <div class="mass-line">Known mass: ${massLine}. ${m.mass.items_without_mass.length ? `${m.mass.items_without_mass.length} items have no published mass, so these are lower bounds.` : ""}</div>
    <div id="cats">${groups}</div></section>`;
}

function renderBudget(m) {
  const b = m.budget;
  const tables = b.groups.map((g) => `<div class="group-label">${esc(g.label)}</div><table class="tbl"><tbody>${g.lines.map((l) => `<tr>
    <td class="l">${esc(l.label)}${l.note ? `<span>${esc(l.note)}</span>` : ""}</td>
    <td class="v">${l.value == null ? "n/a" : num(l.value, 2)} <small>${esc(l.unit)}</small></td>
    <td class="f">${esc(l.formula)}</td><td class="c">${badge(l.confidence)}</td></tr>`).join("")}</tbody></table>`).join("");
  const d = b.radiation;
  const pc = b.planner_check;
  return `<section class="sec"><h2>Consumables and dose</h2>
    <p class="intro">Every line shows its arithmetic. Rates come from NASA documents where they exist; EVA days and similar planning choices are marked as assumptions.</p>
    ${tables}
    <div class="group-label">Radiation, surface only</div>
    <div class="dose"><span class="big">${num(d.surface_dose_msv, 0)} mSv</span><span>${esc(d.formula)}, measured by Curiosity's RAD. ${num(d.career_pct)}% of the ${d.career_limit_msv} mSv career limit. The habitat design cap is ${d.habitat_cap_msv_day} mSv per day.</span></div>
    <p class="note" style="margin-top:6px">${esc(d.caveat)}</p>
    ${pc ? `<div class="callout"><b>Check on the planner's own numbers.</b> ${esc(pc.message)} ${badge(pc.confidence)}</div>` : ""}</section>`;
}

function renderEvidence(m) {
  const cc = m.summary.confidence_counts, total = m.summary.items || 1;
  const bar = Object.keys(cc).filter((k) => cc[k]).map((k) => `<i class="c-${k}" style="flex:${cc[k]}" title="${k}: ${cc[k]}"></i>`).join("");
  const meta = { V: ["Verified", "The source page was re-opened and the figure found."], P: ["Published", "Read in the source; not re-checked."],
    E: ["Excerpt", "Seen only in a search excerpt, often of a PDF. Check before relying on it."], I: ["Inferred", "Reasoning on sourced inputs. Tunable."],
    N: ["No source", "Searched for and not found. A proposal."] };
  const legend = Object.entries(meta).map(([k, [l, t]]) => `<div><span class="conf c-${k}">${k}</span><b>${l} (${cc[k]})</b>${t}</div>`).join("");
  const thin = m.thin_evidence.length ? `<h2 style="margin-top:28px;font:600 12px var(--cond);text-transform:uppercase;letter-spacing:.09em">Rest on thin evidence <span class="n">${m.thin_evidence.length}</span></h2>
    <p class="intro">Critical or recommended items whose specification is inferred or has no published source. They are the first to challenge.</p><ul class="thin">${m.thin_evidence.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : "";
  const assumptions = m.assumptions.length ? `<h2 style="margin-top:28px;font:600 12px var(--cond);text-transform:uppercase;letter-spacing:.09em">Filled in from defaults <span class="n">${m.assumptions.length}</span></h2>
    <ul class="assume">${m.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : "";
  return `<section class="sec"><h2>Evidence <span class="n">${total} items</span></h2>
    <div class="evbar">${bar}</div><div class="legend">${legend}</div>${thin}${assumptions}</section>`;
}

function routeLine(m) {
  const r = m.context.route;
  if (!r) return "No route planned";
  return `Route ${num(r.distance_km)} km, ${num(r.round_trip_h)} h round trip, max slope ${num(r.max_slope_deg)} degrees` + (r.o2_pct != null ? `, suit oxygen ${num(r.o2_pct, 0)}%` : r.energy_pct != null ? `, energy ${num(r.energy_pct, 0)}%` : "");
}

function renderSheet(m, extra = {}) {
  const c = m.context;
  const sub = [plural(c.crew, "crew member"), `${num(c.stay_sols, 0)} sols`, `${c.power} power`, c.region, VEHICLE_LABEL[c.vehicle]].filter(Boolean).join("  /  ");
  const warn = m.warnings.length ? `<div class="alert"><h3>Needs attention</h3><ul>${m.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : "";
  const note = extra.note ? `<p class="published-note">${esc(extra.note)}</p>` : "";
  $("#sheet").innerHTML = `
    <div class="head"><div><h1>${esc(c.archetype_label)}</h1><div class="sub">${esc(sub)}</div></div>
      <div class="tools"><button class="ghost" id="copy">Copy JSON</button><button class="ghost" id="print">Print</button></div></div>
    ${note}<p class="lede">${esc(c.archetype_summary)} ${esc(routeLine(m))}.</p>
    ${renderFigures(m)}${warn}${renderRules(m)}${renderManifest(m)}${renderBudget(m)}${renderEvidence(m)}`;
  $("#print").onclick = () => window.print();
  $("#copy").onclick = async (ev) => {
    try { await navigator.clipboard.writeText(JSON.stringify(m, null, 2)); ev.target.textContent = "Copied"; } catch (_) { ev.target.textContent = "Copy failed"; }
    setTimeout(() => (ev.target.textContent = "Copy JSON"), 1400);
  };
  wireManifest();
  applyFilters();
  if (state.openFiltered) {                 // a deep link like kit.html?rule=S2 opens that rule's items
    state.openFiltered = false;
    $$("details.item:not([hidden])").forEach((d) => { d.open = true; });
    $("#cats").scrollIntoView({ block: "start" });
  }
}

// ---------------------------------------------------------------- filtering
function wireManifest() {
  $$("[data-seg]").forEach((seg) => seg.addEventListener("click", (ev) => {
    const b = ev.target.closest("button"); if (!b) return;
    state.filters[seg.dataset.seg] = b.dataset.v;
    $$("button", seg).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    applyFilters();
  }));
  $("#q").addEventListener("input", (ev) => { state.filters.q = ev.target.value.toLowerCase(); applyFilters(); });
  $("#clearRule").onclick = () => { state.filters.rule = null; applyFilters(); };
  $("#sheet").addEventListener("click", (ev) => {
    const r = ev.target.closest("[data-rule]"); if (!r) return;
    ev.preventDefault(); ev.stopPropagation();
    state.filters.rule = state.filters.rule === r.dataset.rule ? null : r.dataset.rule;
    applyFilters();
    if (state.filters.rule) $("#cats").scrollIntoView({ behavior: "smooth", block: "start" });
  }, true);
}

function applyFilters() {
  const f = state.filters;
  if (!$("#cats")) return;
  let shown = 0, total = 0;
  $$("details.item").forEach((el) => {
    total++;
    const ok = (f.carrier === "all" || el.dataset.carrier === f.carrier) && (f.priority === "all" || el.dataset.priority === f.priority)
      && (!f.q || el.dataset.q.includes(f.q)) && (!f.rule || el.dataset.rules.split(" ").includes(f.rule));
    el.hidden = !ok;
    if (ok) shown++;
  });
  $$(".cat").forEach((c) => { c.hidden = !$$("details.item:not([hidden])", c).length; });
  $$(".chip").forEach((c) => c.classList.toggle("on", c.dataset.rule === f.rule));
  $("#ruleFilter").hidden = !f.rule;
  if (f.rule) $("#ruleFilterId").textContent = f.rule;
  $("#shown").textContent = shown === total ? `${total} items` : `${shown} of ${total} items`;
}

// ---------------------------------------------------------------- actions
async function build() {
  const btn = $("#go"); btn.disabled = true; btn.textContent = "Planning route and building kit";
  try {
    state.manifest = await post("/api/gear/kit", { context: readForm() });
    renderSheet(state.manifest);
  } catch (e) {
    $("#sheet").innerHTML = `<p class="err">Could not build the kit: ${esc(e.message)}</p>`;
  } finally { btn.disabled = false; btn.textContent = "Build kit"; }
}

async function loadPublished(quiet) {
  try {
    const p = await getJSON("/api/gear/published");
    if (!p.manifest) throw new Error("none yet");
    $("#pubDot").hidden = state.mode === "published" || p.published_at === state.publishedAt;
    if (state.mode === "published" && p.published_at !== state.publishedAt) {
      state.publishedAt = p.published_at; state.manifest = p.manifest;
      syncForm(p.manifest.context);
      renderSheet(p.manifest, { note: p.note ? `Planning agent: ${p.note}` : "Published by the planning agent at " + new Date(p.published_at * 1000).toLocaleTimeString() });
    }
    return true;
  } catch (e) {
    if (!quiet && state.mode === "published") $("#sheet").innerHTML = `<p class="empty">The planning agent has not published a kit yet. When it calls recommend_gear with publish set, the kit appears here.</p>`;
    return false;
  }
}

function setMode(mode) {
  state.mode = mode;
  $("#tabBuild").setAttribute("aria-selected", String(mode === "build"));
  $("#tabPublished").setAttribute("aria-selected", String(mode === "published"));
  $("#rail").classList.toggle("readonly", mode === "published");
  $("#railNote").hidden = mode !== "published";
  clearInterval(state.poll);
  if (mode === "published") {
    state.publishedAt = null; $("#pubDot").hidden = true;
    loadPublished(false);
    state.poll = setInterval(() => loadPublished(true), 6000);
  } else if (state.manifest) renderSheet(state.manifest);
}

// ---------------------------------------------------------------- boot
(async function boot() {
  try {
    const [arch, regions] = await Promise.all([
      post("/api/gear/tools/list_mission_archetypes", {}),
      getJSON("/api/regions").catch(() => ({ regions: [], vehicles: {} })),
    ]);
    state.meta = arch; state.regions = regions.regions;
    $("#archetype").innerHTML = arch.archetypes.map((a) => `<option value="${a.id}">${esc(a.label)}</option>`).join("");
    buildChips($("#goals"), arch.goals, GOAL_LABEL);
    buildChips($("#hazards"), arch.hazards, HAZARD_LABEL);
    const veh = regions.vehicles && Object.keys(regions.vehicles).length ? regions.vehicles : VEHICLE_LABEL;
    $("#vehicle").innerHTML = Object.entries(veh).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    $("#region").innerHTML = state.regions.map((r) => `<option value="${r.region}">${esc(r.region)}</option>`).join("");
    if (!state.regions.length) { $("#useRoute").checked = false; $("#useRoute").disabled = true; $("#routeFields").hidden = true; }
    refreshTargets();
    $("#archetype").onchange = (e) => applyArchetype(e.target.value);
    $("#region").onchange = refreshTargets;
    $("#useRoute").onchange = (e) => { $("#routeFields").hidden = !e.target.checked; };
    $("#form").onsubmit = (e) => { e.preventDefault(); build(); };
    $("#tabBuild").onclick = () => setMode("build");
    $("#tabPublished").onclick = () => setMode("published");
    applyArchetype("short_stay");
    prefillFromURL();
    if (new URLSearchParams(location.search).get("tab") === "published") { setMode("published"); }
    else await build();
    loadPublished(true);
    setInterval(() => state.mode === "build" && loadPublished(true), 8000);
  } catch (e) {
    $("#sheet").innerHTML = `<p class="err">The gear service is not reachable: ${esc(e.message)}. Start the server with <span class="mono">uvicorn gear_server:server --port 8000</span>.</p>`;
  }
})();
