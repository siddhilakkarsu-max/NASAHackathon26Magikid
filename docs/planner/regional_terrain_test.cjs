"use strict";
const assert = require("node:assert/strict");
const C = require("../../frontend/vendor/Cesium/index.cjs");
const { createRegionalTerrainProvider } = require("../../frontend/regional_terrain.js");

const scheme = new C.GeographicTilingScheme({ ellipsoid: C.Ellipsoid.MARS });
const metadata = { available: true, rectangle: { west: 77, south: 18, east: 78, north: 19 },
  minimum_level: 8, maximum_level: 11, grid_size: 257, resolution_m: 20,
  tile_url: "/terrain/jezero/{z}/{y}/{x}.bin", credit: "USGS/JPL" };
const requests = [];
let throttle = false, pendingGate = null, malformed = false;
class Resource {
  constructor(options) { this.options = options; }
  fetchArrayBuffer() {
    if (throttle) { throttle = false; return undefined; }
    requests.push(this.options);
    return Promise.resolve(pendingGate).then(() => {
      const bytes = new ArrayBuffer(metadata.grid_size ** 2 * 4), view = new DataView(bytes);
      for (let i = 0; i < metadata.grid_size ** 2; i++) view.setFloat32(i * 4, -3000 + i / 8, true);
      if (malformed) view.setFloat32(0, NaN, true);
      return bytes;
    });
  }
}
const Cesium = { ...C, Resource };
let globalRequests = 0;
const base = {
  tilingScheme: scheme, credit: new C.Credit("Global measured terrain"), errorEvent: new C.Event(),
  getTileDataAvailable: (x, y, level) => level <= 7,
  getLevelMaximumGeometricError: level => 20000 / 2 ** level,
  requestTileGeometry(x, y, level) {
    globalRequests++;
    return Promise.resolve(new C.HeightmapTerrainData({ buffer: new Float32Array([1, 2, 3, 4]),
      width: 2, height: 2, childTileMask: level < 7 ? 15 : 0 }));
  },
};
const xy = level => scheme.positionToTileXY(C.Cartographic.fromDegrees(77.45, 18.45), level);

(async () => {
  const provider = await createRegionalTerrainProvider(Cesium, base, { metadata });
  assert.equal(provider.baseProvider, base);
  assert.equal(provider.regionalMetadata, metadata);
  assert.equal(provider.getTileDataAvailable(xy(11).x, xy(11).y, 11), true);
  assert.equal(provider.getTileDataAvailable(xy(12).x, xy(12).y, 12), false);
  assert.equal(provider.getTileDataAvailable(0, 0, 8), false);
  await assert.rejects(provider.requestTileGeometry(0, 0, 8), /No regional elevation/);
  const p7 = xy(7), parent = await provider.requestTileGeometry(p7.x, p7.y, 7);
  const p8 = xy(8);
  assert(parent.isChildAvailable(p7.x, p7.y, p8.x, p8.y), "Native global parent exposes genuine regional children");
  const remote = await provider.requestTileGeometry(0, 0, 7);
  assert.equal(remote.isChildAvailable(0, 0, 0, 0), false, "No finer source is invented outside Jezero");
  assert.equal(globalRequests, 2);

  const p11 = xy(11), request = { throttle: true };
  throttle = true;
  assert.equal(provider.requestTileGeometry(p11.x, p11.y, 11, request), undefined, "Preserve Cesium's throttle sentinel");
  assert.equal(requests.length, 0);
  let release;
  pendingGate = new Promise(resolve => { release = resolve; });
  const firstLoad = provider.requestTileGeometry(p11.x, p11.y, 11, request);
  const secondLoad = provider.requestTileGeometry(p11.x, p11.y, 11, request);
  assert.equal(requests.length, 1, "One in-flight fetch per tile");
  assert.equal(requests[0].request, request);
  release(); pendingGate = null;
  const [first, second] = await Promise.all([firstLoad, secondLoad]);
  assert.notEqual(first, second, "Each consumer gets a fresh mesh input");
  const rectangle = scheme.tileXYToRectangle(p11.x, p11.y, 11);
  assert.equal(first.interpolateHeight(rectangle, rectangle.west, rectangle.north), -3000);
  assert.equal(first.interpolateHeight(rectangle, rectangle.east, rectangle.south), -3000 + (257 ** 2 - 1) / 8);
  assert.equal(first.isChildAvailable(p11.x, p11.y, p11.x * 2, p11.y * 2), false);
  const cached = await provider.requestTileGeometry(p11.x, p11.y, 11);
  assert.notEqual(cached, first);
  assert.equal(requests.length, 1, "Subsequent reads reuse validated bytes");

  malformed = true;
  await assert.rejects(provider.requestTileGeometry(p8.x, p8.y, 8), /missing heights/);
  malformed = false;
  const recovered = await provider.requestTileGeometry(p8.x, p8.y, 8);
  assert(recovered instanceof C.HeightmapTerrainData);
  assert.equal(requests.length, 3, "Corrupt responses are not cached; retry fetches new bytes");
  const originalNow = Date.now, fetchedBeforeExpiry = requests.length;
  try {
    const later = originalNow() + 31000;
    Date.now = () => later;
    await provider.requestTileGeometry(p11.x, p11.y, 11);
    assert.equal(requests.length, fetchedBeforeExpiry + 1,
      "Expired bytes can recover from a previous real coarse fallback");
  } finally { Date.now = originalNow; }

  const unavailable = await createRegionalTerrainProvider(Cesium, base, { metadata: { available: false, error: "Not installed" } });
  assert.equal(unavailable, base);
  assert.equal(unavailable.regionalMetadata, null);
  assert.equal(unavailable.regionalError, "Not installed");
  const region = (id, west, south, east, north, resolution_m, maximum_level) =>
    ({ id, rectangle: { west, south, east, north }, resolution_m, maximum_level });
  const worldwide = { ...metadata, tile_url: "/terrain/detail/{z}/{y}/{x}.bin", regions: [
    region("jezero", 77, 18, 78, 19, 20, 11),
    region("hrsc", -80, 0, -78, 2, 50, 10),
    region("ctx", -79.5, 0.5, -79, 1, 20, 11),
    region("seam-west", -180, -5, -179.5, -4, 20, 11),
    region("seam-east", 179.5, -5, 180, -4, 20, 11),
  ] };
  const all = await createRegionalTerrainProvider(Cesium, base, { metadata: worldwide });
  const has = (lon, lat, level) => {
    const xy = scheme.positionToTileXY(C.Cartographic.fromDegrees(lon, lat), level);
    return all.getTileDataAvailable(xy.x, xy.y, level);
  };
  assert(has(-79.8, 1.8, 10)); assert.equal(has(-79.8, 1.8, 11), false);
  assert(has(-79.25, 0.75, 11)); assert.equal(has(-79.25, 0.75, 12), false);
  assert(has(179.8, -4.5, 11)); assert(has(-179.8, -4.5, 11));
  assert.equal(has(0, -4.5, 11), false, "Dateline coverage does not wrap across the whole planet");
  assert.equal(all.getDetailForPosition(C.Cartographic.fromDegrees(-79.25, 0.75)).id, "ctx");
  assert.equal(all.getDetailForPosition(C.Cartographic.fromDegrees(-79.8, 1.8)).id, "hrsc");
  assert.equal(all.getDetailForPosition(C.Cartographic.fromDegrees(0, 0)), null);
  const bad = await createRegionalTerrainProvider(Cesium, base, { metadata: { ...worldwide,
    regions: [region("bad", -181, 0, 0, 1, 20, 11)] } });
  assert.equal(bad, base, "Invalid source footprints retain verified global fallback");
  const missing = await createRegionalTerrainProvider(Cesium, base, { metadata: { available: false, message: "Catalog could not load" } });
  assert.equal(missing.regionalError, "Catalog could not load");
  console.log("PASS regional source routing, native caps, child masks, row order, raw heights, throttling, deduplication, cache and missing-source fallback");
  console.log("PASS multiple regions, mixed native resolutions, overlap priority, dateline footprints and metadata validation");
})().catch(error => { console.error(error); process.exitCode = 1; });
