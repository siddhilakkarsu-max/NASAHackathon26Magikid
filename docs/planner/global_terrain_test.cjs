"use strict";
const assert = require("node:assert/strict");
const C = require("../../frontend/vendor/Cesium/index.cjs");
const { createRegionalTerrainProvider } = require("../../frontend/regional_terrain.js");
const scheme = new C.GeographicTilingScheme({ ellipsoid: C.Ellipsoid.MARS });
function baseProvider() {
  return { tilingScheme: scheme, credit: new C.Credit("Test global terrain"), errorEvent: new C.Event(),
    getTileDataAvailable: (x, y, level) => level <= 7,
    getLevelMaximumGeometricError: level => 20000 / 2 ** level,
    requestTileGeometry: (x, y, level) => Promise.resolve(new C.HeightmapTerrainData({
      buffer: new Float32Array([1, 2, 3, 4]), width: 2, height: 2, childTileMask: level < 7 ? 15 : 0 })) };
}
function metadata(regions) {
  return { available: true, minimum_level: 8, maximum_level: 11, grid_size: 257,
    tile_url: "/terrain/detail/{z}/{y}/{x}.bin", regions };
}
const region = (id, w, s, e, n, resolution = 20, maximum = 11) => ({ id,
  rectangle: { west: w, south: s, east: e, north: n }, resolution_m: resolution, maximum_level: maximum });
const toTile = (lon, lat, level) => scheme.positionToTileXY(C.Cartographic.fromDegrees(lon, lat), level);
const plainRect = (x, y, level) => {
  const r = scheme.tileXYToRectangle(x, y, level);
  return { west: C.Math.toDegrees(r.west), east: C.Math.toDegrees(r.east),
    south: C.Math.toDegrees(r.south), north: C.Math.toDegrees(r.north) };
};
function oracle(regions, x, y, level) {
  const a = plainRect(x, y, level);
  return regions.some(r => level <= r.maximum_level && a.west < r.rectangle.east &&
    a.east > r.rectangle.west && a.south < r.rectangle.north && a.north > r.rectangle.south);
}
let fetches = 0, rejectPending = null, mode = "normal";
class Resource {
  fetchArrayBuffer() {
    fetches++;
    if (mode === "hold") return new Promise((resolve, reject) => { rejectPending = reject; });
    return Promise.resolve(new Float32Array(257 ** 2).fill(-3000).buffer);
  }
}
const Cesium = { ...C, Resource };

(async () => {
  const regions = [region("hrsc", 40, 0, 42, 2, 50, 10), region("ctx", 40.03, 0.03, 40.14, 0.14),
    region("seam-east", 179.8, -1, 180, 1), region("seam-west", -180, -1, -179.8, 1)];
  const provider = await createRegionalTerrainProvider(Cesium, baseProvider(), { metadata: metadata(regions) });
  for (const level of [8, 9, 10, 11]) {
    for (const [lon, lat] of [[40.08, 0.08], [41, 1], [179.95, 0], [-179.95, 0], [0, 0]]) {
      const t = toTile(lon, lat, level);
      assert.equal(provider.getTileDataAvailable(t.x, t.y, level), oracle(regions, t.x, t.y, level),
        `Availability must follow actual footprints and source cap: ${lon},${lat},${level}`);
    }
  }
  assert.equal(provider.getDetailForPosition(C.Cartographic.fromDegrees(40.08, 0.08)).id, "ctx");
  assert.equal(provider.getDetailForPosition(C.Cartographic.fromDegrees(41, 1)).id, "hrsc");
  assert.equal(provider.getDetailForPosition(C.Cartographic.fromDegrees(179.95, 0)).id, "seam-east");
  assert.equal(provider.getDetailForPosition(C.Cartographic.fromDegrees(-179.95, 0)).id, "seam-west");
  assert.equal(provider.getDetailForPosition(C.Cartographic.fromDegrees(0, 0)), null, "A seam footprint must not cover the opposite hemisphere");

  for (const [lon, lat, level] of [[40.08, 0.08, 7], [40.08, 0.08, 10], [41, 1, 10]]) {
    const t = toTile(lon, lat, level), data = await provider.requestTileGeometry(t.x, t.y, level);
    for (const dx of [0, 1]) for (const dy of [0, 1]) {
      const x = 2 * t.x + dx, y = 2 * t.y + dy;
      assert.equal(data.isChildAvailable(t.x, t.y, x, y), oracle(regions, x, y, level + 1),
        "Every child mask bit must respect the finer source's actual footprint and native cap");
    }
  }
  console.log("PASS mixed-resolution child masks, smallest real source selection, split-dateline coverage and no opposite-hemisphere leakage");

  // Cancellation belongs to the first Cesium Request in an in-flight fetch.
  // Other consumers can observe its rejection, but a later fresh request must
  // fetch again instead of keeping the canceled promise cached forever.
  mode = "hold";
  const tile = toTile(179.95, 0, 11), before = fetches;
  const a = provider.requestTileGeometry(tile.x, tile.y, 11);
  const b = provider.requestTileGeometry(tile.x, tile.y, 11);
  const settled = Promise.allSettled([a, b]);
  assert.equal(fetches, before + 1);
  rejectPending(Object.assign(new Error("Intentional camera-request cancellation"), { name: "AbortError" }));
  assert((await settled).every(r => r.status === "rejected"));
  mode = "normal";
  const recovered = await provider.requestTileGeometry(tile.x, tile.y, 11);
  assert(recovered instanceof C.HeightmapTerrainData);
  assert.equal(fetches, before + 2);
  console.log("PASS cancellation cannot permanently poison the shared tile cache");

  // A deterministic 44k-footprint catalog exercises the actual production
  // index, compared against a simple exhaustive spatial oracle.
  let seed = 123456789;
  const random = () => ((seed = (1664525 * seed + 1013904223) >>> 0) / 2 ** 32);
  const large = Array.from({ length: 44000 }, (_, i) => {
    const west = -179.8 + random() * 359.4, south = -84.8 + random() * 169.4;
    return region(`source-${i}`, west, south, west + 0.2, south + 0.2, i % 3 ? 20 : 50, i % 3 ? 11 : 10);
  });
  const started = performance.now();
  const indexed = await createRegionalTerrainProvider(Cesium, baseProvider(), { metadata: metadata(large) });
  const constructionMs = performance.now() - started;
  assert.equal(indexed.detailRegions.length, large.length);
  const queries = Array.from({ length: 120 }, (_, i) => {
    const source = large[Math.floor(random() * large.length)], level = i % 2 ? 10 : 11;
    return { ...toTile((source.rectangle.west + source.rectangle.east) / 2,
      (source.rectangle.south + source.rectangle.north) / 2, level), level };
  });
  const queryStart = performance.now();
  const values = queries.map(q => indexed.getTileDataAvailable(q.x, q.y, q.level));
  const queryMs = performance.now() - queryStart;
  queries.forEach((q, i) => assert.equal(values[i], oracle(large, q.x, q.y, q.level)));
  console.log(`PASS 44,000-footprint index agrees with exhaustive oracle; build ${constructionMs.toFixed(1)} ms, 120 lookups ${queryMs.toFixed(1)} ms`);
})().catch(error => { console.error(error); process.exitCode = 1; });
