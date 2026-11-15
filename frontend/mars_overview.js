"use strict";

// A rotating presentation camera around the real Mars-fixed ephemeris. The
// camera's half-solar-turn path is deliberately not a spacecraft trajectory.
function createMarsOverview({ viewer, ellipsoid, moons, lighting, controls,
  selectPlanner, restorePlanningLight, eligible = true }) {
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
  const rotation = new C.Matrix3(), position = new C.Cartesian3();
  const direction = new C.Cartesian3(), up = new C.Cartesian3();
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
      `${mode === 'playing' ? '3,600× · orbiting view' : 'Motion paused'} · ${C.JulianDate.toIso8601(frame.time, 0).replace('T', ' ').replace('Z', ' UTC')}`) :
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
      C.Matrix3.fromRotationZ(delta, rotation);
      C.Matrix3.multiplyByVector(rotation, camera.positionWC, position);
      C.Matrix3.multiplyByVector(rotation, camera.directionWC, direction);
      C.Matrix3.multiplyByVector(rotation, camera.upWC, up);
      camera.setView({ destination: position, orientation: { direction, up } });
    }
    previousLongitude = longitude;
    if (performance.now() - lastReadout > 200) { lastReadout = performance.now(); report(); }
  }
  function start(play = true) {
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
    if (preparing || mode !== 'playing') return;
    mode = 'paused'; framePending = false; previousLongitude = null;
    moons.setSpeed(0); report(); scene.requestRender();
  }
  function leave() {
    if (preparing || !ownsLight) return;
    pause(); framePending = false; ownsLight = false;
    restorePlanningLight(); report();
  }
  controls.button.onclick = () => mode === 'playing' ? pause() : start();
  listen(scene.canvas, 'pointerdown', pause, true);
  listen(scene.canvas, 'wheel', pause, { capture: true, passive: true });
  // Stop before other handlers fly, plan, change lighting, or follow a moon.
  const changes = '#region,#jumpTo,#layer,#globalLayer,#regionalLayer,#hour,#ls,#globeLighting,#showMoons,#moonSpeed';
  const buttons = '#wholeMars,#zoomRegion,#map3dView,#jezero3d,#moonApply,#moonNow,#moonSystemView,#moonPhobos,#moonDeimos,#runMission,#plan,#find,#walkerView,#playRoute,#gmControls button,#gmRail button';
  listen(document, 'input', event => { if (event.target.matches(changes)) leave(); }, true);
  listen(document, 'change', event => { if (event.target.matches(changes)) leave(); }, true);
  listen(document, 'click', event => { if (event.target.closest(buttons)) leave(); }, true);
  listen(document, 'keydown', event => {
    if (!event.target.matches('input,select,textarea') && ['Escape', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) pause();
  }, true);
  listen(document, 'visibilitychange', () => {
    if (mode === 'playing') { moons.setSpeed(document.hidden ? 0 : RATE); previousLongitude = null; }
  });
  listen(reduced, 'change', () => { if (reduced.matches) pause(); });
  const removeTick = scene.preUpdate.addEventListener(tick);
  report();
  return {
    enter() { if (entered) return; entered = true; if (eligible) start(!reduced.matches); },
    start, pause, leave,
    controlsLighting: () => ownsLight,
    state: () => ({ mode, entered, ownsLight, framePending, rate: RATE }),
    destroy() { leave(); removeTick(); removers.forEach(remove => remove()); controls.button.onclick = null; },
  };
}
