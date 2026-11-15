// Helmut: a tiny pixel astronaut who floats beside the planner assistant and reacts to what is going on.
//
// Self-contained (frontend/mascot.js + frontend/mascot.css). Helmut only *watches* the page: the assistant chat
// (#gmChat, built by maps_ui.js), the planner status, route playback, Walker's view, the layer / hour / season /
// region controls, the `mission` and `viewer` globals, and the user's own activity. It never changes app state, and
// every hook is optional: if an element is missing, that reaction simply never fires.
//
// The only global it adds is window.marsMascot = { say(text), react(mood, ms), show(), hide(), state() }.
(() => {
  "use strict";
  if (window.marsMascot) return;

  const NAME = "Helmut";
  const UNIT = 3.5;                                   // CSS px per sprite pixel; the sprite is 16 x 18 pixels
  const W = 16 * UNIT, H = 18 * UNIT;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (id) => document.getElementById(id);
  const now = () => Date.now();
  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const store = {
    get(k, d) { try { const v = localStorage.getItem("helmut." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("helmut." + k, JSON.stringify(v)); } catch { /* private mode: forget */ } },
  };
  // index.html declares these with top-level let/const, so they are shared globals but not window properties
  /* global mission, viewer */
  const currentMission = () => (typeof mission === "undefined" ? undefined : mission);
  const globe = () => (typeof viewer === "undefined" ? undefined : viewer);

  // ------------------------------------------------------------------------------------------------ sprite ----
  const PAL = { k: "#2a1d17", W: "#f6efe8", w: "#d6c3b4", O: "#e0703a", o: "#9c4520", V: "#1b2140", v: "#4a5f9e",
                Y: "#ffd36b", B: "#9ee6ff", P: "#ff8fb1" };
  function rects(rows, x0 = 0, y0 = 0, cls = "") {
    let s = "";
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length;) {
        const c = row[x];
        if (c === ".") { x++; continue; }
        let n = 1;
        while (row[x + n] === c) n++;
        s += `<rect${cls ? ` class="${cls}"` : ""} x="${x0 + x}" y="${y0 + y}" width="${n}" height="1" fill="${PAL[c]}"/>`;
        x += n;
      }
    });
    return s;
  }
  const HEAD = rects([
    "....kkkkkkkk....",
    "...kWWWWWWWWk...",
    "..kWWVVVVVVWWk..",
    "..kWVvVVVVVVWk..",
    ".OkWVVVVVVVVWkO.",
    ".OkWVVVVVVVVWkO.",
    "..kWVVVVVVVVWk..",
    "..kwWVVVVVVWwk..",
    "...kwwWWWWwwk...",
    "....kkkkkkkk....",
  ]);
  const BODY = rects([
    "....kWWWWWWk....",
    "...kWWOOOOWWk...",
    "...kWWOoOoWWk...",
    "...kwWWWWWWwk...",
    "....kwwkkwwk....",
  ], 0, 10);
  const ARM_L = rects([".kk.", "kWWk", "kWWk", "kOOk", ".kk."], 0, 10);
  const ARM_R = rects([".kk.", "kWWk", "kWWk", "kOOk", ".kk."], 12, 10);
  const LEG_L = rects([".kWk", "kOOk", "kkkk"], 3, 15);
  const LEG_R = rects(["kWk.", "kOOk", "kkkk"], 9, 15);
  const FLAG = rects(["kOOOY", "kOYOO", "kOOOO"], 14, 5) + rects(["k", "k", "k", "k", "k"], 14, 8);
  const FLAME = (x) => `<rect class="fl1" x="${x}" y="18" width="2" height="1" fill="${PAL.O}"/>` +
                       `<rect class="fl2" x="${x}" y="19" width="2" height="1" fill="${PAL.Y}"/>`;

  const E = (pts) => pts.map(([x, y, w = 1, h = 1]) => `<rect class="e" x="${x}" y="${y}" width="${w}" height="${h}"/>`).join("");
  const EYES = {
    normal: E([[6, 4, 1, 2], [9, 4, 1, 2]]),
    closed: E([[5, 5, 2, 1], [9, 5, 2, 1]]),
    happy:  E([[4, 5], [5, 4], [6, 5], [9, 5], [10, 4], [11, 5]]),
    wide:   E([[5, 4, 2, 2], [9, 4, 2, 2]]),
    sad:    E([[6, 4], [5, 5], [9, 4], [10, 5]]),
    focus:  E([[5, 4], [6, 5], [10, 4], [9, 5]]),
    dizzy:  E([[4, 3], [6, 3], [5, 4], [4, 5], [6, 5], [9, 3], [11, 3], [10, 4], [9, 5], [11, 5]]),
    heart:  E([[4, 3], [6, 3], [4, 4, 3, 1], [5, 5], [9, 3], [11, 3], [9, 4, 3, 1], [10, 5]]),
    star:   E([[5, 3], [4, 4, 3, 1], [5, 5], [10, 3], [9, 4, 3, 1], [10, 5]]),
    scan:   `<rect class="e scan" x="4" y="4" width="2" height="2"/>`,
  };

  const svg = `
<svg viewBox="0 0 16 18" width="${W}" height="${H}" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
  <polygon class="cone" points="5,-0.5 -9,-6 -9,5"/>
  <g class="flames">${FLAME(4)}${FLAME(10)}</g>
  <g class="legL">${LEG_L}</g><g class="legR">${LEG_R}</g>
  <g class="armL">${ARM_L}</g>
  <g class="torso">${BODY}</g>
  <g class="armR">${ARM_R}<g class="flag">${FLAG}</g></g>
  <g class="head">
    <rect class="ant" x="12" y="-2" width="1" height="1"/>
    <rect x="12" y="-1" width="1" height="1" fill="${PAL.k}"/>
    <rect class="lamp" x="5" y="-1" width="2" height="1"/>
    ${HEAD}
    <g class="eyes"></g>
    <g class="mouth"><rect class="e" x="7" y="6" width="2" height="1"/></g>
    <rect class="blush" x="4" y="6" width="1" height="1" fill="${PAL.P}"/>
    <rect class="blush" x="11" y="6" width="1" height="1" fill="${PAL.P}"/>
    <rect class="sweat" x="14" y="1" width="1" height="2" fill="${PAL.B}"/>
    <g class="frost">${rects(["B..", ".B.", "B.B"], 3, 0)}${rects(["..B", "B.B"], 11, 1)}</g>
  </g>
</svg>`;

  // -------------------------------------------------------------------------------------------------- DOM ----
  const root = document.createElement("div");
  root.id = "helmut";
  root.hidden = true;
  root.setAttribute("aria-hidden", "true");          // decorative: the chat itself carries all the information
  root.innerHTML = `<div class="helmut-fig" title="${NAME}: boop me, drag me, double-click to send me home">${svg}</div>` +
                   `<div class="helmut-bubble"></div>`;
  document.body.append(root);
  const fig = root.querySelector(".helmut-fig");
  const eyesG = root.querySelector(".eyes");
  const bubble = root.querySelector(".helmut-bubble");

  // ------------------------------------------------------------------------------------------- mood state ----
  // base: what Helmut is doing for a while (idle, listen, think, plan, ride, sleep).
  // react: a short reaction that overrides the base, then fades back to it.
  // flags: independent looks that stack on top (night lamp, radiation glow, cold, hot, flag, talking...).
  const EYE_FOR = { idle: "normal", listen: "normal", think: "normal", plan: "scan", ride: "happy", sleep: "closed",
                    happy: "happy", celebrate: "star", sad: "sad", scared: "wide", wake: "wide", dizzy: "dizzy",
                    love: "heart", wave: "happy", salute: "focus", whoa: "wide", cough: "closed", curious: "normal",
                    proud: "happy", carried: "wide", yawn: "closed", nod: "happy" };
  let base = "idle", react = null, reactTimer = 0, eyeOverride = null;
  const flags = new Set();
  let visible = false, leaving = false;

  function render() {
    const mood = react || base;
    fig.className = "helmut-fig m-" + mood + [...flags].map(f => " f-" + f).join("");
    const eyes = eyeOverride || EYE_FOR[mood] || "normal";
    if (eyesG.dataset.k !== eyes) { eyesG.dataset.k = eyes; eyesG.innerHTML = EYES[eyes]; }
  }
  function setBase(m) { if (base === m) return; base = m; if (m !== "sleep") lastActive = now(); render(); syncThinkBubble(); }
  function reactTo(mood, ms = 1400) {
    clearTimeout(reactTimer);
    react = mood;
    // restart the CSS animation even when the same reaction repeats
    fig.className = "helmut-fig"; void fig.offsetWidth;
    render();
    reactTimer = setTimeout(() => { react = null; render(); }, ms);
  }
  const flag = (name, on) => { on ? flags.add(name) : flags.delete(name); render(); };

  // blink now and then, when the eyes are open
  (function blink() {
    setTimeout(() => {
      const k = eyesG.dataset.k;
      if (visible && !eyeOverride && (k === "normal" || k === "focus" || k === "wide")) {
        eyeOverride = "closed"; render();
        setTimeout(() => { eyeOverride = null; render(); }, 120);
        if (Math.random() < 0.2) setTimeout(() => { eyeOverride = "closed"; render(); setTimeout(() => { eyeOverride = null; render(); }, 110); }, 260);
      }
      blink();
    }, 2200 + Math.random() * 3800);
  })();

  // ----------------------------------------------------------------------------------------- speech bubble ----
  let lastQuip = 0, bubbleTimer = 0, thinkBubble = false;
  const recent = [];
  function say(text, { force = false, ms = 0 } = {}) {
    if (!visible || !text) return false;
    if (!force && now() - lastQuip < 5000) return false;
    lastQuip = now();
    thinkBubble = false;
    bubble.className = "helmut-bubble";
    bubble.textContent = text;
    void bubble.offsetWidth;
    bubble.classList.add("on");
    clearTimeout(bubbleTimer);
    bubbleTimer = setTimeout(() => { bubble.classList.remove("on"); syncThinkBubble(); }, ms || clamp(1600 + text.length * 55, 2200, 5200));
    return true;
  }
  // pick a line nobody heard in the last few quips
  function line(list) {
    const fresh = list.filter(t => !recent.includes(t));
    const t = pick(fresh.length ? fresh : list);
    recent.push(t); if (recent.length > 8) recent.shift();
    return t;
  }
  function syncThinkBubble() {
    const want = visible && base === "think";
    if (want && !bubble.classList.contains("on")) {
      thinkBubble = true;
      bubble.className = "helmut-bubble think on";
      bubble.innerHTML = "<i></i><i></i><i></i>";
    } else if (!want && thinkBubble) {
      thinkBubble = false;
      bubble.classList.remove("on");
    }
  }

  // ------------------------------------------------------------------------------------------- particles ----
  function burst(kind, n = 1, opts = {}) {
    if (reduced || !visible) return;
    for (let i = 0; i < n; i++) {
      const p = document.createElement("span");
      p.className = "helmut-p " + kind;
      if (kind === "confetti") {
        p.style.setProperty("--dx", (Math.random() * 120 - 60).toFixed(0) + "px");
        p.style.setProperty("--dy", (-40 - Math.random() * 60).toFixed(0) + "px");
        p.style.setProperty("--rot", (Math.random() * 720 - 360).toFixed(0) + "deg");
        p.style.background = pick(["#e0703a", "#ffd36b", "#9ee6ff", "#ff8fb1", "#f6efe8", "#7fd17a"]);
        p.style.animationDelay = (Math.random() * 120).toFixed(0) + "ms";
      } else if (kind === "puff") {
        p.style.setProperty("--dx", ((i - (n - 1) / 2) * 14).toFixed(0) + "px");
      } else if (kind === "spark") {
        p.style.left = (10 + Math.random() * 40).toFixed(0) + "px";
        p.style.top = (Math.random() * 30).toFixed(0) + "px";
        p.style.animationDelay = (i * 90) + "ms";
      }
      if (opts.text) p.textContent = opts.text;
      p.addEventListener("animationend", () => p.remove(), { once: true });
      root.append(p);
    }
  }

  // ------------------------------------------------------------------------------------ show, hide, place ----
  const chatBox = () => $("gmChat");
  let drag = store.get("offset", { dx: 0, dy: 0 });
  if (!Number.isFinite(drag?.dx) || !Number.isFinite(drag?.dy)) drag = { dx: 0, dy: 0 };
  let pos = { x: -999, y: -999 }, raf = 0;

  function anchor() {
    const box = chatBox();
    if (!box || box.hidden) return null;
    const r = box.getBoundingClientRect();
    if (!r.width) return null;
    // float beside the chat when there is room, otherwise hang just under its bottom-right corner
    let x = r.right + 16, y = r.bottom - H - 10, side = "right";
    if (x + W + 20 > innerWidth) { x = r.right - W - 14; y = r.bottom + 10; side = "below"; }
    return { x, y, side };
  }
  function place() {
    raf = 0;
    if (!visible) return;
    const a = anchor();
    // no visible chat to stand beside (e.g. a collapsed layout): stay out of sight instead of parking at 0,0
    root.style.visibility = a ? "" : "hidden";
    if (a) {
      const x = clamp(a.x + drag.dx, 6, innerWidth - W - 6), y = clamp(a.y + drag.dy, 30, innerHeight - H - 8);
      if (Math.abs(x - pos.x) > 0.5 || Math.abs(y - pos.y) > 0.5) {
        pos = { x, y };
        root.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
        // the bubble opens away from the chat: rightwards when Helmut floats beside it and there is room
        root.classList.toggle("bubble-left", (a.side === "right" && x + 210 < innerWidth) || x < 200);
      }
    }
    gaze();
    raf = requestAnimationFrame(place);
  }

  let greeted = false, opens = 0;
  function show() {
    if (visible && !leaving) return;
    leaving = false;
    visible = true;
    root.hidden = false;
    lastActive = now();
    if (!raf) place();
    root.classList.remove("leave");
    root.classList.add("arrive");
    setTimeout(() => {
      root.classList.remove("arrive");
      burst("puff", 3);
      opens++;
      const met = store.get("met", false);
      reactTo("wave", 1800);
      if (!met) { store.set("met", true); say(`Hi, I'm ${NAME}! I'll keep you company out here.`, { force: true, ms: 4200 }); }
      else if (!greeted) say(line([`Welcome back, commander!`, `${NAME}, back on duty!`, `Good to see you again!`]), { force: true });
      else say(line(["Reporting for duty!", "Helmet on. Let's go!", "Miss me?", "What's the plan?"]), { force: true });
      greeted = true;
      syncAmbient();
    }, reduced ? 50 : 820);
  }
  function hide() {
    if (!visible || leaving) return;
    leaving = true;
    say(line(["Over and out!", "Helmut out!", "See you up there!"]), { force: true, ms: 900 });
    setTimeout(() => {
      if (!leaving) return;
      root.classList.add("leave");
      setTimeout(() => { if (!leaving) return; visible = false; leaving = false; root.hidden = true; root.classList.remove("leave"); }, reduced ? 50 : 650);
    }, reduced ? 0 : 500);
  }

  // ---------------------------------------------------------------------------------------- eyes follow ----
  let pointer = null, gazeTarget = null, gazeX = 0, gazeY = 0;
  addEventListener("pointermove", (e) => { pointer = { x: e.clientX, y: e.clientY }; activity(); }, { passive: true });
  function gaze() {
    let dx = 0, dy = 0;
    const k = eyesG.dataset.k;
    if (base === "think" && !react) { dx = 1; dy = -1; }
    else if (k === "normal" || k === "wide" || k === "focus") {
      const t = gazeTarget || pointer;
      if (t) {
        const cx = pos.x + W / 2, cy = pos.y + H * 0.28;
        const vx = t.x - cx, vy = t.y - cy;
        dx = Math.abs(vx) > 40 ? Math.sign(vx) : 0;
        dy = Math.abs(vy) > 70 ? Math.sign(vy) : 0;
      }
    }
    if (dx !== gazeX || dy !== gazeY) { gazeX = dx; gazeY = dy; eyesG.setAttribute("transform", `translate(${dx} ${dy})`); }
  }

  // ---------------------------------------------------------------------------- boop, drag, send home ----
  let boops = [], dragging = null;
  fig.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    fig.setPointerCapture(e.pointerId);
    dragging = { x0: e.clientX, y0: e.clientY, dx0: drag.dx, dy0: drag.dy, moved: false };
  });
  fig.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const mx = e.clientX - dragging.x0, my = e.clientY - dragging.y0;
    if (!dragging.moved && Math.hypot(mx, my) < 5) return;
    if (!dragging.moved) { dragging.moved = true; setBase(base === "sleep" ? "idle" : base); react = "carried"; render(); say(line(["Wheee!", "Whoa, zero-g!", "Where are we going?"])); }
    drag = { dx: dragging.dx0 + mx, dy: dragging.dy0 + my };
  });
  const endDrag = (e) => {
    if (!dragging) return;
    const d = dragging; dragging = null;
    if (d.moved) { store.set("offset", drag); react = null; reactTo("happy", 600); burst("puff", 2); return; }
    if (e.type === "pointerup") boop();
  };
  fig.addEventListener("pointerup", endDrag);
  fig.addEventListener("pointercancel", endDrag);
  fig.addEventListener("dblclick", () => {
    drag = { dx: 0, dy: 0 }; store.set("offset", drag);
    reactTo("happy", 700); say("Home sweet home.", { force: true });
  });
  function boop() {
    activity();
    if (base === "sleep") { wake(); return; }
    const t = now();
    boops = boops.filter(b => t - b < 1600); boops.push(t);
    if (boops.length >= 5) {
      boops = [];
      reactTo("dizzy", 2400); burst("orbit", 1);
      say(line(["Whoa… seeing stars.", "Okay, okay, I'm dizzy!", "Which way is up?"]), { force: true });
      return;
    }
    const r = Math.random();
    if (r < 0.22) { reactTo("love", 1500); flag("blush", true); setTimeout(() => flag("blush", false), 1500); burst("heart", 1); say(line(["Aww.", "Hehe, that tickles!", "Best commander ever."]), { force: true }); }
    else if (r < 0.4) { reactTo("celebrate", 1150); say(line(["Zero-g flip!", "Ta-da!"]), { force: true }); }
    else { reactTo("happy", 650); say(line(["Hey!", "Boop!", "Hehe.", "Careful, this suit's a rental!", "I'm on the clock here!", "Beep boop.", "That's my helmet!"]), { force: true }); }
  }

  // ---------------------------------------------------------------------------------- idle and sleeping ----
  let lastActive = now(), zzzTimer = 0;
  function activity() {
    lastActive = now();
    if (base === "sleep" && !dragging) wake();
  }
  function wake() {
    clearInterval(zzzTimer);
    setBase(document.activeElement && chatBox()?.contains(document.activeElement) ? "listen" : "idle");
    reactTo("wake", 900);
    burst("pop", 1, { text: "!" });
    if (Math.random() < 0.6) say(line(["Huh? I'm up!", "I wasn't sleeping!", "Just resting my eyes…"]), { force: true });
  }
  addEventListener("keydown", activity, { passive: true });
  addEventListener("wheel", activity, { passive: true });
  setInterval(() => {
    if (!visible || base !== "idle" || react || dragging) return;
    if (now() - lastActive > 45000) {
      setBase("sleep");
      clearInterval(zzzTimer);
      if (!reduced) zzzTimer = setInterval(() => { if (base === "sleep" && visible) burst("zzz", 1, { text: "z" }); else clearInterval(zzzTimer); }, 1500);
    }
  }, 2000);

  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { hiddenAt = now(); return; }
    if (visible && hiddenAt && now() - hiddenAt > 20000) {
      if (base === "sleep") wake();
      reactTo("wave", 1800);
      say(line(["You're back!", "There you are!", "I held the fort."]), { force: true });
    }
    hiddenAt = 0;
  });

  // ------------------------------------------------------------------------------------- the chat itself ----
  const NAME_RE = new RegExp(`\\b${NAME}\\b`, "i");
  let talkTimer = 0, talkUntil = 0;
  function talk(text) {
    clearInterval(talkTimer);
    talkUntil = now() + clamp(text.length * 38, 700, 3800);
    flag("talk", true);
    talkTimer = setInterval(() => {
      if (now() > talkUntil) { clearInterval(talkTimer); flag("talk", false); root.classList.remove("mouth-open"); return; }
      root.classList.toggle("mouth-open");
    }, 130);
  }
  function onUser(text) {
    activity();
    reactTo("nod", 500);
    if (NAME_RE.test(text)) {
      setTimeout(() => { reactTo("love", 1400); flag("blush", true); setTimeout(() => flag("blush", false), 1400); say("That's me!", { force: true }); }, 350);
    } else if (/\b(thanks|thank you|thx|ty|awesome|great job|nice)\b/i.test(text)) {
      setTimeout(() => { reactTo("love", 1300); burst("heart", 1); say(line(["Anytime!", "Happy to help!", "Teamwork!"]), { force: true }); }, 350);
    } else if (/^(hi|hello|hey|yo|howdy)\b/i.test(text)) {
      setTimeout(() => { reactTo("wave", 1400); }, 300);
    }
  }
  function onBot(text) {
    talk(text);
    const after = (fn) => setTimeout(fn, clamp(text.length * 38, 700, 3800) + 150);
    if (/couldn't reach the planner|server error/i.test(text)) {
      after(() => { reactTo("sad", 2600); flag("signal", true); setTimeout(() => flag("signal", false), 2600); burst("rain", 1); say(line(["Lost signal with Houston…", "Hello? Anyone there?"]), { force: true }); });
    } else if (/^(No safe route|I couldn't find|That layer isn't available|The planner says)/i.test(text)) {
      after(() => { reactTo("sad", 2000); say(line(["Aw, no luck. Try another spot?", "Hmm, that didn't work.", "Mars is tricky sometimes."])); });
    } else if (/^Found \d+ route/i.test(text)) {
      // the mission watcher celebrates; here Helmut just looks pleased while "speaking"
      after(() => reactTo("proud", 1200));
    } else if (/dust storm|storm/i.test(text)) {
      after(() => { reactTo("scared", 1600); say(line(["Storms? Eek.", "Hope my visor's sealed…"])); });
    } else if (/radiation/i.test(text)) {
      after(() => { reactTo("scared", 1200); flag("hot", true); setTimeout(() => flag("hot", false), 1600); });
    } else if (/\b(water|clay|ice|delta|lake|olivine|river)\b/i.test(text)) {
      after(() => { reactTo("happy", 900); burst("spark", 4); });
    } else if (/\?\s*$/.test(text)) {
      after(() => reactTo("curious", 1500));
    }
  }

  function wireChat(box) {
    const log = box.querySelector(".log");
    const input = box.querySelector("form input");
    if (!visible && !box.hidden) show();
    new MutationObserver(() => (box.hidden ? hide() : show())).observe(box, { attributes: true, attributeFilter: ["hidden"] });
    if (log) {
      let seen = 0;
      new MutationObserver((records) => {
        for (const r of records) {
          for (const n of r.addedNodes) {
            if (!(n instanceof HTMLElement) || !n.classList.contains("msg")) continue;
            const text = n.textContent || "";
            seen++;
            if (n.classList.contains("user")) onUser(text);
            else if (n.classList.contains("wait")) setBase(/^Planning/i.test(text) ? "plan" : "think");
            else if (seen > 1) onBot(text);
          }
          for (const n of r.removedNodes) {
            if (n instanceof HTMLElement && n.classList.contains("wait") && (base === "think" || base === "plan")) setBase(restingBase());
          }
        }
      }).observe(log, { childList: true });
    }
    if (input) {
      let longOnce = false;
      input.addEventListener("focus", () => { if (base === "idle" || base === "sleep") setBase("listen"); });
      input.addEventListener("blur", () => { if (base === "listen") setBase("idle"); gazeTarget = null; });
      input.addEventListener("input", () => {
        activity();
        if (base === "idle") setBase("listen");
        const r = input.getBoundingClientRect();
        gazeTarget = { x: r.left + Math.min(r.width, 8 * input.value.length), y: r.top + r.height / 2 };
        root.classList.remove("key"); void root.offsetWidth; root.classList.add("key");
        if (!longOnce && input.value.length > 70) { longOnce = true; say("Ooh, a big plan…"); }
        if (NAME_RE.test(input.value)) flag("blush", true); else if (flags.has("blush") && !react) flag("blush", false);
      });
    }
  }
  const restingBase = () => (routePlaying ? "ride" : document.activeElement && chatBox()?.contains(document.activeElement) ? "listen" : "idle");

  // -------------------------------------------------------------------------------------- the whole app ----
  // planner status line: "Planning…" while a mission is computed
  function watchText(id, fn) {
    const n = $(id);
    if (!n) return;
    let prev = n.textContent;
    new MutationObserver(() => { const t = n.textContent; if (t !== prev) { const p = prev; prev = t; fn(t, p); } })
      .observe(n, { childList: true, characterData: true, subtree: true });
  }
  watchText("mStatus", (t) => {
    if (/^Planning/i.test(t)) {
      setBase("plan");
      say(line(["Crunching the terrain…", "Checking every rock…", "Plotting a safe path…", "Asking the rocks nicely…"]));
      return;
    }
    if (base === "plan") setBase(restingBase());
    if (/^Type a goal/i.test(t) && visible) { reactTo("curious", 1500); burst("pop", 1, { text: "?" }); }
  });

  // a new mission with routes: celebrate, hold up a flag, count it
  let lastMission = null;
  setInterval(() => {
    const m = currentMission();
    if (m === lastMission) return;
    lastMission = m;
    const ok = !!m?.candidates?.length;
    flag("flag", ok);
    if (!ok) return;
    if (base === "plan") setBase(restingBase());
    const n = store.get("missions", 0) + 1;
    store.set("missions", n);
    if (!visible) return;
    reactTo("celebrate", 1300);
    burst("confetti", 22);
    say(n === 1 ? "First mission! Flag up!" : n % 5 === 0 ? `Mission #${n}! You're a natural.`
        : line(["Route found! Flag up!", "We have a path!", "Ready to roll!", "Plot twist: it's safe!"]), { force: true });
  }, 600);

  // route playback: "Pause" on the button means it is playing
  let routePlaying = false;
  watchText("playRoute", (t, prev) => {
    const playing = /^Pause/i.test(t);
    if (playing && !routePlaying) {
      routePlaying = true; setBase("ride");
      say(line(["Here we go!", "Vroom!", "Left, right, left…", "Hold on tight!"]));
    } else if (!playing && routePlaying) {
      routePlaying = false; setBase(restingBase());
      if (/^Replay/i.test(t)) { reactTo("proud", 1600); burst("spark", 5); say(line(["Made it back safe!", "Mission complete!", "Home before dark!"]), { force: true }); }
    }
  });
  watchText("walkerStatus", (t, prev) => {
    if (/^Walker's view 1\//.test(t) && !/^Walker's view/.test(prev || "")) { reactTo("salute", 1800); say(line(["Boots on the ground!", "One small step…", "Nice view from down here!"]), { force: true }); }
    else if (/unavailable/i.test(t)) reactTo("sad", 1500);
  });

  // layers: Helmut has opinions about all of them
  const LAYERS = [
    [/radiation|dose|gcr/i, () => { reactTo("scared", 1600); say(line(["Yikes, radiation! Good thing I've got a helmet.", "Glowing in all the wrong ways…"])); }],
    [/dust/i, () => { reactTo("cough", 1300); burst("puff", 4); say(line(["*cough* Dusty out there!", "Achoo! Mars dust."])); }],
    [/wind/i, () => { reactTo("whoa", 1500); say(line(["Hold onto your helmet!", "Breezy!"])); }],
    [/temperature|thermal/i, () => { reactTo("scared", 900); flag("cold", true); setTimeout(() => flag("cold", false), 2600); say(line(["Brrr…", "Chilly, even for me."])); }],
    [/slope/i, () => { reactTo("whoa", 1100); say(line(["Steep! Careful.", "No skateboarding there."])); }],
    [/suitab/i, () => { reactTo("happy", 900); burst("spark", 4); say(line(["Finding the good spots!", "Ooh, where should we go?"])); }],
    [/imagery|ctx|photo/i, () => { reactTo("curious", 1300); say(line(["Ooh, sharp photos!", "Say cheese!"])); }],
    [/illumination|sun/i, () => { reactTo("happy", 900); say("Sunny side up!"); }],
    [/firm|inertia|cost/i, () => { reactTo("curious", 1100); }],
  ];
  function activeLayers() {
    return ["layer", "globalLayer", "regionalLayer"].map(id => $(id)?.value || "").filter(Boolean);
  }
  function syncAmbient() {
    flag("rad", activeLayers().some(v => /radiation|dose|gcr/i.test(v)));
    const h = +($("hour")?.value ?? 12);
    flag("night", h < 6 || h >= 18.5);
  }
  let layerQuipAt = 0;
  document.addEventListener("change", (e) => {
    const id = e.target?.id;
    if (id === "layer" || id === "globalLayer" || id === "regionalLayer") {
      syncAmbient();
      const v = e.target.value || "";
      if (!visible || !v || now() - layerQuipAt < 800) return;
      layerQuipAt = now();
      const hit = LAYERS.find(([re]) => re.test(v));
      if (hit) hit[1]();
    } else if (id === "region") {
      if (visible) { reactTo("curious", 1500); say(line(["Ooh, new place!", "Never been here before!", "Let's explore!"])); }
    }
  }, true);

  // time of day and season, said once the slider settles
  let hourTimer = 0, wasNight = null, lsTimer = 0, wasStormSeason = null;
  document.addEventListener("input", (e) => {
    const id = e.target?.id;
    if (id === "hour") {
      syncAmbient();
      clearTimeout(hourTimer);
      hourTimer = setTimeout(() => {
        const night = flags.has("night");
        if (visible && wasNight !== null && night !== wasNight) {
          if (night) { reactTo("whoa", 900); say(line(["Lights on!", "Night shift. Lamp on!"])); }
          else { reactTo("yawn", 1500); say(line(["Morning, Mars!", "*yawn* Sunrise already?"])); }
        }
        wasNight = night;
      }, 700);
    } else if (id === "ls") {
      clearTimeout(lsTimer);
      lsTimer = setTimeout(() => {
        const ls = +e.target.value, storm = ls >= 180 && ls <= 330;
        if (visible && wasStormSeason !== null && storm !== wasStormSeason) {
          if (storm) { reactTo("scared", 1300); say("Dust storm season… keep an eye out."); }
          else { reactTo("happy", 900); say("Calmer skies ahead."); }
        }
        wasStormSeason = storm;
      }, 700);
    }
  }, true);
  wasNight = (() => { const h = +($("hour")?.value ?? 12); return h < 6 || h >= 18.5; })();
  wasStormSeason = (() => { const ls = +($("ls")?.value ?? 90); return ls >= 180 && ls <= 330; })();
  syncAmbient();

  // the globe: long camera flights make Helmut hold onto his helmet
  $("wholeMars")?.addEventListener("click", () => { if (visible) { reactTo("whoa", 1500); say(line(["Look at it all!", "Whole planet. Wow."])); } });
  (function watchCamera(tries = 0) {
    const v = globe();
    if (!v?.camera?.moveStart) { if (tries < 40) setTimeout(() => watchCamera(tries + 1), 500); return; }
    let flyTimer = 0, flying = false, wheeAt = 0;
    v.camera.moveStart.addEventListener(() => {
      clearTimeout(flyTimer);
      flyTimer = setTimeout(() => {
        if (!visible || react || base !== "idle" && base !== "listen") return;
        flying = true; reactTo("whoa", 60000);
        if (now() - wheeAt > 25000) { wheeAt = now(); say(line(["Wheee!", "Warp speed!", "Are we there yet?"])); }
      }, 1300);
    });
    v.camera.moveEnd.addEventListener(() => {
      clearTimeout(flyTimer);
      if (flying) { flying = false; if (react === "whoa") { react = null; render(); } }
    });
  })();

  // the autoplay tour has its own captions; Helmut steps aside while it runs
  new MutationObserver(() => root.classList.toggle("touring", document.body.classList.contains("touring")))
    .observe(document.body, { attributes: true, attributeFilter: ["class"] });

  // ------------------------------------------------------------------------------------------- start up ----
  (function waitForChat(tries = 0) {
    const box = chatBox();
    if (box) { wireChat(box); return; }
    if (tries < 60) setTimeout(() => waitForChat(tries + 1), 250);
  })();
  addEventListener("resize", () => { if (visible && !raf) place(); });
  render();

  window.marsMascot = {
    say: (text) => say(String(text || ""), { force: true }),
    react: (mood, ms) => reactTo(String(mood), ms),
    show, hide,
    state: () => ({ visible, base, react, flags: [...flags], missions: store.get("missions", 0) }),
  };
})();
