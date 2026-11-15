// "Play" launcher: opens game.html (Marswalk: Survive the Route) from the planner pages.
// A plain classic script with no dependencies. Safe to include on any page, more than once; it never throws.
//
//   index.html  adds a "Play this mission" button under the mission result (#mResult) and a
//               "Play this route as a game" link beside the gear link. Both hand the plan on screen to the game
//               through localStorage["marswalk.game.mission"] and open game.html?src=planner in a new tab.
//               If storage is blocked or full, the request goes in the URL instead and the game plans it again.
//   kit.html    adds a "Play" button to the sheet's tool row. The kit page has no mission plan, so the game
//               plans one live from URL params read off the kit form (traveller, Ls, region, science goals).
//
// It reads two top-level bindings of index.html's inline script by bare name (`mission`, `selected`); nothing is
// written to them. The only global it adds is window.MarswalkGameLaunch = { version, buildPayload(), open() }.
(function () {
  "use strict";
  try {
    if (typeof window === "undefined" || typeof document === "undefined") return;
    if (window.MarswalkGameLaunch) return;                       // already loaded on this page

    var VERSION = "1.0.0";
    var GAME = "game.html";
    var STORE_KEY = "marswalk.game.mission";                     // read by game.html when the URL has ?src=planner
    var MAX_WITH_IMAGES = 1500000;                               // characters of JSON; above this the two PNGs are left out
    var DEFAULT_GOAL = "sample clay where water once flowed";    // the planner's own placeholder goal

    // kit traveller -> mission planner vehicle. Anything not listed (every robotic rover) drives as four_wheel.
    var KIT_VEHICLE = { astronaut: "on_foot", unpressurized_rover: "four_wheel", pressurized_rover: "buggy" };
    // kit science goal -> a word the mission planner's goal reader knows. Goals not listed are skipped.
    var KIT_GOAL = { biosignatures: "clay", geology: "olivine", subsurface: "water-bearing minerals", water_ice: "water-bearing minerals" };
    var GOAL_ORDER = ["clay", "olivine", "water-bearing minerals"];
    var SEASONS = ["northern_spring", "northern_summer", "northern_autumn", "northern_winter"];   // Ls 0-90, 90-180, 180-270, 270-360

    var byId = function (id) { return document.getElementById(id); };
    var value = function (id) { var e = byId(id); return e && e.value != null ? String(e.value) : ""; };
    var isChecked = function (id) { var e = byId(id); return !!(e && e.checked); };
    var number = function (id) { var n = parseFloat(value(id)); return isFinite(n) ? n : null; };
    var text = function (v) { return typeof v === "string" ? v : ""; };

    // Which page this is, decided when asked: the script may sit in <head>, before the markup exists.
    var isPlanner = function () { return !!(byId("runMission") && byId("mResult")); };
    var isKit = function () { return !isPlanner() && !!(byId("sheet") && byId("form") && byId("vehicle")); };

    // ------------------------------------------------------------ planner page (index.html)

    // index.html's `let mission` / `let selected` live in the global lexical scope: visible here by bare name,
    // not as window properties. typeof keeps this safe on pages that never declare them.
    function currentMission() {
      try {
        if (typeof mission === "undefined") return null;
        var m = mission;
        return m && typeof m === "object" && Array.isArray(m.candidates) && m.candidates.length ? m : null;
      } catch (_) { return null; }
    }
    function currentSelected(m) {
      var i = 0;
      try { if (typeof selected !== "undefined") i = Number(selected); } catch (_) { i = 0; }
      var n = m && Array.isArray(m.candidates) ? m.candidates.length : 0;
      return isFinite(i) && i >= 0 && i < n ? Math.floor(i) : 0;
    }

    function plannerRequest() {
      return { goal: value("goal").trim(), vehicle: value("mVehicle"), season: value("mSeason"),
               priority: value("mPriority"), green_only: isChecked("greenOnly") };
    }

    // The hand-off object, shape fixed by the game spec. null when there is no plan with candidates.
    function plannerPayload(withImages) {
      var m = currentMission();
      if (!m) return null;
      var req = plannerRequest();
      if (!req.goal && m.settings && typeof m.settings.goal === "string") req.goal = m.settings.goal;
      var copy = {}, k;
      for (k in m) {
        if (!Object.prototype.hasOwnProperty.call(m, k)) continue;
        if (k === "goal_ai" || k === "explain_ai") continue;               // client-only fields, carried in `ai`
        if (!withImages && (k === "science_image" || k === "offlimits_image")) continue;
        copy[k] = m[k];
      }
      var g = m.goal_ai || {}, x = m.explain_ai || {};
      return {
        v: 1, savedAt: Date.now(), region: value("region"), selected: currentSelected(m), request: req,
        hour: number("hour"), ls: number("ls"),
        ai: { goal: { reasoning: text(g.reasoning), content: text(g.content) },
              explain: { reasoning: text(x.reasoning), content: text(x.content) } },
        mission: copy
      };
    }

    function store(payload) {
      try { window.localStorage.setItem(STORE_KEY, JSON.stringify(payload)); return true; } catch (_) { return false; }
    }

    function query(pairs) {
      var out = [];
      for (var i = 0; i < pairs.length; i++) {
        if (pairs[i][1] == null || pairs[i][1] === "") continue;
        out.push(encodeURIComponent(pairs[i][0]) + "=" + encodeURIComponent(String(pairs[i][1])));
      }
      return out.length ? "?" + out.join("&") : "";
    }

    // Saves the plan and returns the URL to open. With images when the JSON is small enough, then without,
    // then (storage blocked or full) the request itself in the URL so the game plans it again.
    function plannerUrl() {
      var m = currentMission();
      if (!m) return GAME;
      var full = plannerPayload(true), json = "";
      try { json = JSON.stringify(full); } catch (_) { json = ""; }
      if (json && json.length <= MAX_WITH_IMAGES && store(full)) return GAME + "?src=planner";
      if (store(plannerPayload(false))) return GAME + "?src=planner";
      var r = plannerRequest();
      if (!r.goal && m.settings && typeof m.settings.goal === "string") r.goal = m.settings.goal;
      return GAME + query([["goal", r.goal], ["vehicle", r.vehicle], ["season", r.season], ["priority", r.priority],
                           ["green_only", r.green_only ? 1 : 0], ["region", value("region")], ["cand", currentSelected(m)]]);
    }

    // ------------------------------------------------------------ kit page (kit.html)

    function seasonFromLs(ls) {
      if (ls == null || !isFinite(ls)) return "northern_summer";
      return SEASONS[Math.floor((((ls % 360) + 360) % 360) / 90)];
    }

    function kitGoal() {
      var words = [], box = byId("goals");
      var ticked = box ? box.querySelectorAll("input:checked") : [];
      for (var i = 0; i < ticked.length; i++) {
        var w = KIT_GOAL[ticked[i].value];
        if (w && words.indexOf(w) < 0) words.push(w);
      }
      words.sort(function (a, b) { return GOAL_ORDER.indexOf(a) - GOAL_ORDER.indexOf(b); });
      return words.length ? words.join(" and ") : DEFAULT_GOAL;
    }

    function kitParams() {
      var veh = value("vehicle");
      return {
        goal: kitGoal(),
        vehicle: KIT_VEHICLE[veh] || "four_wheel",
        season: seasonFromLs(number("ls")),
        priority: "safety",
        green_only: 0,
        region: value("region") || "jezero"
      };
    }
    function kitUrl() {
      var p = kitParams();
      return GAME + query([["goal", p.goal], ["vehicle", p.vehicle], ["season", p.season], ["priority", p.priority],
                           ["green_only", p.green_only], ["region", p.region]]);
    }

    // ------------------------------------------------------------ shared

    function launchUrl() {
      try { return isPlanner() ? plannerUrl() : isKit() ? kitUrl() : GAME; } catch (_) { return GAME; }
    }
    function openGame() {
      var url = launchUrl();
      try { window.open(url, "_blank", "noopener"); } catch (_) { /* pop-up blocked: nothing else to do */ }
      return url;
    }

    window.MarswalkGameLaunch = {
      version: VERSION,
      // planner page: the object written to localStorage (null without a plan). kit page: { source, url, params }.
      buildPayload: function () {
        try {
          if (isPlanner()) return plannerPayload(true);
          if (isKit()) return { v: 1, source: "kit", url: kitUrl(), params: kitParams() };
        } catch (_) { /* fall through */ }
        return null;
      },
      open: function () { try { return openGame(); } catch (_) { return null; } }
    };

    // ------------------------------------------------------------ planner page UI

    function mountPlanner() {
      var result = byId("mResult"), run = byId("runMission");
      var btn = byId("playMission"), note = byId("playMissionNote");
      if (!btn) {
        btn = document.createElement("button");                  // inherits the panel's full-width orange button style
        btn.id = "playMission"; btn.type = "button"; btn.hidden = true;
        btn.textContent = "▶ Play this mission";
        result.insertAdjacentElement("afterend", btn);           // outside #mResult: renderMission() empties it
        btn.addEventListener("click", function () { try { if (currentMission()) openGame(); } catch (_) {} });
      }
      if (!note) {
        note = document.createElement("div");
        note.id = "playMissionNote"; note.className = "small"; note.hidden = true;
        btn.insertAdjacentElement("afterend", note);
      }

      var gear = byId("gearLink"), sep = byId("playLinkSep"), link = byId("playLink");
      if (gear && gear.parentNode && !link) {
        sep = document.createElement("span");
        sep.id = "playLinkSep"; sep.hidden = true; sep.textContent = " · ";
        link = document.createElement("a");
        link.id = "playLink"; link.hidden = true; link.target = "_blank"; link.rel = "noopener";
        link.href = GAME; link.textContent = "Play this route as a game";
        gear.insertAdjacentElement("afterend", sep);
        sep.insertAdjacentElement("afterend", link);
        // same pattern as gearLink: fix the href on click, then let the browser open the tab
        link.addEventListener("click", function (ev) {
          try {
            if (!currentMission()) { ev.preventDefault(); return; }
            link.href = launchUrl();
          } catch (_) {}
        });
      }

      var last = "";
      function sync() {
        try {
          var m = currentMission();
          var show = !!m && !run.disabled;                       // disabled = a new plan is being computed
          var n = m ? currentSelected(m) + 1 : 0;
          var key = show + ":" + n;
          if (key === last && btn.hidden === !show) return;
          last = key;
          btn.hidden = !show; note.hidden = !show;
          if (link) { link.hidden = !show; sep.hidden = !show; }
          if (show) note.textContent = "Opens route #" + n + " in a new tab as a game: follow the path to B, do the science, get back to A alive.";
        } catch (_) {}
      }

      try {
        if (typeof MutationObserver !== "undefined") {
          new MutationObserver(sync).observe(result, { childList: true });
          new MutationObserver(sync).observe(run, { attributes: true, attributeFilter: ["disabled"] });
        }
      } catch (_) {}
      window.setInterval(sync, 1500);                            // cheap fallback, e.g. the region changed with an empty panel
      sync();
    }

    // ------------------------------------------------------------ kit page UI

    function mountKit() {
      var sheet = byId("sheet");
      if (!byId("gameLaunchStyle")) {
        var css = document.createElement("style");
        css.id = "gameLaunchStyle";
        css.textContent = ".ghost.play{color:var(--rust,#d9642f);border-color:var(--rust,#d9642f);font-weight:500;white-space:nowrap}" +
          ".ghost.play:hover{color:var(--text,#ece0d3);border-color:var(--rust,#d9642f);background:var(--rust-soft,rgba(217,100,47,.12))}";
        document.head.appendChild(css);
      }
      function decorate() {
        try {
          var tools = sheet.querySelector(".head .tools");
          if (!tools || byId("playGame")) return;
          var b = document.createElement("button");
          b.type = "button"; b.className = "ghost play"; b.id = "playGame";
          b.textContent = "▶ Play";
          b.title = "Play this trip as a game. The mission planner plans a route from the form: traveller, season (Ls), region and science goals.";
          b.setAttribute("aria-label", "Play this trip as a game");
          b.onclick = function () { try { openGame(); } catch (_) {} };
          tools.appendChild(b);                                  // last, after Copy JSON and Print
        } catch (_) {}
      }
      // kit.js replaces the whole sheet on every render; a missing button means a fresh render
      try { if (typeof MutationObserver !== "undefined") new MutationObserver(decorate).observe(sheet, { childList: true }); } catch (_) {}
      decorate();
    }

    function mount() {
      try { if (isPlanner()) mountPlanner(); else if (isKit()) mountKit(); } catch (_) {}
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
    else mount();
  } catch (_) { /* never break the host page */ }
})();
