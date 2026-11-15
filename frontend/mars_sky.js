"use strict";

const MARS_SKY_SOURCES = Object.freeze([
  { title: "NASA/Goddard SVS · Tycho/Hipparcos star atlas", url: "https://svs.gsfc.nasa.gov/3572/" },
  { title: "LMD seasonal dust scenarios · 5° climatology", url: "https://www-mars.lmd.jussieu.fr/mars/dust_scenarios/index.html" },
]);

function marsDustHazeFactor(tau, height) {
  if (!Number.isFinite(tau) || tau < 0 || !Number.isFinite(height)) return 1;
  // A local sample must not imply a planet-wide dust field. Fade this schematic
  // regional effect out between 120 and 350 km altitude.
  const x = Math.min(1, Math.max(0, (height - 120000) / 230000));
  const localWeight = 1 - x * x * (3 - 2 * x);
  // The source is IR optical depth, not visible scattering. This bounded visual
  // mapping is illustrative, not an IR-to-visible conversion or a forecast.
  return 1 + 3 * (1 - Math.exp(-2 * Math.min(tau, 3))) * localWeight;
}

function createMarsSky({ viewer, ellipsoid, api = "", getConditions = () => ({}),
  getLocation = () => null, onStatus = () => {},
  assets = "/vendor/Cesium/Assets/Textures/SkyBox/", loadStarFaces,
  Cesium: engine = globalThis.Cesium } = {}) {
  const Cesium = engine;
  if (!viewer?.scene || !Cesium) throw new Error("The Mars sky requires a Cesium viewer");
  const { scene, camera } = viewer;
  const globe = scene.globe, atmosphere = scene.skyAtmosphere;
  const previousSkyBox = scene.skyBox;
  const baselineSky = atmosphere?.atmosphereMieCoefficient && Cesium.Cartesian3.clone(atmosphere.atmosphereMieCoefficient);
  const baselineGround = globe?.atmosphereMieCoefficient && Cesium.Cartesian3.clone(globe.atmosphereMieCoefficient);
  let skyBox = null, starsEnabled = true, starsState = "loading", starsError = null;
  let dustEnabled = false, dustPhase = "off", sample = null, dustError = null;
  let generation = 0, controller = null, destroyed = false, lastFactor = NaN, lastStatus = "";
  let refreshTimer = null, refreshWaiters = [];
  const cache = new Map();

  function state() {
    const dustMessage = {
      off: "", "lighting-off": "Turn on Sunlight and atmosphere to show seasonal dust haze.",
      "zoom-in": "Zoom closer to a region to show seasonal dust haze.",
      "no-location": "Aim at the surface to sample seasonal dust.",
      loading: "Loading seasonal dust opacity…",
      unavailable: "Seasonal dust is unavailable here. No haze is added.",
      ready: sample ? `Seasonal dust τ: ${sample.tau.toFixed(2)} · ${sample.gridStepDeg}° climatology. Haze is illustrative, not observed clouds.` : "",
    }[dustPhase] || "";
    return { starsEnabled, starsState, starsError, dustEnabled, dustPhase,
      dustTau: sample?.tau ?? null, location: sample ? { ...sample.location } : null,
      ls: sample?.ls ?? null, gridStepDeg: sample?.gridStepDeg ?? null,
      dustError, message: [starsState === "unavailable" ? "Star background unavailable." : "", dustMessage].filter(Boolean).join(" "),
      representation: "Schematic seasonal haze; not observed storm clouds or calibrated visible opacity.",
      starsNote: "NASA star atlas with illustrative orientation; not a date-specific Mars star chart." };
  }
  function report() {
    if (destroyed) return;
    const current = state(), encoded = JSON.stringify(current);
    if (encoded !== lastStatus) { lastStatus = encoded; onStatus(current.message, current); }
  }
  function applyHaze() {
    const height = camera.positionCartographic?.height;
    const factor = dustEnabled && sample && globe.enableLighting && atmosphere?.show
      ? marsDustHazeFactor(sample.tau, height) : 1;
    if (factor === lastFactor) return;
    lastFactor = factor;
    if (baselineSky) Cesium.Cartesian3.multiplyByScalar(baselineSky, factor, atmosphere.atmosphereMieCoefficient);
    if (baselineGround) Cesium.Cartesian3.multiplyByScalar(baselineGround, factor, globe.atmosphereMieCoefficient);
    // Do not change fog density, terrain screen-space error, map colors, data,
    // cloud positions, or the user's sunlight/atmosphere toggle.
  }
  function resetSample(phase, error = null) {
    sample = null; dustPhase = phase; dustError = error;
    applyHaze(); report(); scene.requestRender();
  }
  async function requestSample(body, signal) {
    if (typeof api === "function") return api("/api/layer/dust_opacity/sample", body, signal);
    const response = await fetch(api + "/api/layer/dust_opacity/sample", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
    });
    if (!response.ok) throw new Error(`Dust data returned ${response.status}`);
    return response.json();
  }
  async function executeRefresh() {
    const request = ++generation;
    controller?.abort(); controller = null;
    if (destroyed) return state();
    if (!dustEnabled) { resetSample("off"); return state(); }
    if (!baselineSky || !baselineGround) { resetSample("unavailable", "Atmospheric scattering is unavailable"); return state(); }
    if (!globe.enableLighting || !atmosphere.show) { resetSample("lighting-off"); return state(); }
    if (!Number.isFinite(camera.positionCartographic?.height) || camera.positionCartographic.height >= 350000) {
      resetSample("zoom-in"); return state();
    }
    let location, conditions;
    try { location = getLocation(); conditions = getConditions(); }
    catch (_) { resetSample("unavailable", "No selected surface location"); return state(); }
    if (!location || !Number.isFinite(location.lat) || !Number.isFinite(location.lon) || Math.abs(location.lat) > 90) {
      resetSample("no-location"); return state();
    }
    const lon = ((location.lon + 180) % 360 + 360) % 360 - 180;
    const ls = Number(conditions?.ls), hour = Number(conditions?.local_hour ?? 12);
    if (!Number.isFinite(ls) || !Number.isFinite(hour)) { resetSample("unavailable", "A valid season is required"); return state(); }
    const season = ((ls % 360) + 360) % 360;
    // Match app.global_cell's north-first nearest-cell lookup exactly, including
    // which side owns an exact latitude boundary. The sample endpoint does not
    // interpolate spatially within a dust cell.
    const key = `${Math.min(35, Math.max(0, Math.floor((90 - location.lat) / 5)))}:${Math.floor((lon + 180) / 5)}:${season.toFixed(2)}`;
    const found = cache.get(key);
    if (found) {
      sample = { ...found, location: { lat: location.lat, lon } }; dustPhase = "ready"; dustError = null;
      applyHaze(); report(); scene.requestRender(); return state();
    }
    resetSample("loading");
    const abort = new AbortController(); controller = abort;
    const timeout = setTimeout(() => abort.abort(), 15000);
    try {
      const data = await requestSample({ lat: location.lat, lon, ls: season, local_hour: ((hour % 24) + 24) % 24 }, abort.signal);
      if (destroyed || request !== generation || !dustEnabled) return state();
      if (!Number.isFinite(data.value) || data.value < 0) {
        resetSample("unavailable", "No seasonal dust opacity for this location"); return state();
      }
      sample = { tau: data.value, ls: season, location: { lat: location.lat, lon },
        gridStepDeg: Number.isFinite(data.grid_step_deg) ? data.grid_step_deg : 5 };
      cache.set(key, sample);
      while (cache.size > 32) cache.delete(cache.keys().next().value);
      dustPhase = "ready"; dustError = null;
      applyHaze(); report(); scene.requestRender();
    } catch (error) {
      if (!destroyed && request === generation) resetSample("unavailable",
        abort.signal.aborted ? "Dust data timed out" : error.message || String(error));
    } finally {
      clearTimeout(timeout);
      if (controller === abort) controller = null;
    }
    return state();
  }
  function refresh({ immediate = false } = {}) {
    if (destroyed) return Promise.resolve(state());
    clearTimeout(refreshTimer); refreshTimer = null;
    ++generation; controller?.abort(); controller = null;
    if (!dustEnabled || immediate) {
      const waiting = refreshWaiters; refreshWaiters = [];
      const result = executeRefresh();
      result.then(value => waiting.forEach(resolve => resolve(value)));
      return result;
    }
    resetSample("loading");
    return new Promise(resolve => {
      refreshWaiters.push(resolve);
      refreshTimer = setTimeout(() => {
        refreshTimer = null;
        const waiting = refreshWaiters; refreshWaiters = [];
        executeRefresh().then(value => waiting.forEach(resolve => resolve(value)));
      }, 180);
    });
  }

  const removePreRender = scene.preRender.addEventListener(applyHaze);
  const removeMoveEnd = camera.moveEnd.addEventListener(() => { if (dustEnabled) refresh(); });
  const faces = { positiveX: "px", negativeX: "mx", positiveY: "py", negativeY: "my", positiveZ: "pz", negativeZ: "mz" };
  const loadFaces = loadStarFaces || (() => Promise.all(Object.entries(faces).map(([side, suffix]) => new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => image.naturalWidth === image.naturalHeight && image.naturalWidth > 0
      ? resolve([side, image]) : reject(new Error("Invalid star-atlas face"));
    image.onerror = () => reject(new Error("The bundled NASA star atlas could not load"));
    image.src = assets + `tycho2t3_80_${suffix}.jpg`;
  }))).then(Object.fromEntries));
  const ready = Promise.resolve().then(loadFaces).then(sources => {
    if (destroyed) return false;
    skyBox = new Cesium.SkyBox({ sources, show: starsEnabled });
    scene.skyBox = skyBox;
    // Native sky-box rendering stays behind the opaque globe. Cesium's existing
    // directional atmosphere scatters over it and fades stars in the daylight;
    // no foreground screen overlay can put stars on the terrain.
    starsState = "ready"; report(); scene.requestRender(); return true;
  }).catch(error => {
    if (!destroyed) { starsState = "unavailable"; starsError = error.message || String(error); report(); }
    return false;
  });
  report();
  return {
    ready, sources: MARS_SKY_SOURCES,
    getState: state,
    setStarsEnabled(enabled) {
      if (destroyed) return;
      starsEnabled = !!enabled;
      if (skyBox) skyBox.show = starsEnabled;
      report(); scene.requestRender();
    },
    setDustEnabled(enabled) { dustEnabled = !!enabled; return refresh({ immediate: true }); },
    refresh,
    destroy() {
      if (destroyed) return;
      destroyed = true; ++generation; controller?.abort(); controller = null;
      clearTimeout(refreshTimer); refreshTimer = null;
      refreshWaiters.forEach(resolve => resolve(state())); refreshWaiters = [];
      removePreRender(); removeMoveEnd();
      dustEnabled = false; sample = null; lastFactor = NaN; applyHaze();
      if (scene.skyBox === skyBox) scene.skyBox = previousSkyBox;
      if (skyBox && !skyBox.isDestroyed()) skyBox.destroy();
      cache.clear(); scene.requestRender();
    },
  };
}

if (typeof module !== "undefined" && module.exports) module.exports = { createMarsSky, marsDustHazeFactor, MARS_SKY_SOURCES };
