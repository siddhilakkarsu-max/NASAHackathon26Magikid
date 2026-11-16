"use strict";

// A rotating presentation camera around the real Mars-fixed ephemeris. The
// camera's half-solar-turn path is deliberately not a spacecraft trajectory.
function createMarsOverview({ viewer, ellipsoid, moons, lighting, controls,
  selectPlanner, restorePlanningLight, isPlanner = () => false, eligible = true, isBusy = () => false }) {
  // A previously cached module must never throw inside Cesium's render loop.
  // Versioned script URLs prevent this on upgrade; this guard also handles a
  // partial deployment or an independently cached embedded-browser resource.
  if (typeof moons?.systemFrame !== 'function' || typeof lighting?.updateFromPosition !== 'function' ||
      typeof lighting?.clearEphemeris !== 'function') {
    controls.button.textContent = 'Refresh animation';
    controls.button.setAttribute('aria-pressed', 'false');
    controls.readout.textContent = 'Animation needs a refresh. The map is still available.';
    controls.button.onclick = () => {
      const url = new URL(location.href); url.searchParams.set('refresh', String(Date.now()));
      location.replace(url.href);
    };
    return { enter() {}, start() {}, pause() {}, leave() {}, controlsLighting: () => false,
      state: () => ({ mode: 'unavailable', reason: 'incompatible-modules' }),
      destroy() { controls.button.onclick = null; } };
  }
  const C = Cesium, { camera, scene } = viewer;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const RATE = 3600; // One simulated hour per real second; clearly labeled.
  let mode = 'idle', entered = false, preparing = false, framePending = false;
  let previousLongitude = null, ownsLight = false, lastText = '', lastReadout = 0;
  let resumeTimer = null;
  let resumePlanning = false;
  const heldPointers = new Set();
  const zoomButtons = '#gmControls button[title="Zoom in"],#gmControls button[title="Zoom out"]';
  function passiveZoom(event) {
    return isPlanner() && ((event.type === 'wheel' && event.target === scene.canvas) ||
      !!event.target.closest?.(zoomButtons));
  }
  function cancelResume() { clearTimeout(resumeTimer); resumeTimer = null; }
  // Spin again only after IDLE_MS with no input (mouse movement included) AND nothing busy in the planner
  // (isBusy: a plan, the AI, an area or layer loading, a camera flight, route playback, …). Any input or
  // busy moment restarts the wait.
  const IDLE_MS = 7000;
  let idleSince = 0;
  function scheduleResume() {
    cancelResume();
    idleSince = performance.now();
    if (mode !== 'paused' || !(ownsLight || resumePlanning) || document.hidden || reduced.matches || heldPointers.size ||
        moons.systemFrame().error) return;
    resumeTimer = setTimeout(checkResume, IDLE_MS);
  }
  function checkResume() {
    resumeTimer = null;
    if (mode !== 'paused' || !(ownsLight || resumePlanning) || document.hidden || reduced.matches || heldPointers.size ||
        viewer.trackedEntity || document.body.classList.contains('touring') || moons.systemFrame().error) return;
    let busy = true;
    try { busy = !!isBusy(); } catch { /* treat an unreadable state as busy */ }
    if (busy || !moons.systemFrame().available) {
      idleSince = performance.now(); resumeTimer = setTimeout(checkResume, 1000); return;
    }
    const left = IDLE_MS - (performance.now() - idleSince);
    if (left > 50) { resumeTimer = setTimeout(checkResume, left); return; }
    // Resume at the user's camera position, without resetting zoom or map.
    mode = 'playing'; ownsLight = true; resumePlanning = false; previousLongitude = null; moons.setSpeed(RATE);
    report(); scene.requestRender();
  }
  let lastMove = 0;
  function activity() {                                 // using the page restarts the idle wait (if one is running)
    if (resumeTimer === null) return;
    const now = performance.now();
    if (now - lastMove < 150) return;
    lastMove = now;
    idleSince = now;
  }
  const removers = [];
  function listen(node, event, fn, options) {
    node.addEventListener(event, fn, options);
    removers.push(() => node.removeEventListener(event, fn, options));
  }
  function report() {
    controls.button.textContent = mode === 'playing' ? 'Pause motion' : 'Play overview';
    controls.button.setAttribute('aria-pressed', String(mode === 'playing'));
    const frame = moons.systemFrame();
    const text = ownsLight ? (frame.error ? 'Motion unavailable · Play overview to retry' : !frame.available ? 'Loading NASA/JPL motion…' :
      `${mode === 'playing' ? '3,600× · orbiting view' : reduced.matches ? 'Motion paused' : 'Paused · resumes after 7 seconds idle, once nothing is loading'} · ${C.JulianDate.toIso8601(frame.time, 0).replace('T', ' ').replace('Z', ' UTC')}`) :
      resumePlanning && !reduced.matches ? 'Time selected · resumes after 7 seconds idle' :
      'Drag to explore · Play to return to the animated planet';
    if (text !== lastText) { controls.readout.textContent = text; lastText = text; }
  }
  function frameSystem(sun) {
    if (scene.canvas.clientWidth < 2 || scene.canvas.clientHeight < 2) return false;
    viewer.resize();
    const aspect = scene.canvas.clientWidth / scene.canvas.clientHeight;
    const fov = camera.frustum.fov;
    const halfAngle = Math.atan(Math.tan(fov / 2) / Math.max(aspect, 1 / aspect));
    // Fit both physical orbits, including on portrait displays. Mars and the
    // moons retain their physical sizes; point markers make small moons visible.
    const range = 27000000 / Math.sin(halfAngle) * 1.06;
    const longitude = Math.atan2(sun.y, sun.x) + C.Math.toRadians(45);
    // Look across the Sun's seasonal plane: a fixed northern camera can leave
    // the real Sun permanently outside the viewport during northern summer.
    const latitude = -Math.asin(sun.z / C.Cartesian3.magnitude(sun));
    camera.cancelFlight(); moons.stopTracking();
    camera.lookAtTransform(C.Matrix4.IDENTITY);
    camera.setView({ destination: C.Cartesian3.fromRadians(longitude, latitude, range - ellipsoid.maximumRadius, ellipsoid),
      orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 } });
    return true;
  }
  function tick() {
    if (!ownsLight || document.hidden) return;
    if (viewer.trackedEntity || document.body.classList.contains('touring')) { leave(); return; }
    const frame = moons.systemFrame();
    if (!frame.available) {
      previousLongitude = null; lighting.clearEphemeris();
      if (frame.error) pause();
      report(); return;
    }
    lighting.updateFromPosition(frame.sunPosition);
    const longitude = Math.atan2(frame.sunPosition.y, frame.sunPosition.x);
    if (framePending) {
      if (!frameSystem(frame.sunPosition)) return;
      framePending = false; previousLongitude = null;
    }
    if (mode === 'playing' && previousLongitude !== null) {
      const delta = Math.atan2(Math.sin(longitude - previousLongitude), Math.cos(longitude - previousLongitude)) * 0.5;
      // setView changes the camera transform, resetting Cesium's zoom gesture
      // each frame. rotate preserves the ongoing gesture and its zoom inertia.
      camera.rotate(C.Cartesian3.UNIT_Z, -delta);
    }
    previousLongitude = longitude;
    if (performance.now() - lastReadout > 200) { lastReadout = performance.now(); report(); }
  }
  function start(play = true) {
    cancelResume(); resumePlanning = false;
    preparing = true;
    try {
      selectPlanner();
      mode = play ? 'playing' : 'paused'; ownsLight = true; framePending = true;
      previousLongitude = null;
      moons.setEnabled(true);
      moons.setSpeed(play && !document.hidden ? RATE : 0);
    } finally { preparing = false; }
    tick(); report(); scene.requestRender();
  }
  function pause() {
    if (preparing) return;
    if (mode === 'paused') { scheduleResume(); return; }
    if (mode !== 'playing') return;
    mode = 'paused'; framePending = false; previousLongitude = null;
    moons.setSpeed(0); scheduleResume(); report(); scene.requestRender();
  }
  function leave() {
    if (preparing) return;
    cancelResume(); resumePlanning = false;
    if (!ownsLight) return;
    pause(); cancelResume(); framePending = false; ownsLight = false;
    restorePlanningLight(); report();
  }
  function planningChange(event) {
    if (event.target.matches('#hour,#ls') && (ownsLight || resumePlanning)) {
      pause(); ownsLight = false; resumePlanning = true;
      restorePlanningLight(); scheduleResume(); report();
    } else if (event.target.matches(changes)) leave();
  }
  controls.button.onclick = () => mode === 'playing' ? pause() : start();
  listen(scene.canvas, 'pointerdown', pause, true);
  listen(scene.canvas, 'wheel', event => { if (!passiveZoom(event)) pause(); }, { capture: true, passive: true });
  listen(document, 'pointerdown', event => {
    if (passiveZoom(event)) return;
    heldPointers.add(event.pointerId); cancelResume();
  }, true);
  for (const type of ['pointerup', 'pointercancel']) {
    listen(document, type, event => { if (heldPointers.delete(event.pointerId)) scheduleResume(); }, true);
  }
  for (const type of ['wheel', 'keydown', 'input']) listen(document, type, event => {
    if (!passiveZoom(event)) scheduleResume();
  }, { capture: true, passive: true });
  // Moving the mouse, scrolling a panel, touching or tabbing around is using the page too: it delays the spin
  // (it doesn't stop one that is already running; clicks and drags do that).
  for (const type of ['pointermove', 'scroll', 'touchstart', 'focusin']) listen(document, type, activity, { capture: true, passive: true });
  listen(window, 'blur', () => { heldPointers.clear(); cancelResume(); });
  listen(window, 'focus', scheduleResume);
  // Stop before other handlers fly, plan, change lighting, or follow a moon.
  const changes = '#region,#jumpTo,#layer,#globalLayer,#regionalLayer,#hour,#ls,#globeLighting,#showMoons,#moonSpeed';
  const buttons = '#wholeMars,#zoomRegion,#map3dView,#jezero3d,#moonApply,#moonNow,#moonSystemView,#moonPhobos,#moonDeimos,#runMission,#plan,#find,#walkerView,#playRoute';
  listen(document, 'input', planningChange, true);
  listen(document, 'change', planningChange, true);
  listen(document, 'click', event => {
    if (passiveZoom(event)) return;
    if (event.target.closest(buttons)) leave();
    else if (event.target.closest('#gmControls button,#gmRail button')) pause();
  }, true);
  listen(document, 'keydown', event => {
    if (!event.target.matches('input,select,textarea') && ['Escape', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) pause();
  }, true);
  listen(document, 'visibilitychange', () => {
    cancelResume(); heldPointers.clear();
    if (mode === 'playing') { moons.setSpeed(document.hidden ? 0 : RATE); previousLongitude = null; }
    else if (!document.hidden) scheduleResume();
  });
  listen(reduced, 'change', () => { if (reduced.matches) pause(); });
  const removeTick = scene.preUpdate.addEventListener(tick);
  report();
  return {
    enter() { if (entered) return; entered = true; if (eligible) start(!reduced.matches); },
    start, pause, leave,
    controlsLighting: () => ownsLight,
    state: () => ({ mode, entered, ownsLight, framePending, rate: RATE, resumePending: resumeTimer !== null }),
    destroy() { leave(); cancelResume(); removeTick(); removers.forEach(remove => remove()); controls.button.onclick = null; },
  };
}
