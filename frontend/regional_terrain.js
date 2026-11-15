"use strict";

// Combine the global MOLA/HRSC terrain with the actual Jezero CTX DEM. The
// server samples both measured sources on shared tile-edge coordinates and
// feathers only the documented coverage boundary. No photo-derived relief.
async function createRegionalTerrainProvider(Cesium, base, options = {}) {
  const api = options.api || "";
  let metadata;
  try {
    if (options.metadata) metadata = options.metadata;
    else {
      const response = await fetch(api + "/api/terrain/jezero", { signal: AbortSignal.timeout(15000) });
      if (!response.ok) throw new Error(`Regional elevation metadata returned ${response.status}`);
      metadata = await response.json();
    }
    if (!metadata.available) throw new Error(metadata.error || metadata.reason || "Jezero's 20 m elevation file is not installed");
    const r = metadata.rectangle;
    if (!r || ![r.west, r.south, r.east, r.north].every(Number.isFinite) ||
        r.west >= r.east || r.south >= r.north || r.west < -180 || r.east > 180 || r.south < -90 || r.north > 90 ||
        !Number.isInteger(metadata.grid_size) || metadata.grid_size < 2 || metadata.grid_size > 513 ||
        !Number.isInteger(metadata.minimum_level) || metadata.minimum_level !== (options.baseMaximumLevel ?? 7) + 1 ||
        !Number.isInteger(metadata.maximum_level) || metadata.maximum_level < metadata.minimum_level || metadata.maximum_level > 16 ||
        typeof metadata.tile_url !== "string" || !metadata.tile_url.startsWith("/terrain/jezero/")) {
      throw new Error("Regional elevation metadata is invalid");
    }
  } catch (error) {
    // Keep the verified global service available if the optional regional DEM
    // is missing. Surface this limitation instead of claiming 20 m coverage.
    base.regionalMetadata = null;
    base.regionalError = error.message || String(error);
    options.onStatus?.(base.regionalError);
    return base;
  }

  const scheme = base.tilingScheme;
  const region = Cesium.Rectangle.fromDegrees(metadata.rectangle.west, metadata.rectangle.south,
    metadata.rectangle.east, metadata.rectangle.north);
  const baseMaximumLevel = options.baseMaximumLevel ?? 7;
  const minimumLevel = metadata.minimum_level, maximumLevel = metadata.maximum_level, size = metadata.grid_size;
  const cache = new Map(), inflight = new Map();
  const cacheLimit = Math.max(1, Math.min(128, options.cacheTiles || 64));
  const escape = text => String(text).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const credit = new Cesium.Credit((base.credit?.html || "NASA, ESA, USGS, Esri global Mars elevation") +
    " · " + escape(metadata.credit || "Jezero CTX elevation: USGS/JPL"));
  const rectangleScratch = new Cesium.Rectangle();
  function inRegion(x, y, level) {
    const r = scheme.tileXYToRectangle(x, y, level, rectangleScratch);
    // Strict overlap avoids requesting the neighboring tile when it merely
    // touches a DEM boundary. Jezero does not cross the longitude seam.
    return r.west < region.east && r.east > region.west && r.south < region.north && r.north > region.south;
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
      throw new Error("The Jezero elevation tile has an invalid byte count");
    }
    const source = new DataView(buffer), heights = new Float32Array(size * size);
    for (let i = 0; i < heights.length; i++) {
      const value = source.getFloat32(i * 4, true);
      if (!Number.isFinite(value)) throw new Error("The Jezero elevation tile has missing heights");
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
        const buffer = cache.get(key); cache.delete(key); cache.set(key, buffer);
        return Promise.resolve().then(() => terrainData(buffer, x, y, level));
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
          cache.set(key, buffer);
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
