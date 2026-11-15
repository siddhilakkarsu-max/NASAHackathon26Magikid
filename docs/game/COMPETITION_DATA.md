# Competition terrain and surface-property data

The competition uses a **6.4 × 6.4 km** mission area around Jezero's western delta.
Every elevation sample comes from the **20 m USGS CTX science-investigation DEM**.
The portable crop is under 1 MB and runs without the 86 MiB original download.
No terrain is synthesized, hole-filled, exaggerated, or blended with another DEM.

## Elevation and coordinates

[USGS product catalogue](https://astrogeology.usgs.gov/search/map/mars_2020_science_investigation_ctx_dem_mosaic)
identifies Fred Calef's 2021 stereo CTX mosaic, its 20 m sampling, and vertical
control to MOLA. The
[USGS image description](https://www.usgs.gov/media/images/jezero-crater-0)
also describes its origin and marks it public domain. The original file is
available from the [USGS planetary map archive](https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/ScienceInvestigationMaps_JPL/M20_JezeroCrater_CTXDEM_20m.tif).
These sources and local raster metadata were checked on 2026-11-15.

The crop is native source rows 2309–2629 and columns 985–1305, inclusive and
zero-based. Its **321 × 321 nodes** span 6400 m between the outer sample centres.
Array rows run north to south; columns run west to east. Local x increases east
and local y increases north, with (0,0) at the southwestern sample centre.

| Coordinate property | Value |
| --- | --- |
| Planetocentric longitude bounds, east-positive | 77.3480075129° to 77.4618406377° |
| Planetocentric latitude bounds | 18.4029618974° to 18.5109337685° |
| Local metric bounds | x: 0–6400 m; y: 0–6400 m |
| Projection | Source equirectangular, standard parallel 18.4663°, central meridian 0° |
| Source sphere radius | 3,396,190 m |
| Elevation units/reference | Metres, source elevations controlled vertically to MOLA |
| Elevation sampling | 20 m; bilinear interpolation within supported cells |

The source GeoTIFF's radius is retained exactly. The catalogue separately lists
3,396,160 m; using the raster's own projection avoids introducing a coordinate
shift. The manifest records the complete source WKT and the projected origin.
Within this small crop, source-projection east-west scale varies by less than
0.04%. The mission boundary is a game boundary, not a physical wall on Mars.

Slope is `atan(hypot(dz/dx, dz/dy))` in degrees, calculated by centred differences
at native 20 m spacing. Each derivative spans 40 m. A full 3 × 3 measured stencil
must be valid. The builder reads one extra pixel around the crop before
differentiating, so crop-edge slopes have real support. A 20 m DEM cannot
represent small rocks, rover-scale ledges, or soil bearing strength.

## Surface-material estimate: thermal inertia

The layer is explicitly a **surface-material estimate (thermal inertia)** in
**J m⁻² K⁻¹ s⁻¹ᐟ²**. It estimates resistance to temperature change. It does not
measure firmness, traction, bearing strength, individual rocks, or safe driving.
The competition uses elevation-derived grade and slope for route calculations;
thermal inertia supplies context rather than a traction multiplier.

The input is the repository's documented `thermal_data/tes_detail_8ppd.npz`
derivative of the
[NASA PDS TES thermal inertia archive](https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html),
dataset **MGS-M-TES-5-TIMAP-V1.0**. The
[NASA PDS dataset description](https://pds.nasa.gov/ds-view/pds/viewProfile.jsp?dsid=MGS-M-TES-5-TIMAP-V1.0)
documents the original 20-pixels-per-degree products and interpolation masks.
The original apparent-inertia product uses observations from 1999–2004.

The bundled derivative has **0.125° cells**, about **7.4 km north-south and
7.0 km east-west** here, after area-weighted reduction from the source 0.05°
grid. Published source masks excluded archive-interpolated cells. Nightside
estimates are preferred; dayside estimates fill cells only when nightside
estimates are unavailable. See `thermal_data/tes_detail_8ppd.SOURCE.md` for the
upstream product hashes and reduction procedure. A derivative cell can summarize
a partially observed source footprint; it does not imply complete fine-scale
observations throughout that cell.

Only four coarse derivative cells intersect the mission area: **284.9, 289.3,
316.4 and 323.2** in the stated units. Those decimal places are storage rounding,
not a claim of measurement accuracy. No material categories or fine-scale texture
are generated. The layer keeps constant cell values and their true geographic
boundaries. The aligned display raster repeats the coarse cell value; its 20 m
spacing does **not** improve thermal resolution. Missing thermal cells become
NaN internally and `null` in JSON, with a separate validity mask. They remain
unknown and do not invalidate otherwise measured elevation.

## Portable artifact, integrity, and rebuilding

`data/competition/manifest.json` records source URLs, the verified original DEM
SHA-256, the input TES derivative SHA-256, processing, coordinate bounds,
resolution, masks, native source window, and the crop SHA-256.
`data/competition/jezero_west_delta_20m.npz` holds elevation, slope, thermal
inertia and their aligned validity masks. It contains no Python object arrays.

The runtime verifies the crop checksum before loading, then validates the native
source transform, crop window, origin, projection WKT, and geographic bounds.
Its `dataset_sha256` also binds coordinate units, axis order, resolution,
projection, source provenance, slope stencil and thermal cell interpretation to
the artifact bytes. Editorial descriptions and retrieval dates are excluded.
The separate `artifact_sha256` is the ordinary file checksum.
If the artifact or
manifest is missing, incompatible, or corrupt, it raises `TerrainUnavailable`;
no synthetic or lower-resolution fallback starts the competition. Normal
requests perform no downloads. The dataset version and hash must accompany
competition results so incompatible terrain cannot share a leaderboard.

To rebuild from the existing verified source:

```powershell
.venv\Scripts\python.exe jezero_terrain.py --download
.venv\Scripts\python.exe tools/build_competition_terrain.py
.venv\Scripts\python.exe -m pytest tests/test_competition_terrain.py
```

The first command installs the large original only if needed. The builder
rejects an unexpected source checksum. If the optional thermal derivative is
absent, its layer stays entirely unknown, with that absence recorded in the
manifest. Rebuilding with different layers changes the artifact hash.

Because this repository ignores its general `data/` download directory, keep
the two portable competition files explicitly tracked when committing:

```powershell
git add -f data/competition/manifest.json data/competition/jezero_west_delta_20m.npz
```

## Python contract and route validity

`competition_terrain.load_terrain()` returns `Terrain` or raises
`TerrainUnavailable`. `sample(x,y)` returns bilinear elevation and slope with
the containing coarse thermal cell's value (or `None`). `local_to_geo` returns
longitude/latitude; `geo_to_local` returns x/y. `metadata()` includes provenance,
boundary, projection and dataset identity. `public_grid(step=2)` provides a
161 × 161 JSON-safe display grid at 40 m spacing; the authoritative grid stays
at 20 m. Row zero is always north.

`valid_point` and `segment_is_valid` require all corners of every touched
interpolation cell to contain measured elevation and slope. Segment checks split
at every grid crossing, including corner contacts and both sides of a shared
edge. This prevents a long route segment from jumping over a missing-data or
forbidden-slope cell. An optional `max_slope_degrees` checks every touched node,
not just segment endpoints. The current crop happens to have complete measured
coverage; tests exercise missing-data rejection explicitly.

The manifest's suggested game survey route is about 724 m long, on a connected
measured part of the crater floor near the delta. Its points are game objectives,
not claims of mineral discoveries or actual mission hardware locations. Every
reference segment satisfies a 25° slope ceiling.
