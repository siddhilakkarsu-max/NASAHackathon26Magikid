// One-click scenarios for the gear page. Each fills the form, builds the kit and sets ?preset=<id>
// so the scenario can be shared. Uses kit.js globals: state, $, $$, esc, build, applyArchetype,
// refreshTargets, setChecked, prefillFromURL.
"use strict";

(function () {
  const LANDING = [18.4447, 77.4508], DELTA = [18.50, 77.40], NEAR = [18.452, 77.444];
  const route = (vehicle, target, ls, extra = {}) => ({ region: "jezero", vehicle, base: LANDING, target, hour: 11, budget: 8, ls, ...extra });

  const PRESETS = [
    { id: "delta-walk", label: "Delta walk on foot", archetype: "traverse",
      route: route("astronaut", DELTA, 90),
      caption: "Suit oxygen against the 15 % reserve on a 4.8 km walk from the landing site to the delta front." },
    { id: "delta-dust", label: "Same walk, dust season", archetype: "traverse",
      route: route("astronaut", DELTA, 250),
      caption: "The same walk at Ls 250: the 20 % dust-season reserve flags it." },
    { id: "crew-rover", label: "Crew rover to the delta", archetype: "traverse",
      route: route("pressurized_rover", DELTA, 90),
      caption: "The same trip in a pressurized rover: battery energy replaces suit oxygen and the oxygen warnings clear." },
    { id: "opportunity", label: "Opportunity's dust storm", archetype: "traverse", power: "solar", hazards: ["dust_storm_season"],
      route: route("mer", NEAR, 250),
      caption: "Dust cuts solar charging. A global dust storm ended Opportunity in 2018." },
    { id: "spirit", label: "Spirit's sand trap", archetype: "traverse", power: "solar", hazards: ["dunes"],
      route: route("mer", NEAR, 90),
      caption: "Soft ground brings probes, traction aids and recovery gear. Spirit was lost in soft sand in 2009." },
    { id: "cave", label: "Lava-tube scouting", archetype: "cave", route: null,
      caption: "A pit adds vertical-access gear. No crewed procedure for pits is published, so the kit is a proposal." },
    { id: "long-base", label: "Long-stay base", archetype: "long_stay", crew: 4, stay: 500, power: "fission",
      goals: ["biosignatures", "subsurface", "atmosphere"], route: null,
      caption: "Four crew for 500 sols: a drill, weather instruments, long-duration care and a large share of the career dose." },
  ];
  const byId = (id) => PRESETS.find((p) => p.id === id);
  let active = null, applying = false;

  function setPoint(select, latEl, lonEl, [lat, lon]) {
    latEl.value = lat.toFixed(4); lonEl.value = lon.toFixed(4);
    const r = state.regions.find((x) => x.region === $("#region").value);
    const i = r ? r.targets.findIndex((t) => Math.abs(t.lat - lat) < 1e-4 && Math.abs(t.lon - lon) < 1e-4) : -1;
    select.value = i >= 0 ? String(i) : "custom";
  }

  // fill the form only; the caller builds
  function fill(p) {
    applying = true;
    try {
      if ([...$("#archetype").options].some((o) => o.value === p.archetype)) { $("#archetype").value = p.archetype; applyArchetype(p.archetype); }
      if (p.crew) $("#crew").value = String(p.crew);
      if (p.stay) $("#stay").value = p.stay;
      if (p.power) $("#power").value = p.power;
      if (p.goals) setChecked($("#goals"), p.goals);
      if (p.hazards) setChecked($("#hazards"), p.hazards);
      $("#evaHours").value = p.evaHours || 6;
      const useRoute = $("#useRoute");
      if (!useRoute.disabled) {
        useRoute.checked = !!p.route;
        $("#routeFields").hidden = !p.route;
      }
      const r = p.route;
      if (r && $("#region").querySelector(`option[value="${r.region}"]`)) {
        if ($("#region").value !== r.region) $("#region").value = r.region;
        refreshTargets();
        if ($("#vehicle").querySelector(`option[value="${r.vehicle}"]`)) $("#vehicle").value = r.vehicle;
        setPoint($("#base"), $("#baseLat"), $("#baseLon"), r.base);
        setPoint($("#target"), $("#targetLat"), $("#targetLon"), r.target);
        $("#hour").value = r.hour;
        $("#budget").value = r.budget;
        $("#ls").value = r.ls;
        $("#ls").dispatchEvent(new Event("input"));
      }
    } finally { applying = false; }
    setActive(p.id);
  }

  function setActive(id) {
    active = id || null;
    $$(".preset-list button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.preset === active)));
    const cap = $("#presetCaption"), p = byId(active);
    cap.hidden = !p;
    cap.textContent = p ? p.caption : "";
    const url = new URL(location.href);
    if (active) {
      const tab = url.searchParams.get("tab");
      url.search = "";
      url.searchParams.set("preset", active);
      if (tab) url.searchParams.set("tab", tab);
    } else url.searchParams.delete("preset");
    history.replaceState(null, "", url);
  }

  const idle = () => new Promise((res) => { const t = () => ($("#go").disabled ? setTimeout(t, 150) : res()); t(); });

  async function run(id) {
    const p = byId(id); if (!p || !state.meta) return;
    await idle();
    fill(p);
    build();
  }

  function mount() {
    const sec = document.createElement("section");
    sec.className = "presets";
    sec.setAttribute("aria-labelledby", "presetsTitle");
    sec.innerHTML = `<h2 id="presetsTitle">Scenarios</h2>
      <div class="preset-list" role="group" aria-labelledby="presetsTitle">${PRESETS.map((p) =>
        `<button type="button" data-preset="${esc(p.id)}" aria-pressed="false">${esc(p.label)}</button>`).join("")}</div>
      <p class="preset-caption" id="presetCaption" hidden></p>`;
    $("#rail").prepend(sec);
    sec.addEventListener("click", (ev) => { const b = ev.target.closest("button[data-preset]"); if (b) run(b.dataset.preset); });
    // a manual edit means the form no longer matches the named scenario
    const clear = () => { if (!applying && active) setActive(null); };
    $("#form").addEventListener("input", clear);
    $("#form").addEventListener("change", clear);
  }

  mount();
  const wanted = new URLSearchParams(location.search).get("preset");
  if (wanted && byId(wanted)) {
    if (!state.meta) {
      // apply inside kit.js's boot, right after its URL prefill, so its first build is the scenario
      const prefill = window.prefillFromURL;
      window.prefillFromURL = function () { prefill(); fill(byId(wanted)); return true; };
    } else run(wanted);
  }
})();
