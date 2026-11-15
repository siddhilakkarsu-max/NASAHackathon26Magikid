const routeModelKeys = new Set([
  "astronaut", "two_wheel", "four_wheel", "buggy", "pressurized_rover", "unpressurized_rover",
  "small_rover", "perseverance", "sojourner", "mer", "zhurong", "rosalind_franklin",
]);

function routePlaybackPath(points, ellipsoid) {
  if (!Array.isArray(points) || points.length < 2) return null;
  const positions = [];
  const distances = [];
  let length = 0;
  for (const point of points) {
    if (!Number.isFinite(point?.lat) || !Number.isFinite(point?.lon) || Math.abs(point.lat) > 90) return null;
    const position = Cesium.Cartesian3.fromDegrees(point.lon, point.lat, 0, ellipsoid);
    const previous = positions.at(-1);
    const meters = previous ? Cesium.Cartesian3.distance(previous, position) : 0;
    if (previous && meters < 0.01) continue;
    length += meters;
    positions.push(position);
    distances.push(length);
  }
  if (positions.length < 2) return null;
  return { positions, distances, length, bounds: Cesium.BoundingSphere.fromPoints(positions) };
}

function routePlaybackPoint(path, distance, ellipsoid, result) {
  const { positions, distances, length } = path;
  const traveled = Cesium.Math.clamp(distance, 0, length);
  let lo = 0, hi = distances.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (distances[mid] <= traveled) lo = mid;
    else hi = mid;
  }
  const t = (traveled - distances[lo]) / (distances[hi] - distances[lo]);
  Cesium.Cartesian3.lerp(positions[lo], positions[hi], t, result);
  return ellipsoid.scaleToGeodeticSurface(result, result);
}

// Walker's view: the camera stands at an astronaut's eye height on the 3D terrain at five stops along the route
// (start, quarter, half, three quarters, target), looking the way the route goes.
const WALKER_STOPS = [0, 0.25, 0.5, 0.75, 1];
const WALKER_STOP_NAMES = ["Start", "A quarter of the way", "Halfway", "Three quarters of the way", "Target"];
const WALKER_EYE_M = 1.7;
const WALKER_SKY = "#c9a27f";                    // butterscotch daytime sky, seen above the horizon

function createRoutePlayback({ viewer, ellipsoid, controls }) {
  const { scene, camera } = viewer;
  const { panel, button, status, walk, walkNav, walkPrev, walkNext, walkExit, walkStatus,
          beforeWalk, afterWalk } = controls;
  let current = null;
  let walker = null;                              // { route, stop, terrain, background }
  let frame = 0;
  const at = new Cesium.Cartesian3(), behind = new Cesium.Cartesian3(), ahead = new Cesium.Cartesian3();
  const up = new Cesium.Cartesian3(), forward = new Cesium.Cartesian3(), left = new Cesium.Cartesian3();
  const radial = new Cesium.Cartesian3();
  const axes = new Cesium.Matrix3(), matrix = new Cesium.Matrix4();

  function pose(route) {
    const distance = route.elapsed / route.duration * route.path.length;
    const look = Math.min(20, route.path.length / 4);
    routePlaybackPoint(route.path, distance, ellipsoid, at);
    routePlaybackPoint(route.path, distance - look, ellipsoid, behind);
    routePlaybackPoint(route.path, distance + look, ellipsoid, ahead);
    ellipsoid.geodeticSurfaceNormal(at, up);
    Cesium.Cartesian3.subtract(ahead, behind, forward);
    // A U-turn can make the two look-ahead points coincide.
    if (Cesium.Cartesian3.magnitudeSquared(forward) < 1e-8) {
      Cesium.Cartesian3.subtract(ahead, at, forward);
      if (Cesium.Cartesian3.magnitudeSquared(forward) < 1e-8) Cesium.Cartesian3.subtract(at, behind, forward);
    }
    Cesium.Cartesian3.multiplyByScalar(up, Cesium.Cartesian3.dot(up, forward), radial);
    Cesium.Cartesian3.normalize(Cesium.Cartesian3.subtract(forward, radial, forward), forward);
    Cesium.Cartesian3.cross(up, forward, left);
    Cesium.Matrix3.setColumn(axes, 0, forward, axes);
    Cesium.Matrix3.setColumn(axes, 1, left, axes);
    Cesium.Matrix3.setColumn(axes, 2, up, axes);
    Cesium.Matrix4.fromRotationTranslation(axes, at, matrix);
    route.model.modelMatrix = matrix;
  }

  function updateControls() {
    panel.hidden = !current;
    if (walk) {
      walk.hidden = !current || !!walker;
      walk.disabled = !current?.path;
      walkNav.hidden = !walker;
      if (walker) {
        walkPrev.disabled = walker.stop === 0;
        walkNext.disabled = walker.stop === WALKER_STOPS.length - 1;
      }
      if (!walker) walkStatus.textContent = "";
    }
    if (!current) return;
    button.disabled = !current.ready && !current.failed;
    button.textContent = current.failed ? "Retry animation" : !current.ready ? "Loading animation…"
      : current.playing ? "Pause" : current.elapsed === current.duration ? "Replay route"
      : current.elapsed ? "Resume" : "Play route";
    status.textContent = current.failed ? "The 3D model could not load." : `${current.label} · Time compressed`;
  }

  function stop(route) {
    cancelAnimationFrame(frame);
    route.playing = false;
    route.lastFrame = null;
  }

  function clear(kind) {
    if (!current || (kind && kind !== current.kind)) return;
    exitWalker(false);
    stop(current);
    if (current.model) scene.primitives.remove(current.model);
    current = null;
    updateControls();
    scene.requestRender();
  }

  function tick(time) {
    const route = current;
    if (!route?.playing) return;
    if (route.lastFrame !== null) {
      route.elapsed = Math.min(route.duration, route.elapsed + Math.min(100, time - route.lastFrame) / 1000);
    }
    route.lastFrame = time;
    pose(route);
    scene.requestRender();
    if (route.elapsed >= route.duration) {
      stop(route);
      updateControls();
    } else {
      frame = requestAnimationFrame(tick);
    }
  }

  async function load(route) {
    route.failed = false;
    updateControls();
    try {
      const model = await Cesium.Model.fromGltfAsync({
        url: `/route_models/${route.modelKey}.glb`,
        upAxis: Cesium.Axis.Y, forwardAxis: Cesium.Axis.Z, scene,
        allowPicking: false, minimumPixelSize: 76, maximumScale: 1600,
        distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 120000),
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        enableVerticalExaggeration: false,
      });
      if (current !== route) {
        model.destroy();
        return;
      }
      route.model = model;
      pose(route);
      model.readyEvent.addEventListener(() => {
        route.ready = true;
        model.activeAnimations.animateWhilePaused = true;
        model.activeAnimations.addAll({
          loop: Cesium.ModelAnimationLoop.REPEAT,
          animationTime: duration => route.elapsed / duration,
        });
        if (current === route) updateControls();
      });
      model.errorEvent.addEventListener(() => {
        if (current !== route) return;
        stop(route);
        route.failed = true;
        route.ready = false;
        scene.primitives.remove(model);
        route.model = null;
        updateControls();
      });
      scene.primitives.add(model);
      scene.requestRender();
    } catch {
      if (current === route) {
        route.failed = true;
        updateControls();
      }
    }
  }

  async function groundHeight(carto) {
    const terrain = walker?.terrain;
    if (terrain?.provider) {
      try {
        const [sample] = await Cesium.sampleTerrain(terrain.provider, terrain.level, [Cesium.Cartographic.clone(carto)]);
        if (Number.isFinite(sample?.height)) return sample.height;
      } catch { /* fall back to what the globe has loaded */ }
    }
    const height = scene.globe.getHeight(carto);
    return Number.isFinite(height) ? height : 0;
  }

  async function walkerTo(stop) {
    const route = current;
    if (!walker || !route?.path) return;
    walker.stop = stop;
    updateControls();
    const { path } = route;
    const distance = WALKER_STOPS[stop] * path.length;
    const look = Math.max(5, Math.min(150, path.length * 0.1));
    const at = routePlaybackPoint(path, distance, ellipsoid, new Cesium.Cartesian3());
    let ahead = routePlaybackPoint(path, distance + look, ellipsoid, new Cesium.Cartesian3());
    if (distance + look > path.length) {         // at the target: keep facing the way we arrived
      const behind = routePlaybackPoint(path, distance - look, ellipsoid, new Cesium.Cartesian3());
      ahead = Cesium.Cartesian3.add(at, Cesium.Cartesian3.subtract(at, behind, new Cesium.Cartesian3()), ahead);
    }
    const toLocal = Cesium.Matrix4.inverseTransformation(
      Cesium.Transforms.eastNorthUpToFixedFrame(at, ellipsoid), new Cesium.Matrix4());
    const local = Cesium.Matrix4.multiplyByPoint(toLocal, ahead, new Cesium.Cartesian3());
    const heading = Math.atan2(local.x, local.y);
    const carto = ellipsoid.cartesianToCartographic(at);
    const ground = await groundHeight(carto);
    if (!walker || current !== route || walker.stop !== stop) return;
    const exaggeration = scene.verticalExaggeration || 1;
    camera.flyTo({
      destination: Cesium.Cartesian3.fromRadians(carto.longitude, carto.latitude,
        ground * exaggeration + WALKER_EYE_M, ellipsoid),
      orientation: { heading, pitch: Cesium.Math.toRadians(-4), roll: 0 },
      duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1.6,
    });
    walkStatus.textContent = `Walker's view ${stop + 1}/${WALKER_STOPS.length}: ${WALKER_STOP_NAMES[stop]} ` +
      `(${(distance / 1000).toFixed(2)} km along), eye height ${WALKER_EYE_M} m. Ground from 200 m NASA ` +
      "elevation data, so boulders are not shown. Shift-drag to look around.";
  }

  async function enterWalker() {
    const route = current;
    if (!route?.path || walker) return;
    stop(route);
    walker = { route, stop: 0, terrain: null, background: scene.backgroundColor.clone() };
    if (route.model) route.model.show = false;    // don't stand inside the animated model
    scene.backgroundColor = Cesium.Color.fromCssColorString(WALKER_SKY);
    walkStatus.textContent = "Loading the 3D ground…";
    updateControls();
    try { walker.terrain = await beforeWalk?.(); } catch { walker && (walker.terrain = null); }
    if (walker?.route === route) walkerTo(0);
  }

  function exitWalker(flyBack = true) {
    if (!walker) return;
    const { route, background } = walker;
    walker = null;
    scene.backgroundColor = background;
    if (route.model) route.model.show = true;
    afterWalk?.();
    if (flyBack && route === current) {
      const range = Cesium.Math.clamp(route.path.bounds.radius * 3.2, 320, 80000);
      camera.flyToBoundingSphere(route.path.bounds, {
        offset: new Cesium.HeadingPitchRange(Cesium.Math.toRadians(-20), Cesium.Math.toRadians(-55), range),
        duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1.2,
      });
    }
    updateControls();
    scene.requestRender();
  }

  if (walk) {
    walk.addEventListener("click", enterWalker);
    walkPrev.addEventListener("click", () => walker && walkerTo(Math.max(0, walker.stop - 1)));
    walkNext.addEventListener("click", () => walker && walkerTo(Math.min(WALKER_STOPS.length - 1, walker.stop + 1)));
    walkExit.addEventListener("click", () => exitWalker(true));
  }

  button.addEventListener("click", () => {
    const route = current;
    if (!route) return;
    if (walker) exitWalker(false);
    if (route.failed) { load(route); return; }
    if (!route.ready) return;
    if (route.playing) {
      stop(route);
    } else {
      if (route.elapsed === route.duration) route.elapsed = 0;
      if (route.elapsed === 0) {
        const range = Cesium.Math.clamp(route.path.bounds.radius * 3.2, 320, 80000);
        const offset = new Cesium.HeadingPitchRange(Cesium.Math.toRadians(-20), Cesium.Math.toRadians(-55), range);
        const immediate = matchMedia("(prefers-reduced-motion: reduce)").matches;
        camera.flyToBoundingSphere(route.path.bounds, { offset, duration: immediate ? 0 : 0.8 });
      }
      route.playing = true;
      frame = requestAnimationFrame(tick);
    }
    updateControls();
  });

  return {
    setRoute(kind, points, vehicle, label) {
      if (current?.source === points && current.kind === kind) return;
      const modelKey = vehicle === "on_foot" ? "astronaut" : vehicle;
      const path = routeModelKeys.has(modelKey) ? routePlaybackPath(points, ellipsoid) : null;
      if (!path) { clear(kind); return; }
      clear();
      current = {
        kind, source: points, path, modelKey, label, elapsed: 0, duration: Cesium.Math.clamp(path.length / 330, 6, 20),
        ready: false, playing: false, failed: false, lastFrame: null, model: null,
      };
      load(current);
    },
    clear,
    walking: () => !!walker,
  };
}
