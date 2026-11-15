const assert = require('node:assert/strict');
const { marsPointVisible: visible } = require('../../frontend/mars_visibility.js');
const sphere = {x:1,y:1,z:1}, camera={x:3,y:0,z:0};
assert(visible(camera,{x:1,y:0,z:0},sphere));
assert(!visible(camera,{x:-1,y:0,z:0},sphere));
assert(!visible(camera,{x:0,y:1,z:0},sphere));
assert(visible(camera,{x:0.5,y:Math.sqrt(0.75),z:0},sphere));
assert(!visible(camera,{x:0.2,y:Math.sqrt(0.96),z:0},sphere));
assert(!visible(camera,{x:-4,y:0,z:0},sphere)); // a moon behind the planet
assert(visible(camera,{x:0,y:4,z:0},sphere));
assert(visible({x:.999,y:0,z:0},{x:1,y:0,z:0},sphere)); // crater below reference level
assert(!visible({x:.999,y:0,z:0},{x:-1,y:0,z:0},sphere));
// Equator/pole symmetry in a non-spherical ellipsoid, including high orbit.
for (const axis of ['x','y','z']) {
  const radii={x:3396190,y:3396190,z:3376200};
  const c={x:0,y:0,z:0}, near={x:0,y:0,z:0}, far={x:0,y:0,z:0};
  c[axis]=radii[axis]*20; near[axis]=radii[axis]; far[axis]=-radii[axis];
  assert(visible(c,near,radii)); assert(!visible(c,far,radii));
}
console.log('PASS surface horizon, far-side satellites, below-datum camera, oblate poles and distant camera');
