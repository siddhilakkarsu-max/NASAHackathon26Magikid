"use strict";

const windMotion = (() => {
  const RAD = Math.PI / 180;
  const SIMULATION_SPEED = 18000; // Mars seconds per display second at globe scale.
  const MAX_PARTICLES = 420;
  const FRAME_INTERVAL = 1000 / 30;
  let animation = null;

  function wrap(value, period) {
    return ((value % period) + period) % period;
  }

  function interpolate(grid, iy, nextY, ix, nextX, fy, fx) {
    const a = grid[iy][ix], b = grid[iy][nextX];
    const c = grid[nextY][ix], d = grid[nextY][nextX];
    if (!Number.isFinite(a) || !Number.isFinite(b) || !Number.isFinite(c) || !Number.isFinite(d)) return NaN;
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
  }

  function makeField(vectors) {
    if (!Array.isArray(vectors?.east_ms) || !Array.isArray(vectors.north_ms)) return null;
    const east = vectors.east_ms;
    const north = vectors.north_ms;
    const rows = east.length;
    const columns = east[0]?.length;
    if (rows < 2 || columns < 2 || north.length !== rows ||
        [...east, ...north].some(row => !Array.isArray(row) || row.length !== columns)) return null;
    const west = (vectors.west ?? -180) * RAD;
    const eastEdge = (vectors.east ?? 180) * RAD;
    const south = (vectors.south ?? -90) * RAD;
    const northEdge = (vectors.north ?? 90) * RAD;
    const width = eastEdge - west;
    const height = northEdge - south;
    if (!(width > 0) || !(height > 0)) return null;
    const periodic = Math.abs(width - 2 * Math.PI) < 1e-6;

    // Source samples are centered in regular cells, so the lookup crosses
    // between the first and last columns at the antimeridian.
    function sample(lat, lon, out) {
      const offset = periodic ? wrap(lon - west, width) : lon - west;
      if (lat < south || lat > northEdge || offset < 0 || offset > width) return false;
      const rawX = offset / width * columns - 0.5;
      const x = periodic ? rawX : Math.max(0, Math.min(columns - 1, rawX));
      const y = Math.max(0, Math.min(rows - 1, (northEdge - lat) / height * rows - 0.5));
      const ix = Math.floor(x);
      const iy = Math.floor(y);
      const nextY = Math.min(iy + 1, rows - 1);
      const firstX = periodic ? wrap(ix, columns) : ix;
      const nextX = periodic ? wrap(ix + 1, columns) : Math.min(ix + 1, columns - 1);
      const fx = x - ix, fy = y - iy;

      out.east = interpolate(east, iy, nextY, firstX, nextX, fy, fx);
      out.north = interpolate(north, iy, nextY, firstX, nextX, fy, fx);
      return Number.isFinite(out.east) && Number.isFinite(out.north);
    }
    return { sample };
  }

  function painter(viewer, container, field) {
    const scene = viewer.scene;
    const ellipsoid = scene.globe.ellipsoid;
    const canvas = document.createElement("canvas");
    canvas.className = "wind-motion";
    canvas.setAttribute("aria-hidden", "true");
    Object.assign(canvas.style, {
      position: "absolute", inset: "0", width: "100%", height: "100%",
      pointerEvents: "none", zIndex: "1",
    });
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    container.append(canvas);

    const world = new Cesium.Cartesian3();
    const scaled = new Cesium.Cartesian3();
    const cameraScaled = new Cesium.Cartesian3();
    const pixel = new Cesium.Cartesian2();
    const seedPixel = new Cesium.Cartesian2();
    const hit = new Cesium.Cartesian3();
    const viewScratch = new Cesium.Rectangle();
    const seedPosition = new Cesium.Cartographic();
    const tailPoint = { lat: 0, lon: 0 };
    const head = new Cesium.Cartesian2();
    const tail = new Cesium.Cartesian2();
    const lastView = new Cesium.Matrix4();
    const velocity = {};
    const radius = ellipsoid.maximumRadius;
    const tracks = [];
    let paused = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frameId, lastFrame, width, height, dpr;
    let fieldAtTime = field;
    let fieldChanged = true, nextViewCheck = 0, viewBounds;

    // Move along the local wind bearing on the sphere. This avoids the
    // longitude divisor becoming singular in the polar regions.
    function advance(point, seconds) {
      if (!fieldAtTime.sample(point.lat, point.lon, velocity)) return false;
      const speed = Math.hypot(velocity.east, velocity.north);
      if (speed < 0.1) return false;
      const distance = speed * seconds / radius;
      const sinLat = Math.sin(point.lat), cosLat = Math.cos(point.lat);
      const sinDistance = Math.sin(distance), cosDistance = Math.cos(distance);
      const lat = Math.asin(Math.max(-1, Math.min(1,
        sinLat * cosDistance + cosLat * sinDistance * velocity.north / speed
      )));
      const lon = point.lon + Math.atan2(velocity.east / speed * sinDistance * cosLat,
        cosDistance - sinLat * Math.sin(lat));
      point.lat = lat;
      point.lon = wrap(lon + Math.PI, 2 * Math.PI) - Math.PI;
      return true;
    }

    function seed() {
      // Screen-space seeding covers the part of Mars actually in view, including
      // a tight close-up, without spending particles on the hidden hemisphere.
      for (let attempt = 0; attempt < 5; attempt++) {
        seedPixel.x = Math.random() * width;
        seedPixel.y = Math.random() * height;
        if (!viewer.camera.pickEllipsoid(seedPixel, ellipsoid, hit)) continue;
        ellipsoid.cartesianToCartographic(hit, seedPosition);
        const lat = seedPosition.latitude, lon = seedPosition.longitude;
        if (!fieldAtTime.sample(lat, lon, velocity) || Math.hypot(velocity.east, velocity.north) < 0.1) continue;
        return { lat, lon, age: 0.3 + Math.random() * 2.5, life: 3.5 + Math.random() * 4 };
      }
      return null;
    }

    function surfaceProjection(point, result) {
      Cesium.Cartesian3.fromRadians(point.lon, point.lat, 0, ellipsoid, world);
      ellipsoid.transformPositionToScaledSpace(world, scaled);
      // A scaled ellipsoid point is visible only on the viewing side of
      // the unit sphere's tangent plane.
      if (Cesium.Cartesian3.dot(scaled, cameraScaled) <= 1 + 1e-10 ||
          !Cesium.SceneTransforms.worldToWindowCoordinates(scene, world, pixel)) return false;
      result.x = pixel.x;
      result.y = pixel.y;
      return true;
    }

    function headVisible(track) {
      seedPosition.latitude = track.lat;
      seedPosition.longitude = track.lon;
      return Cesium.Rectangle.contains(viewBounds, seedPosition) && surfaceProjection(track, head)
        && head.x >= 0 && head.y >= 0 && head.x <= width && head.y <= height;
    }

    function draw(track, timeScale) {
      tailPoint.lat = track.lat;
      tailPoint.lon = track.lon;
      if (!advance(tailPoint, -0.32 * timeScale) || !surfaceProjection(tailPoint, tail)) return;
      const dx = head.x - tail.x, dy = head.y - tail.y;
      const distance = Math.hypot(dx, dy);
      if (distance < 0.06) return;
      const length = Math.min(12, Math.max(4.5, distance));
      const ux = dx / distance, uy = dy / distance;
      const arrowSize = Math.min(3.5, length * 0.4);
      ctx.beginPath();
      ctx.moveTo(head.x - length * ux, head.y - length * uy);
      ctx.lineTo(head.x, head.y);
      for (const side of [-0.58, 0.58]) {
        ctx.moveTo(head.x - arrowSize * (ux + side * uy), head.y - arrowSize * (uy - side * ux));
        ctx.lineTo(head.x, head.y);
      }
      ctx.globalAlpha = 0.82 * Math.max(0, Math.min(1, track.age * 3, (track.life - track.age) * 3));
      ctx.strokeStyle = "#171427";
      ctx.lineWidth = 1.9;
      ctx.stroke();
      ctx.strokeStyle = "#f7fcff";
      ctx.lineWidth = 0.9;
      ctx.stroke();
    }

    function frame(now) {
      frameId = requestAnimationFrame(frame);
      if (lastFrame !== undefined && now - lastFrame < FRAME_INTERVAL - 1) return;
      const elapsed = lastFrame === undefined ? 0 : Math.min((now - lastFrame) / 1000, 0.085);
      lastFrame = now;
      const nextWidth = scene.canvas.clientWidth, nextHeight = scene.canvas.clientHeight;
      const nextDpr = Math.min(1.5, window.devicePixelRatio || 1);
      if (!nextWidth || !nextHeight) return;
      const resized = width !== nextWidth || height !== nextHeight || dpr !== nextDpr;
      if (resized) {
        width = nextWidth;
        height = nextHeight;
        dpr = nextDpr;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
      }
      const cameraView = viewer.camera.viewMatrix;
      const cameraChanged = !Cesium.Matrix4.equals(lastView, cameraView);
      if (paused && !fieldChanged && !resized && !cameraChanged) return;
      if (resized || now >= nextViewCheck || (paused && cameraChanged)) {
        viewBounds = viewer.camera.computeViewRectangle(ellipsoid, viewScratch);
        nextViewCheck = now + 120;
      }
      Cesium.Matrix4.clone(cameraView, lastView);
      fieldChanged = false;
      ctx.clearRect(0, 0, width, height);
      if (!viewBounds) return;
      const altitude = Math.max(0.0001, viewer.camera.positionCartographic.height / radius);
      const timeScale = SIMULATION_SPEED * Math.min(1, altitude);
      const spacing = 43 + 14 * Math.min(1, altitude);
      const count = Math.max(45, Math.min(MAX_PARTICLES, Math.round(width * height / spacing ** 2)));
      ellipsoid.transformPositionToScaledSpace(viewer.camera.positionWC, cameraScaled);
      if (tracks.length > count) tracks.length = count;
      let seedBudget = resized || (paused && cameraChanged) ? count : Math.min(count, 64);
      for (let i = 0; i < count; i++) {
        let track = tracks[i];
        if (track && !paused && elapsed > 0) {
          track.age += elapsed;
          if (!advance(track, elapsed * timeScale)) track.age = track.life;
        }
        if (!track || track.age >= track.life || !headVisible(track)) {
          tracks[i] = null;
          if (seedBudget <= 0) continue;
          seedBudget--;
          track = tracks[i] = seed();
          if (!track || !headVisible(track)) continue;
        }
        draw(track, timeScale);
      }
    }

    frameId = requestAnimationFrame(frame);
    return {
      viewer, container,
      setField(nextField) { fieldAtTime = nextField; fieldChanged = true; },
      setPaused(value) { paused = value; fieldChanged = true; },
      stop() {
        cancelAnimationFrame(frameId);
        canvas.remove();
      },
    };
  }

  function start({viewer, container, vectors}) {
    const field = makeField(vectors);
    if (!viewer?.scene?.globe || !container || !field) {
      stop();
      return false;
    }
    if (animation?.viewer === viewer && animation.container === container) {
      animation.setField(field);
    } else {
      stop();
      animation = painter(viewer, container, field);
    }
    return Boolean(animation);
  }

  function stop() {
    animation?.stop();
    animation = null;
  }

  function setPaused(value) {
    animation?.setPaused(Boolean(value));
  }
  return { start, stop, setPaused };
})();
