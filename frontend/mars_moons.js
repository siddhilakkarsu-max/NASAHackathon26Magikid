"use strict";

function createMarsMoons({ viewer, ellipsoid, api = '', controls, now = () => Cesium.JulianDate.now() }) {
  const C = Cesium, { scene, camera } = viewer;
  const dataSource = new C.CustomDataSource('NASA/JPL Mars moons');
  viewer.dataSources.add(dataSource);
  let enabled = true, destroyed = false, speed = 1, generation = 0, controller = null;
  let anchor = now(), anchorWall = performance.now(), current = C.JulianDate.clone(anchor);
  let pendingDay = null, failedDay = null, lastReadout = 0, currentTable = null, lastError = '';
  const cache = new Map(), records = new Map();
  const dateOf = time => C.JulianDate.toIso8601(time).slice(0, 10);
  const allowed = day => day >= '1995-01-02' && day <= '2049-12-30';
  const modelAdjustments = {
    phobos: C.Quaternion.fromAxisAngle(C.Cartesian3.UNIT_Z, Math.PI / 2),
    deimos: C.Quaternion.fromAxisAngle(C.Cartesian3.UNIT_X, -Math.PI / 2),
  };
  // Native NASA meshes use kilometre-sized coordinates. Cesium scenes use metres.
  // The longest/shortest axes are approximately aligned, not feature-calibrated.
  for (const id of ['phobos', 'deimos']) {
    const position = new C.Cartesian3(), orientation = new C.Quaternion();
    const record = { id, position, orientation, valid: false, radius: id === 'phobos' ? 15000 : 8500 };
    const positionProperty = new C.CallbackPositionProperty(() => record.valid ? position : undefined, false);
    const visible = () => enabled && record.valid && marsPointVisible(camera.positionWC, position, ellipsoid.radii);
    record.entity = dataSource.entities.add({ id: 'mars-moon-' + id,
      name: id[0].toUpperCase() + id.slice(1), position: positionProperty,
      orientation: new C.CallbackProperty(() => orientation, false),
      // Shrinking the blocker by the moon radius retains partially occulted models.
      model: { uri: api + '/assets/moons/' + id + '.glb', scale: 1000, minimumPixelSize: 0,
        show: new C.CallbackProperty(() => enabled && record.valid &&
          marsPointVisible(camera.positionWC, position, ellipsoid.radii, record.radius), false),
        shadows: C.ShadowMode.DISABLED, runAnimations: false, enableVerticalExaggeration: false,
        // Preserve NASA's texture colors, independent of the planner's arbitrary
        // sunlight scenario. This is an unlit visualization, not a phase renderer.
        customShader: new C.CustomShader({ lightingModel: C.LightingModel.UNLIT }) },
      point: { pixelSize: 5, color: C.Color.fromCssColorString('#eadbca'),
        outlineColor: C.Color.BLACK, outlineWidth: 1, disableDepthTestDistance: 0,
        show: new C.CallbackProperty(() => visible() && C.Cartesian3.distance(camera.positionWC, position) > record.radius * 20, false) },
      label: { text: id[0].toUpperCase() + id.slice(1), font: '12px sans-serif',
        fillColor: C.Color.WHITE, outlineColor: C.Color.BLACK, outlineWidth: 3,
        style: C.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new C.Cartesian2(0, -17),
        disableDepthTestDistance: 0, show: new C.CallbackProperty(visible, false) },
      viewFrom: new C.Cartesian3(record.radius * 5, -record.radius * 3, record.radius * 2),
    });
    records.set(id, record);
  }

  function stopTracking() {
    if ([...records.values()].some(r => viewer.trackedEntity === r.entity)) viewer.trackedEntity = undefined;
  }
  function report() {
    if (!controls) return;
    const iso = C.JulianDate.toIso8601(current, 0);
    if (document.activeElement !== controls.date) controls.date.value = iso.slice(0, 19);
    controls.readout.textContent = iso.replace('T', ' ').replace('Z', ' UTC') +
      (speed === 0 ? ' · paused' : ` · ${speed}× speed`);
    controls.status.textContent = !enabled ? 'Moons hidden.' : lastError || (pendingDay
      ? 'Loading NASA/JPL moon positions… First use downloads about 65 MB of orbital data.'
      : 'Real sizes and distances. Small dots locate moons when they are too small to see.');
    for (const [id, button] of [['phobos', controls.phobos], ['deimos', controls.deimos]]) {
      button.disabled = !enabled || !records.get(id).valid;
    }
  }
  function prepare(data) {
    if (data.frame !== 'IAU_MARS' || !Array.isArray(data.times) || data.times.length < 2 || data.moons?.length !== 2) {
      throw new Error('Invalid moon ephemeris response');
    }
    const times = data.times.map(t => C.JulianDate.fromIso8601(t));
    for (let i = 1; i < times.length; i++) if (C.JulianDate.compare(times[i], times[i - 1]) <= 0) throw new Error('Unordered moon samples');
    const table = { start: times[0], end: times.at(-1), date: data.date, moons: new Map() };
    for (const moon of data.moons) {
      if (!records.has(moon.id) || table.moons.has(moon.id) || moon.samples?.length !== times.length) throw new Error('Invalid moon samples');
      const positions = new C.SampledPositionProperty(C.ReferenceFrame.FIXED, 1);
      positions.setInterpolationOptions({ interpolationDegree: 3, interpolationAlgorithm: C.HermitePolynomialApproximation });
      const orientations = new C.SampledProperty(C.Quaternion);
      for (let i = 0; i < times.length; i++) {
        const row = moon.samples[i];
        if (row.length !== 10 || !row.every(Number.isFinite)) throw new Error('Invalid moon state vector');
        positions.addSample(times[i], C.Cartesian3.fromArray(row), [C.Cartesian3.fromArray(row, 3)]);
        const q = new C.Quaternion(row[6], row[7], row[8], row[9]);
        C.Quaternion.multiply(q, modelAdjustments[moon.id], q);
        orientations.addSample(times[i], q);
      }
      table.moons.set(moon.id, { positions, orientations });
    }
    return table;
  }
  async function load(day, force = false) {
    if (destroyed || !enabled || (!force && (pendingDay === day || failedDay === day))) return;
    if (cache.has(day)) { currentTable = cache.get(day); return; }
    const request = ++generation;
    controller?.abort(); controller = new AbortController();
    pendingDay = day; failedDay = null; lastError = ''; report();
    try {
      if (!allowed(day)) throw new Error('Choose a UTC date from 1995-01-02 through 2049-12-30.');
      const response = await fetch(api + '/api/moons/ephemeris?date=' + encodeURIComponent(day), { signal: controller.signal });
      if (!response.ok) throw new Error('NASA/JPL moon positions are unavailable. Use Retry; no estimated orbit is shown.');
      const table = prepare(await response.json());
      if (destroyed || request !== generation || !enabled) return;
      cache.set(day, table);
      while (cache.size > 3) cache.delete(cache.keys().next().value);
      if (day === dateOf(current)) currentTable = table;
    } catch (error) {
      if (request !== generation || destroyed || error.name === 'AbortError') return;
      failedDay = day; lastError = error.message;
    } finally {
      if (request === generation && !destroyed) { pendingDay = null; update(); report(); scene.requestRender(); }
    }
  }
  function update() {
    if (destroyed) return;
    C.JulianDate.addSeconds(anchor, (performance.now() - anchorWall) / 1000 * speed, current);
    const day = dateOf(current);
    if (enabled && (!currentTable || currentTable.date !== day)) void load(day);
    const available = enabled && currentTable && C.JulianDate.compare(current, currentTable.start) >= 0 &&
      C.JulianDate.compare(current, currentTable.end) <= 0;
    for (const record of records.values()) {
      const sample = available && currentTable.moons.get(record.id);
      record.valid = !!(sample && sample.positions.getValue(current, record.position) &&
        sample.orientations.getValue(current, record.orientation));
    }
    if (!available) stopTracking();
    if (performance.now() - lastReadout > 1000) { lastReadout = performance.now(); report(); }
  }
  function setTime(iso) {
    const time = C.JulianDate.fromIso8601(iso);
    if (!allowed(dateOf(time))) throw new Error('Choose a date between 1995-01-02 and 2049-12-30.');
    anchor = time; C.JulianDate.clone(time, current); anchorWall = performance.now();
    failedDay = null; lastError = '';
    // Invalidate a late request even when the new date is already cached.
    generation++; controller?.abort(); pendingDay = null;
    currentTable = cache.get(dateOf(time)) || null;
    update(); report(); scene.requestRender();
  }
  function setSpeed(value) {
    if (![0, 1, 60, 600].includes(value)) throw new Error('Unsupported moon playback speed');
    update(); anchor = C.JulianDate.clone(current); anchorWall = performance.now(); speed = value;
    report(); scene.requestRender();
  }
  function setEnabled(value) {
    enabled = !!value; dataSource.show = enabled;
    if (!enabled) { generation++; controller?.abort(); pendingDay = null; stopTracking(); }
    else { failedDay = null; lastError = ''; }
    update(); report(); scene.requestRender();
  }
  function systemView() {
    stopTracking();
    camera.flyToBoundingSphere(new C.BoundingSphere(C.Cartesian3.ZERO, 26000000), {
      duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 1.5,
      offset: new C.HeadingPitchRange(0, -Math.PI / 3, 80000000),
    });
  }
  function focus(id) {
    const record = records.get(id);
    if (enabled && record?.valid) { camera.cancelFlight(); viewer.trackedEntity = record.entity; }
  }
  const removeUpdate = scene.preUpdate.addEventListener(update);
  if (controls) {
    controls.enabled.onchange = () => setEnabled(controls.enabled.checked);
    controls.speed.onchange = () => setSpeed(+controls.speed.value);
    controls.system.onclick = systemView;
    controls.phobos.onclick = () => focus('phobos'); controls.deimos.onclick = () => focus('deimos');
    controls.apply.onclick = () => {
      try { if (!controls.date.reportValidity()) return; setTime(controls.date.value + 'Z'); }
      catch (error) { lastError = error.message; report(); }
    };
    controls.now.onclick = () => { setTime(C.JulianDate.toIso8601(now())); setSpeed(1); controls.speed.value = '1'; };
    controls.retry.onclick = () => { failedDay = null; void load(dateOf(current), true); };
  }
  update(); report();
  return { setTime, setSpeed, setEnabled, systemView, focus, stopTracking,
    state: () => ({ enabled, speed, utc: C.JulianDate.toIso8601(current), pendingDay, error: lastError,
      moons: [...records.values()].map(r => ({ id: r.id, valid: r.valid, position: C.Cartesian3.clone(r.position),
        markerVisible: r.entity.label.show.getValue(viewer.clock.currentTime), scale: 1000 })) }),
    destroy() {
      destroyed = true; generation++; controller?.abort(); removeUpdate(); stopTracking();
      for (const r of records.values()) r.entity.model.customShader.getValue()?.destroy();
      viewer.dataSources.remove(dataSource, true); cache.clear();
    },
  };
}
