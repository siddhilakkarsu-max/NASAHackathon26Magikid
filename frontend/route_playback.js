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

function createRoutePlayback({ viewer, ellipsoid, controls }) {
  const { scene, camera } = viewer;
  const { panel, button, status } = controls;
  let current = null;
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

  button.addEventListener("click", () => {
    const route = current;
    if (!route) return;
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
  };
}
