"use strict";

function createTemperatureView({ viewer, ellipsoid, api, current, opacity, onChange }) {
  let request = null;
  let detail = [];
  let displayed = null;
  let moving = false;

  function removeDetail() {
    const wasLoading = request !== null;
    request?.abort();
    request = null;
    const previous = displayed;
    displayed = null;
    if (previous && previous.collection.contains(previous.overview)) previous.overview.show = true;
    for (const { layer, collection } of detail) collection.remove(layer, true);
    detail = [];
    if (previous || wasLoading) onChange("overview");
  }

  function viewBounds() {
    const view = viewer.camera.computeViewRectangle(ellipsoid);
    if (!view) return [];
    const degrees = Cesium.Math.toDegrees;
    const span = degrees(view.width);
    const south = degrees(view.south), north = degrees(view.north);
    if (span > 55 || north - south > 40) return [];
    const west = degrees(view.west);
    const left = Math.floor(west / 2) * 2 - 2;
    const right = Math.ceil((west + span) / 2) * 2 + 2;
    const bottom = Math.max(-90, Math.floor(south / 2) * 2 - 2);
    const top = Math.min(90, Math.ceil(north / 2) * 2 + 2);
    const wrap = ((left + 180) % 360 + 360) % 360 - 180;
    const end = wrap + right - left;
    const first = { west: wrap, south: bottom, east: Math.min(end, 180), north: top };
    if (end <= 180) return [first];
    return [first, { ...first, west: -180, east: end - 360 }];
  }

  async function refresh() {
    const snapshot = current();
    const bounds = snapshot && !moving ? viewBounds() : [];
    if (!bounds.length) { removeDetail(); return; }
    const key = JSON.stringify(bounds);
    if (displayed?.key === key && displayed.overview === snapshot.overview) return;
    request?.abort();
    const load = new AbortController();
    request = load;
    onChange("loading");
    try {
      const maps = await Promise.all(bounds.map(rect => api(
        "/api/weather/temperature-detail", { ...snapshot.conditions, ...rect }, load.signal,
      )));
      if (request !== load) return;
      const providers = await Promise.all(maps.map(map => {
        const { west, south, east, north } = map.rect;
        return Cesium.SingleTileImageryProvider.fromUrl(map.image, {
          ellipsoid, rectangle: Cesium.Rectangle.fromDegrees(west, south, east, north),
        });
      }));
      if (request !== load || current()?.overview !== snapshot.overview) return;
      for (const { layer, collection } of detail) collection.remove(layer, true);
      detail = [];
      for (const provider of providers) {
        const layer = snapshot.collection.addImageryProvider(provider);
        layer.alpha = opacity();
        detail.push({ layer, collection: snapshot.collection });
      }
      snapshot.overview.show = false;
      displayed = { ...snapshot, key, bounds: maps.map(map => map.rect), step: maps[0].grid_step_deg };
      const ranges = maps.map(map => map.temperature_range).filter(Boolean);
      const range = ranges.length ? [
        Math.min(...ranges.map(values => values[0])),
        Math.max(...ranges.map(values => values[1])),
      ] : null;
      onChange("detail", displayed.step, range);
    } catch (error) {
      if (request !== load || error.name === "AbortError") return;
      removeDetail();
      onChange("unavailable");
    } finally {
      if (request === load) request = null;
    }
  }

  viewer.camera.moveStart.addEventListener(() => { moving = true; removeDetail(); });
  viewer.camera.moveEnd.addEventListener(() => { moving = false; refresh(); });

  function stepAt(point) {
    if (!displayed) return null;
    const lon = ((point.lon + 180) % 360 + 360) % 360 - 180;
    const covered = displayed.bounds.some(rect => lon >= rect.west && lon < rect.east
      && point.lat >= rect.south && point.lat <= rect.north);
    return covered ? displayed.step : null;
  }

  return {
    refresh, clear: removeDetail, stepAt,
    setOpacity(value) { for (const { layer } of detail) layer.alpha = value; },
  };
}
