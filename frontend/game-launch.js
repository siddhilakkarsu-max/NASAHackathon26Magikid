// "Play" launcher: opens game.html (Marswalk: Survive the Route) from the planner pages.
// A plain classic script with no dependencies. Safe to include on any page, more than once; it never throws.
//
//   index.html  adds a compact "Play route #N" action inside Mission results and a collapsed Game section.
//               Both hand the plan on screen to the game
//               through localStorage["marswalk.game.mission"] and a saved plan ID in the new tab's URL.
//               If storage is blocked, that ID restores the exact mission from the server.
//   kit.html    adds a "Play" button to the sheet's tool row. The kit page has no mission plan, so the game
//               plans one live from URL params read off the kit form (traveller, exact Ls, region, science goals).
//
// It reads the planner's `mission`, `selected` and `regionId` bindings by bare name; nothing is
// written to them. The only global it adds is window.MarswalkGameLaunch = { version, buildPayload(), open() }.
(function () {
  "use strict";
  try {
    if (typeof window === "undefined" || typeof document === "undefined") return;
    if (window.MarswalkGameLaunch) return;                       // already loaded on this page

    var VERSION = "1.4.0";
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

    function plannerRegion(m) {
      if (m && typeof m.request_region === "string" && m.request_region) return m.request_region;
      try { if (typeof regionId === "function") return regionId(); } catch (_) {}
      return value("region") || "jezero";
    }

    function plannerRequest(m) {
      // Controls may already contain a draft for the next plan. Recreate the plan being played.
      var s = (m && m.settings) || {}, season = s.season || {};
      var ls = typeof season.ls === "number" && isFinite(season.ls) ? season.ls : number("ls");
      return { goal: text(s.goal) || value("goal").trim(), vehicle: text(s.vehicle && s.vehicle.key) || value("mVehicle"),
               season: text(season.key) || seasonFromLs(ls), ls: ls,
               priority: text(s.priority && s.priority.key) || value("mPriority"),
               green_only: typeof s.green_only === "boolean" ? s.green_only : isChecked("greenOnly"),
               local_hour: typeof s.local_hour === "number" && isFinite(s.local_hour) ? s.local_hour : number("hour") };
    }

    // The hand-off object, shape fixed by the game spec. null when there is no plan with candidates.
    function plannerPayload(withImages) {
      var m = currentMission();
      if (!m) return null;
      var req = plannerRequest(m);
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
        v: 1, savedAt: Date.now(), region: plannerRegion(m), selected: currentSelected(m), request: req,
        hour: req.local_hour, ls: req.ls,
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
      var savedUrl=GAME+query([["src","planner"],["plan",text(m.id)],["cand",currentSelected(m)]]);
      try { json = JSON.stringify(full); } catch (_) { json = ""; }
      if (json && json.length <= MAX_WITH_IMAGES && store(full)) return savedUrl;
      if (store(plannerPayload(false))) return savedUrl;
      var r = plannerRequest(m);
      if (!r.goal && m.settings && typeof m.settings.goal === "string") r.goal = m.settings.goal;
      return GAME + query([["plan", text(m.id)], ["goal", r.goal], ["vehicle", r.vehicle], ["season", r.season], ["ls", r.ls], ["local_hour", r.local_hour], ["priority", r.priority],
                           ["green_only", r.green_only ? 1 : 0], ["region", plannerRegion(m)], ["cand", currentSelected(m)]]);
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
        ls: number("ls"),
        priority: "safety",
        green_only: 0,
        region: value("region") || "jezero"
      };
    }
    function kitUrl() {
      var p = kitParams();
      return GAME + query([["goal", p.goal], ["vehicle", p.vehicle], ["season", p.season], ["ls", p.ls], ["priority", p.priority],
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
      var style = document.createElement("style");
      style.textContent = ".game-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0}" +
        ".game-actions button,#gameSection button{width:auto;margin:0;padding:8px 12px}" +
        ".game-actions[hidden]{display:none}" +
        // "mission ready" button: top right of the map, clear of the map controls and the chat
        "#playFab{position:fixed;top:68px;right:16px;z-index:60;width:auto;margin:0;padding:12px 20px 12px 16px;border:0;border-radius:999px;" +
        "background:#22b455;color:#fff;font:700 15px/1.1 system-ui,sans-serif;letter-spacing:.02em;cursor:pointer;display:flex;align-items:center;gap:10px;" +
        "box-shadow:0 6px 22px rgba(0,0,0,.45),0 0 0 0 rgba(34,180,85,.7);animation:playFabPulse 1.6s ease-out infinite,playFabIn .5s cubic-bezier(.2,1.4,.4,1)}" +
        "#playFab:hover{background:#27c960} #playFab:focus-visible{outline:3px solid #fff;outline-offset:2px} #playFab[hidden]{display:none}" +
        "#playFab small{display:block;font:500 11px/1.2 system-ui,sans-serif;opacity:.9;letter-spacing:0}" +
        "#playFab .tri{width:0;height:0;border-style:solid;border-width:9px 0 9px 15px;border-color:transparent transparent transparent #fff}" +
        "@keyframes playFabPulse{0%{box-shadow:0 6px 22px rgba(0,0,0,.45),0 0 0 0 rgba(34,180,85,.75)}100%{box-shadow:0 6px 22px rgba(0,0,0,.45),0 0 0 22px rgba(34,180,85,0)}}" +
        "@keyframes playFabIn{0%{transform:translateY(-24px) scale(.6);opacity:0}100%{transform:none;opacity:1}}" +
        "@media (prefers-reduced-motion:reduce){#playFab{animation:none}}" +
        "@media (max-width:700px){#playFab{top:auto;bottom:86px;right:12px}}";
      document.head.appendChild(style);
      var actions = byId("gameMissionActions");
      if (!actions) {
        actions = document.createElement("div");
        actions.id = "gameMissionActions"; actions.className = "game-actions"; actions.hidden = true;
        result.insertAdjacentElement("afterend", actions);
      }
      if (!btn) {
        btn = document.createElement("button");
        btn.id = "playMission"; btn.type = "button"; btn.className = "secondary";
        btn.textContent = "Play selected route";
        actions.appendChild(btn);                               // outside #mResult: renderMission() empties it
        btn.addEventListener("click", function () { try { if (currentMission()) openGame(); } catch (_) {} });
      }
      if (!note) {
        note = document.createElement("span");
        note.id = "playMissionNote"; note.className = "small";
        note.textContent = "Survival game · opens a new tab";
        actions.appendChild(note);
      }
      var fab = byId("playFab"), fabText;
      if (!fab) {
        fab = document.createElement("button");
        fab.id = "playFab"; fab.type = "button"; fab.hidden = true;
        var tri = document.createElement("span"); tri.className = "tri"; tri.setAttribute("aria-hidden", "true");
        fabText = document.createElement("span"); fabText.id = "playFabText";
        fab.appendChild(tri); fab.appendChild(fabText);
        document.body.appendChild(fab);
        fab.addEventListener("click", function () { try { if (currentMission()) openGame(); } catch (_) {} });
      } else { fabText = byId("playFabText"); }
      var section = byId("gameSection"), gameButton, gameNote;
      if (!section) {
        section = document.createElement("details");
        section.id = "gameSection"; section.className = "panel-section";
        section.setAttribute("name", "workspace");
        var summary = document.createElement("summary"); summary.textContent = "Game · Survive the route";
        gameNote = document.createElement("p"); gameNote.className = "small"; gameNote.id = "gameSectionNote";
        gameButton = document.createElement("button");
        gameButton.id = "gameOpen"; gameButton.type = "button"; gameButton.className = "secondary";
        section.appendChild(summary); section.appendChild(gameNote); section.appendChild(gameButton);
        (byId("missionResults") || result).insertAdjacentElement("afterend", section);
        gameButton.addEventListener("click", function () { if (!run.disabled) openGame(); });
      } else {
        gameButton = byId("gameOpen"); gameNote = byId("gameSectionNote");
      }

      var last = "";
      function sync() {
        try {
          var m = currentMission();
          var show = !!m && !run.disabled;                       // disabled = a new plan is being computed
          var n = m ? m.candidates[currentSelected(m)].rank || currentSelected(m) + 1 : 0;
          var key = show + ":" + n + ":" + run.disabled;
          if (key === last && actions.hidden === !show) return;
          last = key;
          actions.hidden = !show; btn.disabled = !show;
          btn.textContent = "Play route #" + n;
          fab.hidden = !show;                                    // appears (and animates in) the moment a plan is ready
          if (show) {
            fabText.textContent = "";
            fabText.appendChild(document.createTextNode("MISSION READY \u00b7 PLAY ROUTE"));
            var sm = document.createElement("small"); sm.textContent = "Route #" + n + " \u00b7 first-person game \u00b7 new tab"; fabText.appendChild(sm);
            fab.setAttribute("aria-label", "Mission ready: play route " + n + " in the survival game (opens a new tab)");
          }
          gameButton.disabled = run.disabled;
          gameButton.textContent = show ? "Play route #" + n : "Browse game missions";
          gameNote.textContent = show
            ? "Play your selected route #" + n + " and sample at B. Your goal, vehicle and start time are already included. Opens in a new tab."
            : "Plan a mission above, then play its route. Opens in a new tab.";
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
