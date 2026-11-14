"use strict";

const windMotion = (() => {
  const RAD = Math.PI / 180;
  const TRAIL_LENGTH = 7;
  const TRAIL_STEP = 0.13;
  const SIMULATION_SPEED = 18000; // Mars seconds per display second at globe scale.
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
    return { sample, west, width, north: northEdge, south };
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
    const velocity = {};
    const radius = ellipsoid.maximumRadius;
    const tracks = [];
    const projected = Array.from({length: TRAIL_LENGTH + 1}, () => ({ x: 0, y: 0, visible: false }));
    let paused = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frameId, lastFrame, width, height, dpr;
    let fieldAtTime = field;
    let lastCloseView = false;

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

    function seed(timeScale, closeView) {
      let point;
      if (closeView) {
        const hit = viewer.camera.pickEllipsoid(
          new Cesium.Cartesian2(Math.random() * width, Math.random() * height), ellipsoid);
        if (hit) {
          const position = ellipsoid.cartesianToCartographic(hit);
          point = { lat: position.latitude, lon: position.longitude };
        }
      }
      if (!point) {
        // Equal-area seeds distribute the arrows across the sphere evenly.
        const minY = Math.sin(fieldAtTime.south), maxY = Math.sin(fieldAtTime.north);
        point = {
          lat: Math.asin(minY + Math.random() * (maxY - minY)),
          lon: fieldAtTime.west + Math.random() * fieldAtTime.width,
        };
      }
      const tail = { ...point };
      const trail = [];
      for (let i = 0; i < TRAIL_LENGTH; i++) {
        if (!advance(tail, -TRAIL_STEP * timeScale)) break;
        trail.unshift({ ...tail });
      }
      return { ...point, trail, elapsed: 0, age: Math.random() * 2.8, life: 3.5 + Math.random() * 4 };
    }

    function surfaceProjection(point, result) {
      Cesium.Cartesian3.fromRadians(point.lon, point.lat, 0, ellipsoid, world);
      ellipsoid.transformPositionToScaledSpace(world, scaled);
      // A scaled ellipsoid point is visible only on the viewing side of
      // the unit sphere's tangent plane.
      if (Cesium.Cartesian3.dot(scaled, cameraScaled) <= 1.002 ||
          !Cesium.SceneTransforms.worldToWindowCoordinates(scene, world, pixel)) {
        result.visible = false;
        return;
      }
      result.x = pixel.x;
      result.y = pixel.y;
      result.visible = true;
    }

    function draw(track) {
      const count = track.trail.length;
      surfaceProjection(track, projected[count]);
      const head = projected[count];
      if (!head.visible || head.x < -12 || head.y < -12 || head.x > width + 12 || head.y > height + 12) return;
      for (let i = 0; i < count; i++) surfaceProjection(track.trail[i], projected[i]);
      let first = count;
      while (first > 0 && projected[first - 1].visible) first--;
      if (first === count) return;
      const tail = projected[count - 1];
      const dx = head.x - tail.x, dy = head.y - tail.y;
      if (Math.hypot(dx, dy) < 0.06) return;
      const angle = Math.atan2(dy, dx);
      const arrowSize = Math.min(5, Math.max(2, Math.hypot(head.x - projected[first].x,
        head.y - projected[first].y) * 0.45));
      ctx.beginPath();
      ctx.moveTo(projected[first].x, projected[first].y);
      for (let i = first + 1; i <= count; i++) ctx.lineTo(projected[i].x, projected[i].y);
      for (const turn of [-0.61, 0.61]) {
        ctx.moveTo(head.x - arrowSize * Math.cos(angle + turn), head.y - arrowSize * Math.sin(angle + turn));
        ctx.lineTo(head.x, head.y);
      }
      ctx.globalAlpha = Math.max(0, Math.min(1, track.age * 3, (track.life - track.age) * 3));
      ctx.strokeStyle = "#171427";
      ctx.lineWidth = 2.9;
      ctx.stroke();
      ctx.strokeStyle = "#f7fcff";
      ctx.lineWidth = 1.25;
      ctx.stroke();
    }

    function frame(now) {
      frameId = requestAnimationFrame(frame);
      if (lastFrame !== undefined && now - lastFrame < 32) return;
      const elapsed = lastFrame === undefined ? 0 : Math.min((now - lastFrame) / 1000, 0.085);
      lastFrame = now;
      const nextWidth = scene.canvas.clientWidth, nextHeight = scene.canvas.clientHeight;
      const nextDpr = Math.min(2, window.devicePixelRatio || 1);
      if (!nextWidth || !nextHeight) return;
      if (width !== nextWidth || height !== nextHeight || dpr !== nextDpr) {
        width = nextWidth;
        height = nextHeight;
        dpr = nextDpr;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
      }
      ctx.clearRect(0, 0, width, height);
      const altitude = viewer.camera.positionCartographic.height / radius;
      const closeView = altitude < 0.25;
      const timeScale = SIMULATION_SPEED * Math.max(0.015, Math.min(1, altitude));
      const count = Math.max(220, Math.min(750, Math.round(width * height / (closeView ? 4800 : 1200))));
      if (closeView !== lastCloseView) tracks.length = 0;
      lastCloseView = closeView;
      ellipsoid.transformPositionToScaledSpace(viewer.camera.positionWC, cameraScaled);
      for (let i = 0; i < count; i++) {
        let track = tracks[i];
        if (!track || track.age >= track.life) track = tracks[i] = seed(timeScale, closeView);
        if (!paused && elapsed > 0) {
          track.age += elapsed;
          track.elapsed += elapsed;
          if (track.elapsed >= TRAIL_STEP) {
            track.elapsed %= TRAIL_STEP;
            track.trail.push({ lat: track.lat, lon: track.lon });
            if (track.trail.length > TRAIL_LENGTH) track.trail.shift();
          }
          if (!advance(track, elapsed * timeScale)) track.age = track.life;
        }
        draw(track);
      }
    }

    frameId = requestAnimationFrame(frame);
    return {
      viewer, container,
      setField(nextField) { fieldAtTime = nextField; },
      setPaused(value) { paused = value; },
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
