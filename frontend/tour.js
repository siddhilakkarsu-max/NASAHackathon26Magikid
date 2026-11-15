// Autoplay tour: a hands-off, looping flythrough of the planner for demos and the project video.
// Start it from the "Tour" button on the left bar, or open http://localhost:8000/?tour=1 (starts by itself).
// Esc, the Stop button or any click on the map ends it. Each step only uses the planner's own controls, and a step
// that can't run (no network, no route) is skipped, so the tour never gets stuck.
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
  const MARS = Cesium.Ellipsoid.MARS;
  const cam = () => viewer.camera;

  const title = el("div", { className: "tourTitle" }), line = el("div", { className: "tourLine" });
  const dots = el("div", { className: "tourDots" });
  const stopBtn = el("button", { type: "button", className: "tourStop", textContent: "Stop tour  (Esc)" });
  const card = el("div", { id: "tourCard", hidden: true }, title, line, dots, stopBtn);
  card.setAttribute("role", "status");
  card.setAttribute("aria-live", "polite");
  $("map").append(card);

  let running = false, run = 0, spin = 0;
  class Stopped extends Error {}
  const check = (id) => { if (!running || id !== run) throw new Stopped(); };
  const wait = async (ms, id) => {
    const end = performance.now() + ms;
    while (performance.now() < end) { check(id); await new Promise(r => setTimeout(r, 100)); }
    check(id);
  };
  const fly = (options, id) => new Promise((resolve) => {
    check(id);
    cam().flyTo({ ...options, complete: resolve, cancel: resolve });
  });
  const caption = (t, l, step, total) => {
    title.textContent = t; line.textContent = l || "";
    dots.replaceChildren(...Array.from({ length: total }, (_, i) => el("span", { className: i === step ? "on" : "" })));
    card.classList.remove("show"); void card.offsetWidth; card.classList.add("show");
  };
  viewer.scene.preUpdate.addEventListener(() => {           // slow spin of the globe between stops
    if (running && spin) cam().rotate(Cesium.Cartesian3.UNIT_Z, spin);
  });
  const layer = (id) => { try { window.marsSetLayer?.(id); } catch { /* layer not available here */ } };
  const place = (name) => (typeof JUMP_PLACES !== "undefined" ? JUMP_PLACES : []).find(p => p[0].startsWith(name));
  const above = (lon, lat, h, heading = 0, pitch = -90) => ({
    destination: Cesium.Cartesian3.fromDegrees(lon, lat, h, MARS),
    orientation: { heading: Cesium.Math.toRadians(heading), pitch: Cesium.Math.toRadians(pitch), roll: 0 } });

  async function planDemoMission(id) {
    const sel = $("region");
    if ([...sel.options].some(o => o.value === "jezero") && sel.value !== "jezero") { sel.value = "jezero"; sel.onchange(); }
    await wait(2500, id);
    $("goal").value = "sample clay where water once flowed";
    const before = mission;
    if (!$("runMission").disabled) $("runMission").click();
    const t0 = performance.now();
    while (performance.now() - t0 < 60000) {
      await wait(500, id);
      if (mission && mission !== before && mission.candidates?.length) return true;
    }
    return false;
  }

  const STEPS = [
    async (id, s, n) => {
      caption("Marswalk Planner", "Plan a safe walk on Mars from real NASA data", s, n);
      await fly({ ...above(40, 10, 9.5e6), duration: 2 }, id);
      spin = 0.0025; await wait(7000, id); spin = 0;
    },
    async (id, s, n) => {
      caption("Jezero crater", "Where NASA's Perseverance rover landed in 2021", s, n);
      await fly({ ...above(77.45, 18.44, 140e3, 0, -70), duration: 5 }, id);
      await wait(2500, id);
    },
    async (id, s, n) => {
      caption("Every pixel holds every dataset", "Here: minerals mapped by NASA's CRISM, where water once flowed", s, n);
      layer("science"); await wait(4500, id);
      caption("Ground the crew can trust", "Slope from NASA elevation data; steep ground is slow and dangerous", s, n);
      layer("slope"); await wait(4000, id);
      layer("");
    },
    async (id, s, n) => {
      caption("\"Sample clay where water once flowed\"", "The planner finds a landing spot, the best places and three safe routes", s, n);
      const ok = await planDemoMission(id);
      if (!ok) return;
      await wait(3500, id);
    },
    async (id, s, n) => {
      if (!mission?.candidates?.length || $("playRoute").disabled || $("routePlayback").hidden) return;
      const best = mission.candidates[0], r = best.route || {};
      caption("Checked for safety", `${r.distance_km} km, ${r.round_trip_h} h round trip: oxygen, storm shelter and the walk back`, s, n);
      $("playRoute").click();
      await wait(9000, id);
    },
    async (id, s, n) => {
      if ($("walkerView").hidden || $("routePlayback").hidden) return;
      caption("Walker's view", "What the astronaut sees, at eye height along the route", s, n);
      $("walkerView").click();
      for (let i = 0; i < 4; i++) { await wait(3000, id); if (!$("walkerNext").disabled) $("walkerNext").click(); }
      await wait(2500, id);
      $("walkerExit").click();
      await wait(1500, id);
    },
    async (id, s, n) => {
      caption("Radiation across Mars", "Modelled cosmic-ray dose at the surface: lower ground is better shielded", s, n);
      layer("radiation_dose");
      await fly({ ...above(-60, 0, 9.5e6), duration: 3 }, id);
      spin = 0.002; await wait(6000, id); spin = 0;
      layer("");
    },
    async (id, s, n) => {
      const p = place("Olympus Mons");
      if (!p) return;
      caption("Anywhere on Mars", "Olympus Mons, the largest volcano in the Solar System", s, n);
      await fly({ ...above(p[2], p[1] - 4, 700e3, 0, -50), duration: 4 }, id);
      await wait(3000, id);
    },
    async (id, s, n) => {
      const p = place("Valles Marineris");
      if (!p) return;
      caption("Valles Marineris", "A canyon system as long as the United States is wide", s, n);
      await fly({ ...above(p[2], p[1] - 6, 900e3, 10, -45), duration: 4 }, id);
      await wait(3000, id);
    },
    async (id, s, n) => {
      caption("Marswalk Planner", "Team MagiKid · NASA Space Apps Challenge 2026", s, n);
      await fly({ ...above(140, 0, 9.5e6), duration: 3 }, id);
      spin = 0.0025; await wait(5000, id); spin = 0;
    },
  ];

  async function start() {
    if (running) return;
    running = true;
    const id = ++run;
    document.body.classList.add("touring");
    document.body.classList.remove("drawer");
    window.marsAssistant?.open(false);
    card.hidden = false;
    $("landing")?.classList.add("gone");
    try {
      for (;;) {                                           // loops until stopped
        for (let i = 0; i < STEPS.length; i++) {
          try { await STEPS[i](id, i, STEPS.length); }
          catch (e) { if (e instanceof Stopped) throw e; }  // a step that fails is skipped
        }
      }
    } catch (e) {
      if (!(e instanceof Stopped)) console.error(e);
    }
  }
  function stop() {
    if (!running) return;
    running = false; run++; spin = 0;
    cam().cancelFlight();
    card.hidden = true;
    document.body.classList.remove("touring");
    if (!$("walkerNav").hidden) $("walkerExit").click();
  }
  stopBtn.onclick = stop;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && running) stop(); });
  $("map").addEventListener("pointerdown", (e) => { if (running && !card.contains(e.target)) stop(); }, true);

  // "Tour" on the left bar, just above Help
  const rail = $("gmRail");
  if (rail) {
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("viewBox", "0 0 24 24"); icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = '<circle cx="12" cy="12" r="8.5"/><path d="m10 8.5 5.5 3.5-5.5 3.5z"/>';
    const b = el("button", { type: "button", title: "Autoplay tour", onclick: start }, icon, el("span", { textContent: "Tour" }));
    const help = [...rail.querySelectorAll("button")].find(x => x.title === "Help");
    help ? help.before(b) : rail.append(b);
  }
  window.marsTour = { start, stop };
  if (new URLSearchParams(location.search).has("tour")) {
    const go = () => setTimeout(start, 4000);              // let the map and data load first
    document.readyState === "complete" ? go() : addEventListener("load", go);
  }
})();
