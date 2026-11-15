"use strict";

// A labeled display transition, not a predicted trajectory between two dates.
// Interpolate directions along an arc and radii separately, never through Mars.
function marsMoonTransitionPosition(C, from, to, t, result) {
  if (t <= 0) return C.Cartesian3.clone(from, result);
  if (t >= 1) return C.Cartesian3.clone(to, result);
  const a = C.Cartesian3.normalize(from, new C.Cartesian3());
  const b = C.Cartesian3.normalize(to, new C.Cartesian3());
  const dot = C.Math.clamp(C.Cartesian3.dot(a, b), -1, 1);
  const axis = C.Cartesian3.cross(a, b, new C.Cartesian3());
  if (C.Cartesian3.magnitudeSquared(axis) < 1e-16) {
    if (dot > 0) return C.Cartesian3.lerp(from, to, t, result);
    C.Cartesian3.cross(a, C.Cartesian3.mostOrthogonalAxis(a, new C.Cartesian3()), axis);
  }
  C.Cartesian3.normalize(axis, axis);
  const rotation = C.Matrix3.fromQuaternion(C.Quaternion.fromAxisAngle(axis, Math.acos(dot) * t));
  C.Matrix3.multiplyByVector(rotation, a, result);
  return C.Cartesian3.multiplyByScalar(result,
    C.Math.lerp(C.Cartesian3.magnitude(from), C.Cartesian3.magnitude(to), t), result);
}

function createMarsMoons({ viewer, ellipsoid, api = '', controls, now = () => Cesium.JulianDate.now() }) {
  const C = Cesium, { scene, camera } = viewer;
  const dataSource = new C.CustomDataSource('NASA/JPL Mars moons');
  viewer.dataSources.add(dataSource);
  let enabled = true, destroyed = false, speed = 1, generation = 0, controller = null;
  let anchor = now(), anchorWall = performance.now(), current = C.JulianDate.clone(anchor);
  let pendingDay = null, failedDay = null, lastReadout = 0, currentTable = null, lastError = '';
  let prefetchController = null, prefetchedDay = null;
  let planningReference = null, planningKey = '', planningTimer = null, planningController = null;
  let planningGeneration = 0, planningPending = false, planningError = '', planningResult = null, lastPlan = null;
  let transition = null;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const cache = new Map(), records = new Map();
  const system = { time: current, speed, available: false, error: '', sunPosition: new C.Cartesian3() };
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
    const record = { id, position, orientation, targetPosition: new C.Cartesian3(), targetOrientation: new C.Quaternion(),
      valid: false, radius: id === 'phobos' ? 15000 : 8500 };
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
    controls.readout.textContent = (transition && !planningPending ? 'Target: ' : '') + iso.replace('T', ' ').replace('Z', ' UTC') +
      (speed === 0 ? ' · paused' : ` · ${speed}× speed`);
    if (controls.syncNote) controls.syncNote.textContent = planningResult
      ? `Linked to region center ${planningResult.longitude.toFixed(2)}°E · resolved Ls ${planningResult.actual_ls.toFixed(3)}° · reference date ${planningResult.reference_date}.`
      : 'Time/season edits choose the nearest season to the displayed moon date, then the nearest matching local solar time at the region center. The resolved UTC and season are shown; this is a dated scenario.';
    controls.status.textContent = !enabled ? 'Moons hidden.' : planningPending ? 'Matching season and local time with NASA/JPL… Holding the previous view.' : planningError || lastError || (pendingDay
      ? 'Loading NASA/JPL moon positions… First use downloads about 65 MB of orbital data.'
      : transition ? 'Moving to the selected date · visual transition, not the actual orbital path between dates.'
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
    if (data.sun) {
      if (data.sun.samples?.length !== times.length) throw new Error('Invalid Sun samples');
      table.sun = new C.SampledPositionProperty(C.ReferenceFrame.FIXED, 1);
      table.sun.setInterpolationOptions({ interpolationDegree: 3, interpolationAlgorithm: C.HermitePolynomialApproximation });
      data.sun.samples.forEach((row, i) => {
        if (row.length !== 6 || !row.every(Number.isFinite)) throw new Error('Invalid Sun state vector');
        table.sun.addSample(times[i], C.Cartesian3.fromArray(row), [C.Cartesian3.fromArray(row, 3)]);
      });
    }
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
  async function prefetch(day) {
    if (!allowed(day) || cache.has(day) || prefetchedDay === day) return;
    prefetchedDay = day;
    prefetchController?.abort();
    const abort = prefetchController = new AbortController(), request = generation;
    try {
      const response = await fetch(api + '/api/moons/ephemeris?date=' + encodeURIComponent(day), { signal: abort.signal });
      if (!response.ok) return; // The normal loader supplies the visible retry/error state.
      const table = prepare(await response.json());
      if (destroyed || !enabled || request !== generation || abort.signal.aborted) return;
      cache.set(day, table);
      while (cache.size > 3) cache.delete(cache.keys().next().value);
    } catch (error) { /* No substituted orbit; normal loading handles an unavailable day. */ }
  }
  function update() {
    if (destroyed) return;
    C.JulianDate.addSeconds(anchor, (performance.now() - anchorWall) / 1000 * speed, current);
    const day = dateOf(current);
    if (enabled && (!currentTable || currentTable.date !== day)) void load(day);
    const available = enabled && !planningPending && !planningError && currentTable && C.JulianDate.compare(current, currentTable.start) >= 0 &&
      C.JulianDate.compare(current, currentTable.end) <= 0;
    const hadTransition = !!transition;
    if (planningError || lastError || !enabled) transition = null;
    if (transition && available && transition.start === null) transition.start = performance.now();
    const progress = transition && available ? (reduced.matches ? 1 : Math.min(1, (performance.now() - transition.start) / 1200)) : 0;
    const eased = progress * progress * (3 - 2 * progress);
    system.available = !!(available && currentTable.sun?.getValue(current, system.sunPosition) && (!transition || progress === 1));
    system.speed = speed;
    system.error = planningError || lastError;
    if (available && speed >= 600 && C.JulianDate.secondsDifference(currentTable.end, current) < speed * 5) {
      void prefetch(dateOf(C.JulianDate.addSeconds(currentTable.end, 1, new C.JulianDate())));
    }
    for (const record of records.values()) {
      const sample = available && currentTable.moons.get(record.id);
      const source = transition?.from.get(record.id);
      const targetValid = !!(sample && sample.positions.getValue(current, record.targetPosition) &&
        sample.orientations.getValue(current, record.targetOrientation));
      record.valid = targetValid || !!(source && enabled);
      if (targetValid && source) {
        marsMoonTransitionPosition(C, source.position, record.targetPosition, eased, record.position);
        C.Quaternion.slerp(source.orientation, record.targetOrientation, eased, record.orientation);
      } else if (targetValid) {
        C.Cartesian3.clone(record.targetPosition, record.position);
        C.Quaternion.clone(record.targetOrientation, record.orientation);
      } else if (source) {
        C.Cartesian3.clone(source.position, record.position);
        C.Quaternion.clone(source.orientation, record.orientation);
      }
    }
    if (transition && progress === 1) transition = null;
    if (hadTransition && !transition) report();
    if (!available) stopTracking();
    if (performance.now() - lastReadout > 1000) { lastReadout = performance.now(); report(); }
  }
  function cancelPlanning() {
    planningGeneration++; clearTimeout(planningTimer); planningController?.abort();
    planningPending = false; planningError = ''; planningResult = null; planningReference = null; planningKey = ''; lastPlan = null;
    transition = null;
  }
  function syncPlanning(values) {
    const key = JSON.stringify(values);
    if (key === planningKey) return;
    planningKey = key; lastPlan = values;
    planningReference ||= dateOf(current);
    const request = ++planningGeneration;
    clearTimeout(planningTimer); planningController?.abort();
    setSpeed(0);
    const from = new Map([...records.values()].filter(r => r.valid).map(r => [r.id,
      { position: C.Cartesian3.clone(r.position), orientation: C.Quaternion.clone(r.orientation) }]));
    transition = from.size && !reduced.matches ? {from, start:null} : null;
    planningPending = true; planningError = ''; planningResult = null; update(); report();
    // Debounce slider scrubbing, cancel superseded work, and never display an
    // old date's moon positions as though they match a new planning scenario.
    planningTimer = setTimeout(async () => {
      const abort = planningController = new AbortController();
      try {
        const params = new URLSearchParams({ ...values, reference_date: planningReference });
        const response = await fetch(api + '/api/moons/planning-time?' + params, { signal: abort.signal });
        if (!response.ok) throw new Error('Moon time could not match these settings. Retry moon data or choose another UTC reference date.');
        const result = await response.json();
        if (destroyed || request !== planningGeneration) return;
        if (!Number.isFinite(result.actual_ls) || !Number.isFinite(result.longitude)) throw new Error('Invalid NASA/JPL time response.');
        setTime(result.utc, true); planningResult = result; planningPending = false;
      } catch (error) {
        if (destroyed || request !== planningGeneration || error.name === 'AbortError') return;
        planningPending = false; planningError = error.message;
      }
      if (!destroyed && request === planningGeneration) { update(); report(); scene.requestRender(); }
    }, 250);
  }
  function setTime(iso, fromPlanning = false) {
    const time = C.JulianDate.fromIso8601(iso);
    if (!allowed(dateOf(time))) throw new Error('Choose a date between 1995-01-02 and 2049-12-30.');
    if (!fromPlanning) cancelPlanning();
    anchor = time; C.JulianDate.clone(time, current); anchorWall = performance.now();
    failedDay = null; lastError = '';
    // Invalidate a late request even when the new date is already cached.
    generation++; controller?.abort(); prefetchController?.abort(); prefetchedDay = null; pendingDay = null;
    currentTable = cache.get(dateOf(time)) || null;
    update(); report(); scene.requestRender();
  }
  function setSpeed(value) {
    if (![0, 1, 60, 600, 3600].includes(value)) throw new Error('Unsupported moon playback speed');
    update(); anchor = C.JulianDate.clone(current); anchorWall = performance.now(); speed = value;
    system.speed = speed;
    if (controls) controls.speed.value = String(speed);
    report(); scene.requestRender();
  }
  function setEnabled(value) {
    enabled = !!value; dataSource.show = enabled;
    if (!enabled) { generation++; controller?.abort(); prefetchController?.abort(); prefetchedDay = null; pendingDay = null; stopTracking(); }
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
    controls.retry.onclick = () => {
      if (planningError && lastPlan) { planningKey = ''; syncPlanning(lastPlan); }
      else { failedDay = null; void load(dateOf(current), true); }
    };
  }
  update(); report();
  return { setTime, setSpeed, setEnabled, systemView, focus, stopTracking, syncPlanning,
    planningLinked: () => planningReference !== null,
    // Read-only live frame, updated before the overview's scene listener.
    systemFrame: () => system,
    state: () => ({ enabled, speed, utc: C.JulianDate.toIso8601(current), pendingDay, error: planningError || lastError,
      planningPending, planningResult, transitioning: !!transition,
      moons: [...records.values()].map(r => ({ id: r.id, valid: r.valid, position: C.Cartesian3.clone(r.position),
        markerVisible: r.entity.label.show.getValue(viewer.clock.currentTime), scale: 1000 })) }),
    destroy() {
      destroyed = true; cancelPlanning(); generation++; controller?.abort(); prefetchController?.abort(); removeUpdate(); stopTracking();
      for (const r of records.values()) r.entity.model.customShader.getValue()?.destroy();
      viewer.dataSources.remove(dataSource, true); cache.clear();
    },
  };
}
