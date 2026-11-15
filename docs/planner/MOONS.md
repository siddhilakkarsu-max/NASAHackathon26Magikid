# Phobos and Deimos

Open **Time → Phobos & Deimos**. **Mars and moons** frames the whole system;
**View Phobos** and **View Deimos** follow the individual bodies. Choosing a
region or another map releases moon tracking. The opening overview selects
3,600× (one simulated hour per real second). The explicit 1×, 60×, 600× and
3,600× controls set the moon clock; **Paused** freezes it.
**Now** restores current UTC and real-time speed.

Moon time is a separate UTC clock. The planner's local solar time and season
are scenarios without a unique Earth date/year; changing them must not silently
invent a new absolute orbital phase. During the opening overview, surface
lighting uses the Sun position on this same UTC clock. Leaving the overview
for planning restores lighting from the planning settings.

## Opening overview

**Start exploring** opens the planner's own Viking imagery with no weather or
terrain overlay and automatically plays the system at 3,600×. The view fits
both physical moon orbits; moons are very small at this distance, so locator
dots identify them. **Pause motion** freezes the UTC clock and camera. Dragging
or scrolling also pauses it. **Play overview** returns to the planner background
and resumes the animation. Existing region, map, moon-following, tour and
planning controls take priority over the automatic view.

The camera circles Mars by half the changing subsolar longitude, showing
surface rotation, moon motion and the Sun moving through the sky. This is a
presentation camera, not a claimed spacecraft orbit or an inertial observer.
The physical moon and Sun vectors are not moved to fit the picture. The Sun
marker is illustrative and is hidden behind Mars or outside the camera's view.
Its direction and distance come from the DE440 Sun states bundled in MAR099s,
using the same geometric Mars-centered frame and UTC epochs as the moons.
The initial camera latitude follows the seasonal Sun plane so a fixed tilt
does not accidentally keep the Sun off-screen for the whole animation.

The overview does not advance mission/weather season or solar-time inputs.
It pauses on source failure and offers retry rather than showing invented
positions. The next UTC day is prefetched for fast playback. Hidden tabs
suspend the overview clock; returning does not jump forward through hidden
time. A reduced-motion preference starts paused and can be overridden with
the explicit Play button. Explicit terrain and layer links keep their selected
view. Late regional metadata never replaces the default whole-system view
with an unsolicited Jezero flight.

## Positions, timing and scale

- [JPL MAR099 short ephemeris](https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/mar099s.cmt)
  supplies Phobos (401), Deimos (402) and Mars (499). The short file covers
  1995–2050; the UI admits full UTC dates from 1995-01-02 through 2049-12-30.
- [NAIF SPICE state vectors](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/spkezr_c.html)
  are geometric (`NONE` aberration correction), Mars-centered, and expressed in
  the rotating `IAU_MARS` frame using `pck00011.tpc`. Both position and velocity
  are transformed, including frame rotation. Kilometres and km/s become metres
  and m/s for Cesium. There is no invented circular-orbit fallback.
- The server samples every 300 TDB seconds, with exact UTC day endpoints. UTC
  timestamps are converted using the pinned `naif0012.tls` leap-second kernel.
  The browser uses Cesium JulianDate (TAI elapsed time) and cubic Hermite position
  interpolation with the supplied velocities. It never extrapolates outside
  the returned interval; a missing day hides the moons and offers retry.
- This is a Mars-fixed view. Both inertial orbits are prograde, but their motion
  relative to the rotating surface differs: Phobos overtakes Mars's rotation;
  Deimos falls behind it. Do not replace this with two identical spinning rings.
- Models use a scale of 1000 metres per source coordinate unit, consistent with
  the NASA assets' kilometre-sized meshes. Terrain height exaggeration is
  explicitly disabled on the moon models. Small dots and names are locator
  aids, not representations of body diameters. Their positions are not displaced.

## NASA images and models

The original textured glTF assets are bundled without recoloring or geometry
changes. Credit: **NASA/JPL-Caltech**.

- [Phobos model and download](https://science.nasa.gov/resource/phobos-mars-moon-3d-model/)
- [Deimos model and download](https://science.nasa.gov/resource/deimos-mars-moon-3d-model/)

These are NASA visualization textures, not a claim of calibrated natural-color
photometry. An unlit material preserves the supplied colors independently of
the user's daylight scenario. Moon phases, eclipses and photometric illumination
are not modeled. Body orientations use the IAU rotational models with approximate
mesh-axis alignment; the model is not suitable for feature-level pointing.

`moon_sources.json` records the original URLs, byte counts and SHA-256 hashes of
both assets and all three kernels. The 64.5 MiB satellite kernel and small text
kernels download on first use to ignored `data/moons/`. Downloads are verified
and atomically installed; partial or changed files are rejected. A single lock
protects CSPICE's global state and cold requests; only four daily tables remain
in the backend cache and three in the browser. Install `requirements.txt` on
other machines to obtain SpiceyPy. The rest of the app remains usable if moon
data cannot load. Future announced leap seconds require updating the pinned
time kernel and its manifest.

## Place-label visibility

Murray place, crater and photo-grid labels use a camera-to-label segment test
against Mars's oblate reference ellipsoid on every rendered frame, in addition
to normal depth testing. They do not wait for the camera's move-end event and
do not depend on the selected map enabling terrain depth tests. A camera below
the reference ellipsoid retains its local hemisphere; actual terrain depth
testing handles foreground relief. Moon locators use the same horizon check;
model culling retains partially occulted bodies using a conservative radius.

## Checks and limits

`tests/test_mars_moons.py` covers rejected dates, download integrity, source
failure, coordinate units/frame transformation, leap seconds, supported date
edges, relative orbital motion, and intermediate-time interpolation. Numerical
tests require the downloaded kernels; the tests do not fetch them automatically.

The independent Horizons reference fixture contains Mars-centered geometric
ICRF states at 2026-11-15 12:00 UTC/UT. Direct SPICE positions differed by about
0.045 m (Phobos) and 0.029 m (Deimos) in that comparison. This checks our setup,
not the physical accuracy of the ephemeris. Interpolation is checked against
direct SPICE at intermediate times; browser checks found a largest departure
of 0.146 m across the three recorded test timestamps.

With the app running on port 8001:

```sh
python -m pytest tests/test_mars_moons.py -q
node docs/planner/mars_visibility_test.cjs
node docs/planner/moons_browser_test.mjs
node docs/planner/overview_browser_test.mjs
```

The browser audit checks actual NASA model rendering, physical scale, following
and releasing a moon, horizon occlusion during rotation, accelerated/paused
time, delayed responses and unavailable data. Failures/delays are explicit test
fixtures, not substituted scientific data. Reports and screenshots use
`MARSWALK_AUDIT_DIR`; see the planner README for Playwright/Chrome settings.
The overview audit additionally checks synchronized Sun direction, entry map,
pause/resume, delayed metadata, midnight, source failure/retry, hidden tabs,
reduced motion, portrait layout and preserved terrain links. Sun interpolation
is checked against direct SPICE direction; microsecond-rounded API timestamps
do not imply metre-level solar ranging accuracy.
