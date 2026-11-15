"use strict";

// Combine the global MOLA/HRSC terrain with published higher-resolution DEMs. The
// server samples both measured sources on shared tile-edge coordinates and
// feathers only the documented coverage boundary. No photo-derived relief.
async function createRegionalTerrainProvider(Cesium, base, options = {}) {
  const api = options.api || "";
  let metadata;
  try {
    if (options.metadata) metadata = options.metadata;
    else {
      const response = await fetch(api + "/api/terrain/detail", { cache: "no-cache", signal: AbortSignal.timeout(20000) });
      if (!response.ok) throw new Error(`Regional elevation metadata returned ${response.status}`);
      metadata = await response.json();
    }
    if (!metadata.available) throw new Error(metadata.message || metadata.error || metadata.reason || "Detailed elevation sources are unavailable");
    const regions = metadata.regions || [metadata];
    if (!Array.isArray(regions) || !regions.length || regions.length > 100000 ||
        regions.some(region => {
          const r = region.rectangle;
          return !r || ![r.west, r.south, r.east, r.north].every(Number.isFinite) ||
            r.west >= r.east || r.south >= r.north || r.west < -180 || r.east > 180 || r.south < -90 || r.north > 90 ||
            !Number.isFinite(region.resolution_m) || region.resolution_m <= 0 ||
            !Number.isInteger(region.maximum_level) || region.maximum_level < metadata.minimum_level || region.maximum_level > metadata.maximum_level;
        }) || !Number.isInteger(metadata.grid_size) || metadata.grid_size < 2 || metadata.grid_size > 513 ||
        !Number.isInteger(metadata.minimum_level) || metadata.minimum_level !== (options.baseMaximumLevel ?? 7) + 1 ||
        !Number.isInteger(metadata.maximum_level) || metadata.maximum_level < metadata.minimum_level || metadata.maximum_level > 16 ||
        typeof metadata.tile_url !== "string" || !/^\/terrain\/(detail|jezero)\//.test(metadata.tile_url)) {
      throw new Error("Regional elevation metadata is invalid");
    }
  } catch (error) {
    // Keep the verified global service available if the optional catalog is
    // missing. Surface this limitation instead of claiming finer coverage.
    base.regionalMetadata = null;
    base.regionalError = error.message || String(error);
    options.onStatus?.(base.regionalError);
    return base;
  }

  const scheme = base.tilingScheme;
  const baseMaximumLevel = options.baseMaximumLevel ?? 7;
  const minimumLevel = metadata.minimum_level, maximumLevel = metadata.maximum_level, size = metadata.grid_size;
  const cache = new Map(), inflight = new Map();
  const cacheLimit = Math.max(1, Math.min(128, options.cacheTiles || 64));
  // Responses may contain real coarse fallback after an upstream outage. Do
  // not retain those bytes forever after the backend's short retry lifetime.
  const cacheLifetimeMs = 30000;
  const escape = text => String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const credit = new Cesium.Credit((base.credit?.html || "NASA, ESA, USGS, Esri global Mars elevation") +
    " · " + escape(metadata.credit || "Surveyed Mars elevation: NASA/JPL/USGS, ESA/DLR/FU Berlin"));
  const regions = (metadata.regions || [metadata]).map(source => ({ ...source,
    bounds: Cesium.Rectangle.fromDegrees(source.rectangle.west, source.rectangle.south,
      source.rectangle.east, source.rectangle.north) }));
  // Index by native global parent tile: thousands of survey footprints should
  // not require thousands of rectangle tests for every frame's child lookup.
  const regionIndex = new Map();
  const columns = scheme.getNumberOfXTilesAtLevel(baseMaximumLevel);
  const rows = scheme.getNumberOfYTilesAtLevel(baseMaximumLevel);
  for (const region of regions) {
    const r = region.rectangle;
    const x0 = Math.max(0, Math.floor((r.west + 180) / 360 * columns));
    const x1 = Math.min(columns - 1, Math.ceil((r.east + 180) / 360 * columns) - 1);
    const y0 = Math.max(0, Math.floor((90 - r.north) / 180 * rows));
    const y1 = Math.min(rows - 1, Math.ceil((90 - r.south) / 180 * rows) - 1);
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const key = y * columns + x;
      if (!regionIndex.has(key)) regionIndex.set(key, []);
      regionIndex.get(key).push(region);
    }
  }
  const rectangleScratch = new Cesium.Rectangle();
  function inRegion(x, y, level) {
    const r = scheme.tileXYToRectangle(x, y, level, rectangleScratch);
    const factor = 2 ** (level - baseMaximumLevel);
    const candidates = regionIndex.get(Math.floor(y / factor) * columns + Math.floor(x / factor)) || [];
    return candidates.some(region => level <= region.maximum_level &&
      r.west < region.bounds.east && r.east > region.bounds.west &&
      r.south < region.bounds.north && r.north > region.bounds.south);
  }
  function available(x, y, level) {
    if (level <= baseMaximumLevel) return base.getTileDataAvailable(x, y, level);
    return level <= maximumLevel && inRegion(x, y, level);
  }
  function childMask(x, y, level) {
    if (level >= maximumLevel) return 0;
    let mask = 0;
    // Cesium child bits: SW=1, SE=2, NW=4, NE=8; tile y increases southward.
    for (const [dx, dy, bit] of [[0, 1, 1], [1, 1, 2], [0, 0, 4], [1, 0, 8]]) {
      if (available(2 * x + dx, 2 * y + dy, level + 1) !== false) mask |= bit;
    }
    return mask;
  }
  function terrainData(buffer, x, y, level) {
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== size * size * 4) {
      throw new Error("The detailed elevation tile has an invalid byte count");
    }
    const source = new DataView(buffer), heights = new Float32Array(size * size);
    for (let i = 0; i < heights.length; i++) {
      const value = source.getFloat32(i * 4, true);
      if (!Number.isFinite(value)) throw new Error("The detailed elevation tile has missing heights");
      heights[i] = value;
    }
    // A fresh TerrainData object is necessary: Cesium transfers its height
    // buffer into a mesh. Cache immutable bytes, never the consumed object.
    return new Cesium.HeightmapTerrainData({ buffer: heights, width: size, height: size,
      childTileMask: childMask(x, y, level) });
  }
  const regionalZeroError = Cesium.TerrainProvider.getEstimatedLevelZeroGeometricErrorForAHeightmap(
    scheme.ellipsoid, size, scheme.getNumberOfXTilesAtLevel(0));
  const provider = {
    baseProvider: base,
    regionalMetadata: metadata,
    regionalError: null,
    detailRegions: regions,
    getDetailForPosition(position) {
      const xy = scheme.positionToTileXY(position, baseMaximumLevel);
      if (!xy) return null;
      const candidates = regionIndex.get(xy.y * columns + xy.x) || [];
      let finest = null;
      for (const region of candidates) {
        if ((!finest || region.resolution_m < finest.resolution_m) &&
            Cesium.Rectangle.contains(region.bounds, position)) finest = region;
      }
      return finest;
    },
    tilingScheme: scheme,
    errorEvent: base.errorEvent,
    credit,
    hasWaterMask: false,
    hasVertexNormals: false,
    availability: undefined,
    getTileDataAvailable: available,
    loadTileDataAvailability: () => undefined,
    getLevelMaximumGeometricError(level) {
      // Above native global level, this describes the regional grid's actual
      // sample spacing. Elsewhere child availability stops network refinement.
      return level < minimumLevel ? base.getLevelMaximumGeometricError(level) : regionalZeroError / 2 ** level;
    },
    requestTileGeometry(x, y, level, request) {
      if (level < minimumLevel) {
        const pending = base.requestTileGeometry(x, y, level, request);
        if (!pending || level !== baseMaximumLevel || !inRegion(x, y, level)) return pending;
        return Promise.resolve(pending).then(data => {
          // The global provider stops at its real native level. Only children
          // intersecting the installed regional DEM may continue beyond it.
          const mask = childMask(x, y, level);
          data.isChildAvailable = (parentX, parentY, childX, childY) => {
            const dx = childX - 2 * parentX, dy = childY - 2 * parentY;
            const bit = dy === 0 ? (dx === 0 ? 4 : 8) : (dx === 0 ? 1 : 2);
            return !!(mask & bit);
          };
          return data;
        });
      }
      if (!available(x, y, level)) {
        // Globe traversal uses availability/child masks and upsamples its last
        // parent. Explicit sampling outside coverage must fail, not return the
        // throttling sentinel and make that caller retry forever.
        return Promise.reject(new Error("No regional elevation tile exists at this location and level"));
      }
      const key = `${level}/${y}/${x}`;
      if (cache.has(key)) {
        const entry = cache.get(key); cache.delete(key);
        if (entry.expires > Date.now()) {
          cache.set(key, entry);
          return Promise.resolve().then(() => terrainData(entry.buffer, x, y, level));
        }
      }
      let pending = inflight.get(key);
      if (!pending) {
        const url = api + metadata.tile_url.replace("{z}", level).replace("{y}", y).replace("{x}", x);
        pending = new Cesium.Resource({ url, request }).fetchArrayBuffer();
        if (!pending) return undefined; // Preserve Cesium's request-throttling contract.
        pending = Promise.resolve(pending).then(buffer => {
          // Validate before caching, so retrying a corrupt/partial response can
          // fetch new bytes instead of repeatedly reusing the bad tile.
          terrainData(buffer, x, y, level);
          cache.set(key, { buffer, expires: Date.now() + cacheLifetimeMs });
          while (cache.size > cacheLimit) cache.delete(cache.keys().next().value);
          return buffer;
        }).finally(() => inflight.delete(key));
        inflight.set(key, pending);
      }
      return pending.then(buffer => terrainData(buffer, x, y, level));
    },
  };
  return provider;
}

if (typeof module !== "undefined" && module.exports) module.exports = { createRegionalTerrainProvider };
