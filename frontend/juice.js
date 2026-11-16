// Juice: makes the planner fun to click around. Loaded last (defer); it only adds feedback on top of the planner's own
// controls and never changes what they do.
//
//   * every button, chip, section and menu item squishes and springs back, with a ripple where you pressed
//   * soft synthesized sounds (Web Audio, no files) and a tiny vibration on phones; one toggle mutes them
//   * the left rail's active item is a sliding pill; chips sparkle when they switch on
//   * sliders show a live value bubble (sun/moon, season), fill their track and tick as they pass each step
//   * map clicks send a sonar ping; Plan mission glows when there is a goal and fires confetti cannons on success
//   * route cards slide in, count their scores up and tilt under the pointer
//   * Explorer XP: actions earn XP with combos, 15 badges (2 secret) unlock with a toast, levels have names.
//     A ring in the rail shows the level; click it for the badge collection, sound toggle and reset.
//
// Progress lives in localStorage ("jz.v1"). The only global is window.marsJuice = { xp(), unlock(id), reset() }.
(() => {
  "use strict";
  if (window.marsJuice) return;
  const $ = (id) => document.getElementById(id);
  const el = (tag, props = {}, ...kids) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
  // Line icons in the same style as the menu's (maps_ui.js): 24×24, stroked in the text colour, no emoji.
  const ICONS = {
    storm: '<path d="M4 7h11a3 3 0 1 0-3-3"/><path d="M3 11h15a3 3 0 1 1-3 3"/><path d="M6 15h6"/><path d="M8 19h7"/>',
    sprout: '<path d="M12 21v-9"/><path d="M12 12C12 8 9 5.5 4.5 5.5 4.5 10 7.5 12 12 12z"/><path d="M12 14c0-3.5 2.5-6 7-6 0 4-2.5 6-7 6z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    leaf: '<path d="M5 19c0-8 5-13 14-14 0 9-5 14-13 14z"/><path d="M5 19 13 11"/>',
    snow: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="m9.5 4.5 2.5 2 2.5-2M9.5 19.5l2.5-2 2.5 2"/>',
    moon: '<path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a6.5 6.5 0 0 0 10 10z"/>',
    sunrise: '<path d="M3 18h18M7 18a5 5 0 0 1 10 0"/><path d="M12 4v5M9.5 6.5 12 4l2.5 2.5"/><path d="M4.5 12.5l1.4 1.4M19.5 12.5l-1.4 1.4"/>',
    sunset: '<path d="M3 18h18M7 18a5 5 0 0 1 10 0"/><path d="M12 9V4M9.5 6.5 12 9l2.5-2.5"/><path d="M4.5 12.5l1.4 1.4M19.5 12.5l-1.4 1.4"/>',
    pack: '<path d="M7 8a5 5 0 0 1 10 0v11a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2z"/><path d="M10 4.5V3h4v1.5"/><path d="M9.5 14h5v4h-5zM7 11h10"/>',
    rocket: '<path d="M14.5 4.5c2.6-1.3 5-1.2 5-1.2s.1 2.4-1.2 5l-5.6 5.6-3.6-3.6z"/><path d="m9.1 10.3-3.4-.4-2.2 2.2 3.8 1.2M13.7 14.9l.4 3.4-2.2 2.2-1.2-3.8"/><circle cx="15.4" cy="8.6" r="1.4"/><path d="M6.5 17.5 4 20"/>',
    antenna: '<path d="M5 11a7 7 0 0 1 7-7M5 11l8 8M5 11 3 21h10"/><circle cx="12.5" cy="11.5" r="1.3"/><path d="M15 4.5a5 5 0 0 1 4.5 4.5M15 1.8a8 8 0 0 1 7.2 7.2"/>',
    map: '<path d="M3.5 6.5 9 4l6 2.5L20.5 4v13.5L15 20l-6-2.5-5.5 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>',
    compass: '<circle cx="12" cy="12" r="8.5"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    radiation: '<circle cx="12" cy="12" r="1.8"/><path d="M12 4a8 8 0 0 1 6.9 4l-4.3 2.5M5.1 8A8 8 0 0 1 12 4v5M8.6 19.4l2.5-4.4M15.4 19.4 12.9 15"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 2.6 14.6 0 17M12 3.5c-2.6 2.4-2.6 14.6 0 17"/>',
    rock: '<path d="M3 18 6.5 9.5 11 7l5 1.5 3.5 4.5L21 18z"/><path d="m11 7 1.5 5L16 8.5M12.5 12 9 18"/>',
    flag: '<path d="M5 21V4"/><path d="M5 4h12l-2.5 4 2.5 4H5"/>',
    satellite: '<rect x="9.5" y="9.5" width="5" height="5" rx="1" transform="rotate(45 12 12)"/><path d="m5 5 3.5 3.5M15.5 15.5 19 19"/><path d="m3 7 4-4 3 3-4 4zM14 17l3-3 4 4-3 3z"/><path d="M15 3.5a5.5 5.5 0 0 1 5.5 5.5"/>',
    rover: '<path d="M4 15V11h16v4z"/><path d="M7 11V8h7l2 3"/><path d="M14 8V5h3"/><circle cx="6.5" cy="18" r="2"/><circle cx="12" cy="18" r="2"/><circle cx="17.5" cy="18" r="2"/>',
    boot: '<path d="M7 3h5v8l6 2.5a2.5 2.5 0 0 1 1.5 2.3V19H4.5V14L7 11z"/><path d="M4.5 16.5h15M12 7h-2.5M12 9.5H9.5"/>',
    robot: '<rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 8V4.5"/><circle cx="12" cy="3.5" r="1"/><circle cx="9.5" cy="13" r="1.2"/><circle cx="14.5" cy="13" r="1.2"/><path d="M10 16.5h4M3 12v3M21 12v3"/>',
    midnight: '<circle cx="12" cy="12" r="8.5"/><path d="M12 12V6.5"/><circle cx="12" cy="12" r=".8"/>',
    question: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.7.3-1 .8-1 1.5v.6"/><circle cx="12" cy="16.8" r=".6"/>',
    soundOn: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    soundOff: '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="m16 9.5 5 5M21 9.5l-5 5"/>',
  };
  const icon = (name) => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.setAttribute("class", "jz-icon");
    s.innerHTML = ICONS[name] || ICONS.question;
    return s;
  };
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const now = () => performance.now();
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  /* global mission */
  const currentMission = () => (typeof mission === "undefined" ? undefined : mission);

  if (!document.querySelector('link[href="/juice.css"]')) document.head.append(el("link", { rel: "stylesheet", href: "/juice.css" }));

  // ----------------------------------------------------------------------------------------------- state ----
  const KEY = "jz.v1";
  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(KEY) || "null");
      if (s && Number.isFinite(s.xp)) return { xp: s.xp, badges: s.badges || {}, n: s.n || {}, layers: s.layers || [],
                                               regions: s.regions || [], sound: s.sound !== false };
    } catch { /* fall through */ }
    return { xp: 0, badges: {}, n: {}, layers: [], regions: [], sound: true };
  }
  let S = load();
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch { /* private mode */ } };
  const count = (k, by = 1) => { S.n[k] = (S.n[k] || 0) + by; save(); return S.n[k]; };

  // ----------------------------------------------------------------------------------------------- sound ----
  let actx = null, master = null;
  function audio() {
    if (!S.sound) return null;
    if (!actx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      actx = new AC();
      master = actx.createGain();
      master.gain.value = 0.16;
      master.connect(actx.destination);
    }
    if (actx.state === "suspended") actx.resume();
    return actx;
  }
  function tone(freq, { t = 0, dur = 0.08, type = "sine", vol = 1, slide = 0 } = {}) {
    const c = audio();
    if (!c) return;
    const t0 = c.currentTime + t, o = c.createOscillator(), g = c.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t0);
    if (slide) o.frequency.exponentialRampToValueAtTime(freq * slide, t0 + dur);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(vol, t0 + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g); g.connect(master);
    o.start(t0); o.stop(t0 + dur + 0.03);
  }
  // The click: a premium-switch "tk… tik", built from three tiny layers so it is crisp, not beepy.
  //   1. transient: ~1-2 ms of high-passed noise with a bright peak (the snap you feel in your teeth)
  //   2. body: a 20-35 ms resonant ping falling in pitch (the plastic of the key)
  //   3. weight: a soft low thump, on the press only (the key bottoming out)
  // The release is lighter and higher. Each click varies its pitch by a few percent so repeats never sound
  // machine-gunned, and it pans gently toward where you clicked. kind: "down" | "up" | "tick" (slider detent).
  const noiseFor = new WeakMap();
  function noise(c) {
    let b = noiseFor.get(c);
    if (!b) {
      b = c.createBuffer(1, Math.floor(c.sampleRate * 0.06), c.sampleRate);
      const d = b.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      noiseFor.set(c, b);
    }
    return b;
  }
  function clickInto(c, dest, t, kind = "down", pan = 0, pitch = 1) {
    const up = kind === "up", tick = kind === "tick";
    const jit = pitch * (1 + (Math.random() - 0.5) * 0.07);
    const out = c.createGain();
    out.gain.value = tick ? 0.32 : up ? 0.6 : 1;
    if (c.createStereoPanner) { const p = c.createStereoPanner(); p.pan.value = pan; out.connect(p); p.connect(dest); }
    else out.connect(dest);
    // 1. transient
    const n = c.createBufferSource();
    n.buffer = noise(c);
    const hp = c.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = (up || tick ? 3600 : 2400) * jit;
    const pk = c.createBiquadFilter(); pk.type = "peaking"; pk.frequency.value = (up || tick ? 6800 : 4700) * jit;
    pk.Q.value = 1.4; pk.gain.value = 9;
    const ng = c.createGain();
    ng.gain.setValueAtTime(0, t);
    ng.gain.linearRampToValueAtTime(tick ? 1.5 : up ? 1.8 : 2.4, t + 0.0005);
    ng.gain.exponentialRampToValueAtTime(0.001, t + (tick ? 0.006 : up ? 0.009 : 0.014));
    n.connect(hp); hp.connect(pk); pk.connect(ng); ng.connect(out);
    n.start(t, Math.random() * 0.04); n.stop(t + 0.02);
    // 2. body
    const o = c.createOscillator(), og = c.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime((tick ? 3400 : up ? 2900 : 2050) * jit, t);
    o.frequency.exponentialRampToValueAtTime((tick ? 3000 : up ? 2450 : 1650) * jit, t + 0.02);
    og.gain.setValueAtTime(0.0001, t);
    og.gain.exponentialRampToValueAtTime(tick ? 0.12 : up ? 0.16 : 0.34, t + 0.0008);
    og.gain.exponentialRampToValueAtTime(0.0001, t + (tick ? 0.014 : up ? 0.022 : 0.034));
    o.connect(og); og.connect(out);
    o.start(t); o.stop(t + 0.05);
    // 3. weight
    if (kind === "down") {
      const l = c.createOscillator(), lg = c.createGain();
      l.type = "sine";
      l.frequency.setValueAtTime(260 * jit, t);
      l.frequency.exponentialRampToValueAtTime(130, t + 0.02);
      lg.gain.setValueAtTime(0.0001, t);
      lg.gain.exponentialRampToValueAtTime(0.15, t + 0.0015);
      lg.gain.exponentialRampToValueAtTime(0.0001, t + 0.026);
      l.connect(lg); lg.connect(out);
      l.start(t); l.stop(t + 0.06);
    }
  }
  function click(kind, x = innerWidth / 2, pitch = 1) {
    const c = audio();
    if (!c) return;
    clickInto(c, master, c.currentTime + 0.002, kind, clamp(x / innerWidth * 2 - 1, -1, 1) * 0.35, pitch);
  }
  const SFX = {
    press: (x) => click("down", x),
    release: (x) => click("up", x),
    on: () => { tone(660, { dur: 0.07, type: "triangle", vol: 0.5 }); tone(990, { t: 0.06, dur: 0.1, type: "triangle", vol: 0.5 }); },
    off: () => { tone(620, { dur: 0.06, type: "triangle", vol: 0.35 }); tone(415, { t: 0.05, dur: 0.08, type: "triangle", vol: 0.35 }); },
    open: () => tone(260, { dur: 0.16, vol: 0.3, slide: 2.6 }),
    tick: (f = 1, x) => click("tick", x, f),
    ping: () => { tone(540, { dur: 0.4, vol: 0.4, slide: 2.1 }); tone(1080, { t: 0.09, dur: 0.32, vol: 0.12 }); },
    xp: (step = 0) => tone(880 * Math.pow(1.1225, step * 2), { dur: 0.1, vol: 0.32 }),
    success: () => [523, 659, 784, 1047].forEach((f, i) => tone(f, { t: i * 0.08, dur: 0.24, type: "triangle", vol: 0.5 })),
    badge: () => { [784, 988, 1319].forEach((f, i) => tone(f, { t: i * 0.07, dur: 0.55, vol: 0.38 })); tone(2637, { t: 0.22, dur: 0.7, vol: 0.1 }); },
    levelup: () => {
      [523, 659, 784, 1047, 1319].forEach((f, i) => tone(f, { t: i * 0.07, dur: 0.18, type: "square", vol: 0.16 }));
      [523, 659, 784, 1047].forEach(f => tone(f, { t: 0.4, dur: 1, type: "triangle", vol: 0.26 }));
    },
  };
  const sfx = (name, ...a) => { try { SFX[name]?.(...a); } catch { /* audio is a bonus */ } };
  const buzz = (ms = 8) => { try { navigator.vibrate?.(ms); } catch { /* not supported */ } };

  // ------------------------------------------------------------------------------------------ fx overlay ----
  const fx = el("div", { id: "jzFx" });
  fx.setAttribute("aria-hidden", "true");
  document.body.append(fx);
  function spawn(cls, x, y, { vars = {}, text = "", keep = false, life = 3000 } = {}) {
    if (reduced && !keep) return null;
    const p = el("span", { className: "jz-" + cls, textContent: text });
    p.style.left = x + "px"; p.style.top = y + "px";
    for (const [k, v] of Object.entries(vars)) p.style.setProperty(k, v);
    p.addEventListener("animationend", () => p.remove(), { once: true });
    setTimeout(() => p.remove(), life);
    fx.append(p);
    return p;
  }
  const COLORS = ["#e0703a", "#ffd36b", "#9ee6ff", "#ff8fb1", "#f6efe8", "#7fd17a"];
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const mid = (node) => { const r = node.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
  function sparks(x, y, n = 9, spread = 34) {
    for (let i = 0; i < n; i++) {
      spawn("spark", x, y, { vars: { "--a": (i / n * 360 + Math.random() * 20) + "deg", "--d": (spread * (0.7 + Math.random() * 0.6)) + "px",
                                    "--c": pick(COLORS) } });
    }
  }
  function confetti(x, y, n, dir = 0) {             // dir: -1 fires up-left, 1 up-right, 0 all around
    for (let i = 0; i < n; i++) {
      const ang = dir ? (dir > 0 ? -70 : -110) + (Math.random() * 50 - 25) : Math.random() * 360;
      const v = 160 + Math.random() * 260, rad = ang * Math.PI / 180;
      spawn("confetti", x, y, { life: 2600, vars: {
        "--dx": (Math.cos(rad) * v).toFixed(0) + "px", "--dy": (Math.sin(rad) * v).toFixed(0) + "px",
        "--r": (Math.random() * 900 - 450).toFixed(0) + "deg", "--c": pick(COLORS),
        "--w": (4 + Math.random() * 5).toFixed(0) + "px", "--delay": (Math.random() * 140).toFixed(0) + "ms" } });
    }
  }

  // --------------------------------------------------------------------------- press physics everywhere ----
  const PRESSABLE = 'button, summary, [role="button"], [role="menuitem"], select, label.check';
  let lastPointer = [innerWidth / 2, innerHeight / 2], lastUser = -1e9, held = false;
  // was this change caused by the user? (a held pointer, e.g. a long slider drag, or a press/key just now)
  const userish = () => held || now() - lastUser < 900;
  const release = () => { held = false; lastUser = now(); };
  addEventListener("pointerup", release, true);
  addEventListener("pointercancel", release, true);
  addEventListener("pointerdown", (e) => {
    lastPointer = [e.clientX, e.clientY];
    lastUser = now();
    held = true;
    if (e.button !== 0) return;
    const t = e.target.closest?.(PRESSABLE);
    if (!t || t.disabled || t.closest("#jzFx, .helmut-fig, .cesium-viewer-toolbar")) return;
    audio();                                       // first gesture unlocks audio
    t.classList.remove("jz-release");
    t.classList.add("jz-press");
    spawn("ring", e.clientX, e.clientY);
    sfx("press", e.clientX);
    const up = (ev) => {
      removeEventListener("pointerup", up, true);
      removeEventListener("pointercancel", up, true);
      if (ev.type === "pointerup") sfx("release", ev.clientX);
      t.classList.remove("jz-press");
      t.classList.add("jz-release");
      setTimeout(() => t.classList.remove("jz-release"), 500);
    };
    addEventListener("pointerup", up, true);
    addEventListener("pointercancel", up, true);
  }, true);
  addEventListener("keydown", () => { lastUser = now(); }, true);
  // keyboard presses click too: Enter/Space on a focused button press on keydown, release on keyup
  const keyX = (n) => { const r = n.getBoundingClientRect(); return r.left + r.width / 2; };
  let keyHeld = null;
  addEventListener("keydown", (e) => {
    if ((e.key !== "Enter" && e.key !== " ") || e.repeat || keyHeld) return;
    const t = e.target.closest?.('button, summary, [role="button"], [role="menuitem"]');
    if (!t || t.disabled) return;
    keyHeld = t; audio(); sfx("press", keyX(t));
  }, true);
  addEventListener("keyup", (e) => {
    if (keyHeld && (e.key === "Enter" || e.key === " ")) { sfx("release", keyX(keyHeld)); keyHeld = null; }
  }, true);

  // ------------------------------------------------------------------------------------ toggles sparkle ----
  const chips = $("gmChips");
  if (chips) {
    new MutationObserver((records) => {
      for (const r of records) {
        const b = r.target;
        if (!(b instanceof HTMLButtonElement)) continue;
        const was = (r.oldValue || "").split(/\s+/).includes("on"), on = b.classList.contains("on");
        if (was === on || !userish()) continue;
        if (on) { const [x, y] = mid(b); sparks(x, y, 10, 40); sfx("on"); buzz(10); b.classList.add("jz-pop"); setTimeout(() => b.classList.remove("jz-pop"), 500); }
        else sfx("off");
      }
    }).observe(chips, { subtree: true, attributes: true, attributeFilter: ["class"], attributeOldValue: true });
  }
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (!(t instanceof HTMLInputElement) || t.type !== "checkbox" || !userish()) return;
    if (t.checked) { const [x, y] = mid(t); sparks(x, y, 6, 22); sfx("on"); buzz(6); } else sfx("off");
  }, true);
  document.addEventListener("toggle", (e) => {
    const d = e.target;
    if (!(d instanceof HTMLDetailsElement) || !d.open || !userish()) return;
    sfx("open");
    d.classList.remove("jz-opened"); void d.offsetWidth; d.classList.add("jz-opened");
    gain("open", 2);
  }, true);

  // ------------------------------------------------------------------------------------ rail glide pill ----
  const rail = $("gmRail");
  if (rail) {
    const pill = el("div", { id: "jzRailPill" });
    rail.prepend(pill);
    const sync = () => {
      const b = rail.querySelector("button.on");
      pill.classList.toggle("on", !!b);
      if (!b) return;
      pill.style.transform = `translate(${b.offsetLeft}px, ${b.offsetTop}px)`;
      pill.style.width = b.offsetWidth + "px";
      pill.style.height = b.offsetHeight + "px";
    };
    new MutationObserver(sync).observe(rail, { subtree: true, attributes: true, attributeFilter: ["class"] });
    addEventListener("resize", sync);
    sync();
  }

  // --------------------------------------------------------------------------------------------- sliders ----
  const bubble = el("div", { id: "jzSlide" });
  bubble.setAttribute("aria-hidden", "true");
  document.body.append(bubble);
  const SEASON = (ls) => (ls >= 180 && ls <= 330 ? "storm" : ls < 90 ? "sprout" : ls < 180 ? "sun" : ls < 270 ? "leaf" : "snow");
  const SLIDERS = {
    hour: { step: 1, icon: (v) => (v < 5 || v >= 19.5 ? "moon" : v < 7.5 ? "sunrise" : v >= 17 ? "sunset" : "sun"), label: (v) => `${Math.floor(v) % 24}:${String(Math.round((v % 1) * 60)).padStart(2, "0")}` },
    ls: { step: 15, icon: SEASON, label: (v) => "Ls " + Math.round(v) + "°" },
    budget: { step: 1, icon: () => "pack", label: (v) => v + " h EVA" },
  };
  const fill = (r) => { const p = (r.value - r.min) / ((r.max - r.min) || 1) * 100; r.style.setProperty("--jz-fill", p.toFixed(1) + "%"); };
  const bucket = new WeakMap();
  let slideTimer = 0;
  function slide(r, show) {
    fill(r);
    const cfg = SLIDERS[r.id];
    const v = +r.value, b = Math.floor(v / (cfg?.step || ((r.max - r.min) / 12 || 1)));
    if (bucket.has(r) && bucket.get(r) !== b && userish()) {
      const rr = r.getBoundingClientRect();
      sfx("tick", 0.85 + 0.4 * (v - r.min) / ((r.max - r.min) || 1), rr.left + rr.width * (v - r.min) / ((r.max - r.min) || 1));
      buzz(3);
    }
    bucket.set(r, b);
    if (!cfg || !show) return;
    const rect = r.getBoundingClientRect();
    if (!rect.width) return;
    const x = rect.left + 7.5 + (v - r.min) / ((r.max - r.min) || 1) * (rect.width - 15);
    bubble.replaceChildren(icon(cfg.icon(v)), " " + cfg.label(v));
    bubble.style.transform = `translate(${x.toFixed(1)}px, ${(rect.top - 6).toFixed(1)}px) translate(-50%, -100%)`;
    bubble.classList.add("on");
    clearTimeout(slideTimer);
    slideTimer = setTimeout(() => bubble.classList.remove("on"), 900);
  }
  for (const r of document.querySelectorAll('input[type="range"]')) { fill(r); bucket.set(r, null); }
  document.addEventListener("input", (e) => {
    const r = e.target;
    if (r instanceof HTMLInputElement && r.type === "range") slide(r, userish());
  }, true);
  document.addEventListener("pointerdown", (e) => {
    const r = e.target;
    if (r instanceof HTMLInputElement && r.type === "range") setTimeout(() => slide(r, true), 0);
  }, true);

  // ------------------------------------------------------------------------------------- map sonar ping ----
  const map = $("map");
  if (map) {
    let down = null;
    map.addEventListener("pointerdown", (e) => { down = e.target.tagName === "CANVAS" && e.button === 0 ? { x: e.clientX, y: e.clientY, t: now() } : null; });
    map.addEventListener("pointerup", (e) => {
      if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5 || now() - down.t > 450) return;
      down = null;
      spawn("ping", e.clientX, e.clientY, { keep: true });
      spawn("ping2", e.clientX, e.clientY);
      sfx("ping");
      if (count("points") >= 5) unlock("rock");
      gain("point", 5, e.clientX, e.clientY);
    });
  }

  // ------------------------------------------------------------------------------- planning and results ----
  const run = $("runMission"), goal = $("goal");
  const syncReady = () => run?.classList.toggle("jz-ready", !!goal?.value.trim() && !run.disabled);
  goal?.addEventListener("input", syncReady);
  if (run) new MutationObserver(syncReady).observe(run, { attributes: true, attributeFilter: ["disabled"] });
  syncReady();

  function cannons() {
    const m = $("map")?.getBoundingClientRect() || { left: 0, right: innerWidth, bottom: innerHeight };
    confetti(m.left + 20, m.bottom - 10, 46, 1);
    confetti(m.right - 20, m.bottom - 10, 46, -1);
    fx.classList.remove("flash"); void fx.offsetWidth; fx.classList.add("flash");
  }
  let lastMission = currentMission(), animatedMission = null;
  setInterval(() => {
    const m = currentMission();
    if (m === lastMission) return;
    lastMission = m;
    if (!m?.candidates?.length) return;
    sfx("success");
    buzz(30);
    cannons();
    const n = count("missions");
    unlock("trail");
    if (n >= 5) unlock("control");
    gain("mission", 40, innerWidth / 2, innerHeight * 0.4, true);
  }, 500);

  const results = $("mResult");
  if (results) {
    new MutationObserver(() => {
      const cards = [...results.querySelectorAll("details.card")];
      if (!cards.length) return;
      const m = currentMission();
      const fresh = m && m !== animatedMission;
      if (fresh) animatedMission = m;
      cards.forEach((c, i) => {
        if (c.dataset.jz) return;
        c.dataset.jz = "1";
        if (!fresh) return;
        c.style.setProperty("--i", i);
        c.classList.add("jz-in");
        countUp(c.querySelector("summary"));
      });
    }).observe(results, { childList: true, subtree: true });
    results.addEventListener("pointermove", (e) => {
      const c = e.target.closest?.("details.card");
      if (!c || reduced) return;
      const r = c.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width - 0.5, py = (e.clientY - r.top) / r.height - 0.5;
      c.style.setProperty("--rx", (-py * 6).toFixed(2) + "deg");
      c.style.setProperty("--ry", (px * 8).toFixed(2) + "deg");
      c.style.setProperty("--gx", ((px + 0.5) * 100).toFixed(0) + "%");
      c.classList.add("jz-tilt");
    });
    results.addEventListener("pointerout", (e) => {
      const c = e.target.closest?.("details.card");
      if (c && !c.contains(e.relatedTarget)) c.classList.remove("jz-tilt");
    });
  }
  function countUp(summary) {
    const node = summary && [...summary.childNodes].find(n => n.nodeType === 3 && /score \d+\/100/.test(n.textContent));
    if (!node || reduced) return;
    const original = node.textContent, target = +original.match(/score (\d+)\/100/)[1], t0 = now(), dur = 700;
    const step = () => {
      if (!node.isConnected) return;
      const k = clamp((now() - t0) / dur, 0, 1), v = Math.round(target * (1 - Math.pow(1 - k, 3)));
      node.textContent = original.replace(/score \d+\/100/, `score ${v}/100`);
      if (k < 1) requestAnimationFrame(step); else node.textContent = original;
    };
    requestAnimationFrame(step);
  }

  // ------------------------------------------------------------------------------ playback and walking ----
  const watchText = (id, fn) => {
    const n = $(id);
    if (!n) return;
    let prev = n.textContent;
    new MutationObserver(() => { const t = n.textContent; if (t !== prev) { const p = prev; prev = t; fn(t, p); } })
      .observe(n, { childList: true, characterData: true, subtree: true });
  };
  watchText("playRoute", (t, prev) => { if (/^Pause/i.test(t) && !/^Pause/i.test(prev)) { unlock("road"); gain("play", 15); } });
  watchText("walkerStatus", (t, prev) => { if (/^Walker's view/.test(t) && !/^Walker's view/.test(prev || "")) { unlock("boots"); gain("walk", 15); } });

  // ------------------------------------------------------------------------ layers, region, time, season ----
  const RAD = /radiation|dose|gcr/i;
  document.addEventListener("change", (e) => {
    const id = e.target?.id, v = e.target?.value || "";
    if ((id === "layer" || id === "globalLayer" || id === "regionalLayer") && v) {
      if (!S.layers.includes(v)) { S.layers.push(v); save(); }
      unlock("layer");
      if (RAD.test(v)) unlock("rad");
      if (S.layers.length >= 5) unlock("carto");
      if (userish()) gain("layer", 10);
    } else if (id === "region" && v) {
      if (!S.regions.includes(v)) { S.regions.push(v); save(); }
      if (S.regions.length >= 3) unlock("globe");
      if (userish()) gain("region", 10);
    }
  }, true);
  let settle = 0;
  document.addEventListener("input", (e) => {
    const id = e.target?.id;
    if (id !== "hour" && id !== "ls") return;
    const user = userish();
    clearTimeout(settle);
    settle = setTimeout(() => {
      const v = +e.target.value;
      if (id === "hour") {
        if (v < 5 || v >= 19.5) unlock("night");
        if (v === 0 || v === 24) unlock("midnight");
      } else if (v >= 180 && v <= 330) unlock("storm");
      if (user) gain("time", 5);
    }, 600);
  }, true);

  // ------------------------------------------------------------------------------- chat, Helmut, landing ----
  (function waitForChat(tries = 0) {
    const log = document.querySelector("#gmChat .log");
    if (!log) { if (tries < 60) setTimeout(() => waitForChat(tries + 1), 250); return; }
    new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes) {
        if (n instanceof HTMLElement && n.classList.contains("msg") && n.classList.contains("user")) { unlock("comms"); gain("chat", 10); }
      }
    }).observe(log, { childList: true });
  })();
  document.addEventListener("click", (e) => {
    if (e.target.closest?.(".helmut-fig") && count("boops") >= 10) unlock("boop");
  }, true);
  $("startExploring")?.addEventListener("click", () => setTimeout(() => unlock("liftoff"), 700));

  // ------------------------------------------------------------------------------------- XP and levels ----
  const LEVELS = ["Cadet", "Rover Rookie", "Dust Walker", "Crater Hopper", "Ridge Runner", "Canyon Diver",
                  "Red Planeteer", "Olympus Legend"];
  const need = (lv) => 100 + 60 * (lv - 1);
  function levelOf(xp) { let lv = 1, rest = xp; while (rest >= need(lv)) { rest -= need(lv); lv++; } return { lv, rest, need: need(lv) }; }
  const title = (lv) => LEVELS[Math.min(lv - 1, LEVELS.length - 1)];
  let combo = 0, comboAt = -1e9;
  const cool = {};
  function gain(kind, amount, x, y, force = false) {
    const t = now();
    if (!force && cool[kind] && t - cool[kind] < 2500) return;
    cool[kind] = t;
    combo = t - comboAt < 4000 ? Math.min(combo + 1, 5) : 1;
    comboAt = t;
    const pts = amount * combo;
    if (x == null) [x, y] = lastPointer;
    spawn("float", x, y - 14, { keep: true, text: `+${pts} XP` + (combo > 1 ? `  ×${combo}` : "") });
    if (combo > 1) spawn("combo", x, y - 34, { text: ["", "", "Nice!", "Great!", "Awesome!", "STELLAR!"][combo] });
    sfx("xp", combo - 1);
    addXP(pts);
  }
  function addXP(n) {
    const before = levelOf(S.xp).lv;
    S.xp += n; save();
    meterSync(true);
    const after = levelOf(S.xp).lv;
    if (after > before) setTimeout(() => levelUp(after), 450);
  }
  function levelUp(lv) {
    const o = el("div", { id: "jzLevel" }, el("small", { textContent: "LEVEL UP" }), el("b", { textContent: "Lv " + lv }),
                el("span", { textContent: title(lv) }));
    document.body.append(o);
    setTimeout(() => o.remove(), 2600);
    sfx("levelup"); buzz(40);
    cannons();
    const [x, y] = [innerWidth / 2, innerHeight / 2];
    sparks(x, y, 18, 140);
    try { window.marsMascot?.react("celebrate", 1300); window.marsMascot?.say(`Level ${lv}! ${title(lv)}!`); } catch { /* optional */ }
  }

  // ----------------------------------------------------------------------------------------------- badges ----
  const BADGES = [
    { id: "liftoff", icon: "rocket", name: "Liftoff", desc: "Start exploring Mars" },
    { id: "comms", icon: "antenna", name: "Comms Check", desc: "Talk to the planner assistant" },
    { id: "layer", icon: "map", name: "Map Nerd", desc: "Turn on a map layer" },
    { id: "carto", icon: "compass", name: "Cartographer", desc: "Try 5 different layers" },
    { id: "rad", icon: "radiation", name: "Rad Aware", desc: "Check the radiation map" },
    { id: "night", icon: "moon", name: "Night Owl", desc: "Move the clock to night" },
    { id: "storm", icon: "storm", name: "Storm Chaser", desc: "Visit dust-storm season (Ls 180–330)" },
    { id: "globe", icon: "globe", name: "Globetrotter", desc: "Visit 3 regions" },
    { id: "rock", icon: "rock", name: "Rock Hound", desc: "Inspect 5 spots on the map" },
    { id: "trail", icon: "flag", name: "Trailblazer", desc: "Plan your first mission" },
    { id: "control", icon: "satellite", name: "Mission Control", desc: "Plan 5 missions" },
    { id: "road", icon: "rover", name: "Road Trip", desc: "Play a route" },
    { id: "boots", icon: "boot", name: "Boots Down", desc: "Stand on Mars in Walker's view" },
    { id: "boop", icon: "robot", name: "Boop Master", desc: "Boop Helmut 10 times", secret: true },
    { id: "midnight", icon: "midnight", name: "Witching Sol", desc: "Set the clock to exactly midnight", secret: true },
  ];
  const queue = [];
  let toasting = false;
  function unlock(id) {
    if (S.badges[id]) return;
    const b = BADGES.find(x => x.id === id);
    if (!b) return;
    S.badges[id] = Date.now(); save();
    queue.push(b);
    if (!toasting) nextToast();
    addXP(50);
    panelSync();
  }
  function nextToast() {
    const b = queue.shift();
    if (!b) { toasting = false; return; }
    toasting = true;
    const t = el("div", { className: "jz-toast" + (b.secret ? " secret" : "") },
      el("i", {}, icon(b.icon)),
      el("div", {}, el("small", { textContent: b.secret ? "Secret badge unlocked!" : "Badge unlocked" }),
        el("b", { textContent: b.name }), el("span", { textContent: b.desc })),
      el("em", { textContent: "+50 XP" }));
    t.setAttribute("role", "status");
    document.body.append(t);
    sfx("badge"); buzz(20);
    requestAnimationFrame(() => { const [x, y] = mid(t.querySelector("i")); sparks(x, y, 14, 60); });
    try { window.marsMascot?.react("love", 1400); } catch { /* optional */ }
    const done = $("jzMeter");
    if (done) { done.classList.remove("jz-bump"); void done.offsetWidth; done.classList.add("jz-bump"); }
    setTimeout(() => { t.classList.add("out"); setTimeout(() => { t.remove(); nextToast(); }, 380); }, 3200);
  }

  // ------------------------------------------------------------------------------- level ring and panel ----
  const meter = el("button", { id: "jzMeter", type: "button", title: "Explorer level: badges and XP" });
  meter.innerHTML = `<svg viewBox="0 0 36 36" aria-hidden="true"><circle class="bg" cx="18" cy="18" r="15"/>` +
                    `<circle class="fg" cx="18" cy="18" r="15" pathLength="100"/></svg><b></b><span></span>`;
  const panel = el("div", { id: "jzPanel", hidden: true });
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Explorer badges");
  document.body.append(panel);
  if (rail) {
    const more = $("uiMoreBtn");
    more ? rail.insertBefore(meter, more) : rail.append(meter);
  } else {
    meter.classList.add("floating");
    document.body.append(meter);
  }
  let shownXP = S.xp;
  function meterSync(animate) {
    const { lv, rest, need: n } = levelOf(S.xp);
    meter.querySelector("b").textContent = lv;
    meter.querySelector("span").textContent = "Lv " + lv;
    meter.querySelector(".fg").style.strokeDasharray = `${(rest / n * 100).toFixed(1)} 100`;
    meter.setAttribute("aria-label", `Explorer level ${lv}, ${title(lv)}: ${rest} of ${n} XP. Open badges`);
    if (animate && S.xp !== shownXP) { meter.classList.remove("jz-bump"); void meter.offsetWidth; meter.classList.add("jz-bump"); }
    shownXP = S.xp;
    if (!panel.hidden) panelSync();
  }
  function panelSync() {
    if (panel.hidden) return;
    const { lv, rest, need: n } = levelOf(S.xp);
    const got = BADGES.filter(b => S.badges[b.id]).length;
    const tiles = BADGES.map(b => {
      const on = !!S.badges[b.id], hide = b.secret && !on;
      const tile = el("div", { className: "tile" + (on ? " on" : "") + (hide ? " secret" : ""),
                               title: hide ? "Secret badge: keep exploring" : `${b.name}: ${b.desc}` },
        el("i", {}, icon(hide ? "question" : b.icon)), el("span", { textContent: hide ? "???" : b.name }));
      return tile;
    });
    const sound = el("button", { type: "button", className: "ghost" }, icon(S.sound ? "soundOn" : "soundOff"), S.sound ? " Sound on" : " Sound off");
    Object.assign(sound, {
      onclick: () => { S.sound = !S.sound; save(); if (S.sound) sfx("on"); panelSync(); } });
    const reset = el("button", { type: "button", className: "ghost", textContent: "Reset progress",
      onclick: () => {
        if (reset.dataset.armed) { S = { xp: 0, badges: {}, n: {}, layers: [], regions: [], sound: S.sound }; save(); meterSync(false); panelSync(); return; }
        reset.dataset.armed = "1"; reset.textContent = "Click again to reset";
      } });
    panel.replaceChildren(
      el("header", {},
        el("div", { className: "lv" }, el("b", { textContent: lv }), el("small", { textContent: "LEVEL" })),
        el("div", {}, el("strong", { textContent: title(lv) }),
          el("div", { className: "bar" }, el("i", { style: `width:${(rest / n * 100).toFixed(1)}%` })),
          el("small", { textContent: `${rest} / ${n} XP to level ${lv + 1} · ${got}/${BADGES.length} badges` })),
        el("button", { type: "button", className: "x", textContent: "×", title: "Close", onclick: () => openPanel(false) })),
      el("div", { className: "grid" }, ...tiles),
      el("footer", {}, sound, reset));
  }
  function openPanel(on) {
    panel.hidden = !on;
    meter.classList.toggle("on", on);
    if (on) {
      const r = meter.getBoundingClientRect();
      panel.style.left = (r.right + 10) + "px";
      panel.style.bottom = Math.max(12, innerHeight - r.bottom - 40) + "px";
      panelSync();
      sfx("open");
    }
  }
  meter.addEventListener("click", (e) => { e.stopPropagation(); openPanel(panel.hidden); });
  document.addEventListener("click", (e) => { if (!panel.hidden && !panel.contains(e.target) && !meter.contains(e.target)) openPanel(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) { openPanel(false); meter.focus(); } });
  meterSync(false);
  if ($("landing")?.classList.contains("gone")) unlock("liftoff");   // after setup: unlock() needs the panel

  window.marsJuice = {
    xp: () => ({ xp: S.xp, ...levelOf(S.xp), title: title(levelOf(S.xp).lv), badges: Object.keys(S.badges) }),
    unlock,
    reset: () => { S = { xp: 0, badges: {}, n: {}, layers: [], regions: [], sound: S.sound }; save(); meterSync(false); panelSync(); },
  };
})();
