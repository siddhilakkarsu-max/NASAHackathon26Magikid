"use strict";

// Segment/ellipsoid intersection, independent of terrain depth mode. Endpoints
// on the near surface are visible; an earlier intersection hides the far side.
function marsPointVisible(camera, point, radii, margin = 0) {
  const axes = ['x', 'y', 'z'];
  let cc = 0, pp = 0, cp = 0;
  for (const axis of axes) {
    const radius = radii[axis] - margin;
    if (!(radius > 0) || !Number.isFinite(camera[axis]) || !Number.isFinite(point[axis])) return false;
    const c = camera[axis] / radius, p = point[axis] / radius;
    cc += c * c; pp += p * p; cp += c * p;
  }
  // A terrain camera can be below the zero-height reference ellipsoid. Retain
  // its local hemisphere; normal terrain depth testing handles nearby hills.
  if (cc <= 1 + 1e-10) return cp > 0;
  const a = cc + pp - 2 * cp;
  if (a < 1e-20) return true;
  const b = cp - cc, discriminant = b * b - a * (cc - 1);
  if (discriminant <= 0) return true;
  const entry = (-b - Math.sqrt(discriminant)) / a;
  return !(entry >= 0 && entry < 1 - 1e-7);
}

function marsSurfaceLabelVisibility(viewer, ellipsoid, position) {
  return new Cesium.CallbackProperty(() =>
    marsPointVisible(viewer.camera.positionWC, position, ellipsoid.radii), false);
}

if (typeof module !== 'undefined' && module.exports) module.exports = { marsPointVisible };
