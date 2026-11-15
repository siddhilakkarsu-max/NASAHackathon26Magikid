// Making the planner easy to pick up, the way a street map is:
//  - a search bar on the map (places, or a mission goal),
//  - a "?" button and a "How to use this map" manual that explains every option, with a quick start the first time,
//  - an (i) on each panel section opening the manual at that section, and plain-language tooltips on the controls.
// Loaded after the main script in index.html; it only reads its globals (regions, namedSites, JUMP_PLACES,
// viewer, MARS) and presses its existing controls, so the planner works the same without this file.
(() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
  const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } },
                  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };

  // ------------------------------------------------------------------ manual ----
  const SECTIONS = [
    ["start", "Quick start", `
      <h3>Plan a Marswalk in four steps</h3>
      <ol>
        <li><b>Find a place.</b> Type a name in the search bar at the top of the map (try <i>Jezero</i> or
          <i>Olympus Mons</i>), or pick one from <b>Region</b> in the panel.</li>
        <li><b>Say what you want to do.</b> Under <b>Plan a mission</b>, type a science goal such as
          <i>sample clay where water once flowed</i>, choose how you travel, then press <b>Plan mission</b>.
          You can also type the goal straight into the search bar.</li>
        <li><b>Compare the options.</b> You get up to three routes. Each card shows the distance, time, oxygen,
          the walk to the nearest storm shelter and whether you could walk back if the vehicle broke down.</li>
        <li><b>Look at the route.</b> Press <b>Play route</b> to watch it, or <b>Walker's view</b> to stand on the ground
          and see what the astronaut would see along the way.</li>
      </ol>
      <h4>Moving the map</h4>
      <ul>
        <li><b>Drag</b> to move. <b>Scroll</b> (or pinch) to zoom.</li>
        <li><b>Right-drag</b> or <kbd>Ctrl</kbd> + drag to tilt and see hills in 3D.</li>
        <li><b>Click</b> any spot to see what is there (slope, rock, minerals, temperature…).</li>
        <li><b>Whole Mars</b> zooms out to the planet; <b>Zoom to region</b> goes back to the area you are planning in.</li>
      </ul>
      <p>Press <kbd>?</kbd> any time to open this manual, and <kbd>A</kbd> to show or hide technical details.</p>`],
    ["find", "Finding places", `
      <h3>Finding places</h3>
      <dl>
        <dt>Search bar (top of the map)</dt>
        <dd>Type a place name and pick it from the list. If nothing matches, the last suggestion plans a mission
          with your words as the goal.</dd>
        <dt>Region</dt>
        <dd>The area the planner works in. <b>Loaded areas</b> are ready now. <b>More places</b> load the first time you
          pick them (about a minute; mineral maps follow a few minutes later). <b>Anywhere on Mars</b> uses
          whatever is in the middle of the map.</dd>
        <dt>Jump to a place</dt>
        <dd>Flies to famous places (rover landing sites, Olympus Mons, Valles Marineris…) to look around.
          It moves the view only; pick the place in Region to plan there.</dd>
        <dt>3D terrain when zoomed in on a key site</dt>
        <dd>When ticked, the hills and craters appear in 3D as you zoom in on a key site, and the view tilts once so you
          can see them. Untick it for a flat map.</dd>
      </dl>`],
    ["mission", "Plan a mission", `
      <h3>Plan a mission</h3>
      <dl>
        <dt>Goal</dt>
        <dd>What you want to do, in plain words: <i>sample clay where water once flowed</i>, <i>carbonates near the
          crater rim</i>, <i>a flat spot to land near olivine</i>. The planner turns it into map criteria and finds the
          best matching places.</dd>
        <dt>Vehicle</dt>
        <dd>How the crew travels: on foot, or in one of the rovers. Each has its own speed, range, slope limit and
          power, and the routes respect them.</dd>
        <dt>Priority</dt>
        <dd>What matters most when choosing between options: safety, science or speed. It changes the weights in the
          decision matrix.</dd>
        <dt>Stick to green rover-verified tracks</dt>
        <dd>Only drive where Perseverance has already driven safely (green on the map).</dd>
        <dt>Plan mission</dt>
        <dd>Finds a safe landing spot, the targets and up to three routes.</dd>
      </dl>
      <h4>Reading the results</h4>
      <dl>
        <dt>Option cards</dt><dd>One per route, best first. Click a card to show its route on the map.</dd>
        <dt>Decision matrix</dt><dd>How each option scores on science, safety, slope, distance and resources.</dd>
        <dt>Storm shelter</dt><dd>Minutes to the nearest shelter if a dust storm or solar flare hits.</dd>
        <dt>If the vehicle breaks</dt><dd>Whether the crew could walk back to base on the oxygen they have left.</dd>
        <dt>Play route</dt><dd>Animates the astronaut or rover along the route (time sped up).</dd>
        <dt>Walker's view</dt><dd>Puts you on the ground at eye height at five stops along the route, facing the way you
          walk. Use Back and Next to move, Exit view to return.</dd>
      </dl>`],
    ["manual", "Manual planning", `
      <h3>Manual planning (one route)</h3>
      <p>For planning a single walk yourself instead of letting the planner choose.</p>
      <dl>
        <dt>Who is travelling</dt><dd>On foot or a vehicle; sets speed, slope limit and supplies.</dd>
        <dt>EVA budget (hours)</dt><dd>How long the crew can stay outside. Routes longer than this are flagged.</dd>
        <dt>Set base / Set target</dt><dd>Press the button, then click the map to place the start or the destination.</dd>
        <dt>…or describe the target</dt><dd>Type what you are looking for (<i>valley with clay</i>) and press Find;
          pick one of the matches.</dd>
        <dt>Pick a science target</dt><dd>Ready-made targets for this region.</dd>
        <dt>Plan route</dt><dd>Draws the safest route between base and target.</dd>
        <dt>Consumables</dt><dd>Oxygen, water and energy used on the route against what the traveller carries.</dd>
        <dt>Gear for this route</dt><dd>Opens the gear page to choose the kit for the walk.</dd>
      </dl>`],
    ["time", "Time & season", `
      <h3>Time, season and lighting</h3>
      <dl>
        <dt>Season</dt><dd>Where Mars is in its year (shown as Ls, 0–360°). It changes temperature, dust and the
          air pressure that shields from radiation.</dd>
        <dt>Local solar time</dt><dd>Time of day at the place you are planning. Missions use it for the sun, the
          temperature and a warning when the sun is low.</dd>
        <dt>Sunlight and atmosphere</dt><dd>Shows day and night on the globe. Move the mouse over the night side to see
          the map there.</dd>
      </dl>`],
    ["global", "Mars-wide maps", `
      <h3>Mars global maps</h3>
      <dl>
        <dt>Map view (choose one)</dt>
        <dd><b>The planner's own map</b>: colour photos plus the planner's data. <b>Detailed photos</b>: 5 m black
          and white images of almost all of Mars. <b>Height map</b>: coloured by elevation. <b>Colour photos</b>:
          the Viking colour mosaic. <b>3D hills and craters</b>: real elevation everywhere.</dd>
        <dt>Weather layers</dt>
        <dd>Ground and air temperature, air pressure, wind speed and arrows, and dust in the air, from Mars climate
          data. They follow the Season and Local solar time sliders.</dd>
        <dt>Radiation</dt>
        <dd>Modelled cosmic-ray dose at the surface. <b>Solar activity</b> picks quiet or active sun; <b>Color
          scale</b> either shows small differences across the map or keeps one scale to compare scenarios.</dd>
        <dt>Weather timeline</dt><dd>Plays the weather through a range of sols (Mars days).</dd>
        <dt>Labels, tracks and photo outlines</dt>
        <dd>Place and crater names, the Perseverance and Curiosity rover paths, and where close-up HiRISE photos
          exist. Turn on as many as you like.</dd>
      </dl>`],
    ["regional", "Area data maps", `
      <h3>Regional map tools</h3>
      <p>Colour the selected area by one kind of data. The key and an opacity slider appear underneath.</p>
      <dl>
        <dt>Mission suitability</dt><dd>One score for safety, science and radiation shielding. Best place to start.</dd>
        <dt>Slope</dt><dd>How steep the ground is. Steep ground is slow and dangerous.</dd>
        <dt>Ground firmness</dt><dd>Solid rock versus loose sand or dust, where rovers can get stuck.</dd>
        <dt>Thermal inertia</dt><dd>How quickly the ground heats and cools; high means rock, low means dust.</dd>
        <dt>Travel cost</dt><dd>How hard it is to cross each spot. Routes follow the cheapest path.</dd>
        <dt>Sunlight on slopes</dt><dd>How much sun each slope gets at the chosen time (solar power, warmth).</dd>
        <dt>Surface temperature</dt><dd>Modelled ground temperature at the chosen season and time.</dd>
        <dt>Minutes to shelter</dt><dd>Walking time to the nearest shelter from every spot.</dd>
        <dt>Elevation</dt><dd>Height of the ground.</dd>
        <dt>Science targets and minerals</dt><dd>Where orbiters detected clay, carbonate, olivine and other minerals.</dd>
        <dt>Radiation shielding</dt><dd>How much air is overhead; low places are better shielded.</dd>
        <dt>Albedo</dt><dd>How bright the ground is; dark ground absorbs more sunlight.</dd>
        <dt>Box a sharp area</dt><dd>Press it, then click two corners: the sharpest photos load inside the box only, so
          the map stays fast.</dd>
        <dt>Show rover tracks</dt><dd>Perseverance's real path: green where it drove easily, yellow where it slowed down.</dd>
      </dl>`],
    ["point", "Clicking the map", `
      <h3>Inspect a map point</h3>
      <p>Click anywhere to see the values under that spot: elevation, slope, ground type, minerals, temperature and
        radiation. With the photo grid or HiRISE outlines on, you also get links to download the images there.</p>
      <h4>Map key and opacity</h4>
      <p>Explains the colours of the layer you chose. Lower the opacity to see the photo underneath.</p>
      <h4>Technical details</h4>
      <p>Press <kbd>A</kbd> to show units, sources and model details next to every value. <b>Sources &amp; model
        information</b> lists where all the data comes from.</p>`],
    ["words", "Words to know", `
      <h3>Words to know</h3>
      <dl>
        <dt>EVA / Marswalk</dt><dd>Time spent outside the habitat in a spacesuit.</dd>
        <dt>Sol</dt><dd>A Mars day: 24 hours 39 minutes.</dd>
        <dt>Ls (season)</dt><dd>Mars' position around the Sun. 0° is northern spring, 90° summer, 180° autumn,
          270° winter.</dd>
        <dt>CRISM</dt><dd>A mineral-mapping camera on NASA's Mars Reconnaissance Orbiter.</dd>
        <dt>CTX and HiRISE</dt><dd>Cameras on the same orbiter: CTX maps almost all of Mars at about 5 m, HiRISE
          takes close-ups at under 1 m.</dd>
        <dt>THEMIS</dt><dd>An infrared camera on Mars Odyssey; it shows how warm the ground stays at night.</dd>
        <dt>MOLA / HRSC</dt><dd>The laser altimeter and stereo camera that measured Mars' heights.</dd>
        <dt>GCR</dt><dd>Galactic cosmic rays: the steady background radiation from outside the solar system.</dd>
        <dt>Albedo</dt><dd>How much sunlight the ground reflects.</dd>
      </dl>`],
  ];

  const nav = el("nav", { "aria-label": "Manual sections" });
  const article = el("article", { tabIndex: 0 });
  const closeBtn = el("button", { type: "button", textContent: "Close" });
  const sheet = el("div", { className: "sheet" },
    el("header", {}, el("h2", { id: "mapManualTitle", textContent: "How to use the Marswalk Planner" }), closeBtn),
    nav, article);
  const overlay = el("div", { id: "mapManual", hidden: true }, sheet);
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-labelledby", "mapManualTitle");
  document.body.append(overlay);
  let lastFocus = null;

  function show(key) {
    const [k, , html] = SECTIONS.find(s => s[0] === key) || SECTIONS[0];
    article.innerHTML = html;
    if (k === "start") {
      const box = el("input", { type: "checkbox", checked: store.get("mapManualSeen") === "1" });
      box.onchange = () => store.set("mapManualSeen", box.checked ? "1" : "0");
      article.append(el("label", { className: "foot" }, box, "Don't open this automatically next time"));
    }
    for (const b of nav.children) b.classList.toggle("on", b.dataset.key === k);
    article.scrollTop = 0;
  }
  for (const [key, title] of SECTIONS) {
    const b = el("button", { type: "button", textContent: title });
    b.dataset.key = key;
    b.onclick = () => show(key);
    nav.append(b);
  }
  function openManual(key = "start") {
    lastFocus = document.activeElement;
    show(key);
    overlay.hidden = false;
    closeBtn.focus();
  }
  function closeManual() {
    overlay.hidden = true;
    if (lastFocus?.focus) lastFocus.focus();
  }
  closeBtn.onclick = closeManual;
  overlay.addEventListener("click", e => { if (e.target === overlay) closeManual(); });
  document.addEventListener("keydown", e => {
    if (!overlay.hidden && e.key === "Escape") { closeManual(); e.preventDefault(); return; }
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
    if (e.key === "?" && !typing && overlay.hidden) { openManual(); e.preventDefault(); }
  });
  window.openMapManual = openManual;

  // "?" on the map, "How to use this map" at the top of the panel, and (i) on each panel section.
  const fab = el("button", { id: "helpFab", type: "button", textContent: "?", title: "How to use this map (?)" });
  fab.setAttribute("aria-label", "How to use this map");
  fab.onclick = () => openManual();
  $("map").append(fab);
  const panelTitle = document.querySelector("#panel h1");
  if (panelTitle) panelTitle.after(el("button", { id: "helpOpen", type: "button", className: "secondary",
    textContent: "How to use this map", onclick: () => openManual() }));
  const SECTION_HELP = { missionSetup: "mission", manual: "manual", missionResults: "mission", conditionsPanel: "time",
    globalMaps: "global", regionalMaps: "regional", mapKey: "point", pointDetails: "point" };
  for (const [id, key] of Object.entries(SECTION_HELP)) {
    const summary = document.querySelector(`#${id} > summary`);
    if (!summary) continue;
    const b = el("button", { type: "button", className: "secHelp", textContent: "?", title: "What is this?" });
    b.setAttribute("aria-label", `Explain ${summary.textContent.trim()}`);
    b.addEventListener("click", e => { e.preventDefault(); e.stopPropagation(); openManual(key); });
    summary.append(b);
  }

  // Plain-language tooltips (hover) on the controls.
  const TIPS = {
    region: "The area you plan in. 'More places' load in about a minute the first time.",
    wholeMars: "Zoom out to see the whole planet.",
    zoomRegion: "Fly back to the area you are planning in.",
    jumpTo: "Fly to a famous place to look around.",
    auto3d: "Show hills and craters in 3D when you zoom in on a key site.",
    goal: "What you want to do, in plain words, e.g. 'sample clay where water once flowed'.",
    mVehicle: "How the crew travels. Each vehicle has its own speed, range and slope limit.",
    mPriority: "What matters most when the planner compares routes.",
    greenOnly: "Only use ground Perseverance has already driven safely.",
    runMission: "Find a landing spot, targets and up to three routes.",
    vehicle: "Who makes this one walk or drive.",
    budget: "How many hours the crew can stay outside.",
    setBase: "Then click the map where the walk starts.",
    setTarget: "Then click the map where the walk ends.",
    query: "Describe what you are looking for, then press Find.",
    plan: "Draw the safest route between base and target.",
    ls: "Season on Mars (Ls): 0 northern spring, 90 summer, 180 autumn, 270 winter.",
    hour: "Time of day at the place you are planning.",
    globeLighting: "Show day and night on the globe.",
    globalLayer: "One planet-wide map view: photos, heights, 3D, weather or radiation.",
    regionalLayer: "Colour the selected area by one kind of data.",
    boxBtn: "Click two corners on the map to load the sharpest photos inside the box.",
    clearBox: "Remove the sharp photo box.",
    showTracks: "Perseverance's real path: green easy, yellow where it slowed.",
    mapOpacity: "Lower it to see the photos under the coloured layer.",
    playRoute: "Animate the traveller along the route (time sped up).",
    walkerView: "Stand on the ground at eye height at five stops along the route.",
    sourcesButton: "Where all the data comes from.",
  };
  for (const [id, tip] of Object.entries(TIPS)) {
    const n = $(id);
    if (n && !n.title) n.title = tip;
  }

  // ------------------------------------------------------------- search bar ----
  const input = el("input", { type: "search", placeholder: "Search Mars: Jezero, Olympus Mons… or a goal",
                              autocomplete: "off", spellcheck: false });
  input.setAttribute("aria-label", "Search places on Mars, or type a mission goal");
  const go = el("button", { type: "button", textContent: "Go" });
  const list = el("ul", { hidden: true, role: "listbox" });
  const search = el("div", { id: "marsSearch" }, el("div", { className: "box" }, input, go), list);
  $("map").append(search);
  let items = [], on = 0;
  const norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

  function places() {
    const out = [], seen = new Set();
    const add = (name, sub, act) => {
      const key = norm(name).replace(/\(.*\)/, "").trim();
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ name, sub, act });
    };
    try {
      for (const r of regions) add(r.label || r.region, "Ready to plan", () => pickRegion(r.region));
      for (const s of namedSites) add(s.label, s.ready ? "Ready to plan" : "Loads in about a minute, then ready to plan",
                                      () => pickRegion(s.ready ? s.site : `site:${s.site}`));
      for (const [name, lat, lon, h] of JUMP_PLACES) add(name, "Fly there to look around", () =>
        viewer.camera.flyTo({ destination: Cesium.Cartesian3.fromDegrees(lon, lat, h, MARS) }));
    } catch { /* the main script hasn't finished loading */ }
    return out;
  }
  function pickRegion(value) {
    const sel = $("region");
    if (![...sel.options].some(o => o.value === value)) return;
    sel.value = value;
    sel.onchange();
  }
  function planGoal(text) {
    $("goal").value = text;
    const setup = $("missionSetup");
    if (setup) setup.open = true;
    $("runMission").click();
  }
  function render() {
    const q = norm(input.value.trim());
    items = q ? places().filter(p => norm(p.name).includes(q)).slice(0, 8) : places().slice(0, 8);
    if (q) items.push({ name: `Plan a mission: “${input.value.trim()}”`, sub: "Use these words as the goal",
                        act: () => planGoal(input.value.trim()) });
    on = 0;
    list.replaceChildren(...items.map((p, i) => {
      const li = el("li", { role: "option" }, p.name, el("small", { textContent: p.sub }));
      li.classList.toggle("on", i === on);
      li.onmousedown = e => { e.preventDefault(); choose(i); };
      return li;
    }));
    list.hidden = !items.length;
  }
  function highlight(i) {
    on = (i + items.length) % items.length;
    [...list.children].forEach((li, j) => li.classList.toggle("on", j === on));
    list.children[on]?.scrollIntoView({ block: "nearest" });
  }
  function choose(i) {
    const p = items[i];
    if (!p) return;
    list.hidden = true;
    if (!p.name.startsWith("Plan a mission")) input.value = p.name;
    input.blur();
    p.act();
  }
  input.addEventListener("focus", () => { input.select(); render(); });
  input.addEventListener("input", render);
  input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 120));
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") { if (list.hidden) render(); else highlight(on + 1); e.preventDefault(); }
    else if (e.key === "ArrowUp") { highlight(on - 1); e.preventDefault(); }
    else if (e.key === "Enter") { if (list.hidden) render(); choose(on); e.preventDefault(); }
    else if (e.key === "Escape") { list.hidden = true; input.blur(); }
  });
  go.onclick = () => { render(); choose(on); };

  // ------------------------------------------------------- first-time quick start ----
  function firstTime() {
    if (store.get("mapManualSeen") === "1") return;
    store.set("mapManualSeen", "1");
    openManual("start");
  }
  const landing = $("landing");
  const landingShown = () => landing && !landing.hidden && getComputedStyle(landing).display !== "none"
                                     && !landing.classList.contains("hide") && !landing.classList.contains("gone");
  if (landingShown()) {
    $("startExploring")?.addEventListener("click", () => setTimeout(firstTime, 900));
  } else setTimeout(firstTime, 1200);
})();
