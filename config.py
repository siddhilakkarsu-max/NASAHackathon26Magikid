"""
Settings for the Mars data cube.

Every region uses the SAME code. Jezero is just a small, high-res box;
"global" is the whole planet at low res. Add more regions (Gale, a landing site)
by adding a line to REGIONS.
"""

MARS_RADIUS_M = 3396190.0  # IAU Mars sphere radius used by MOLA/USGS products

# Lat/lon on the Mars sphere. All bands are resampled onto this grid.
MARS_LONLAT_CRS = "+proj=longlat +R=3396190 +no_defs"

# px_per_deg: grid density.  256 px/deg ~ 230 m/px at the equator.
#                             16  px/deg ~ 3.7 km/px (global tier).
REGIONS = {
    # Whole Jezero crater at ~29 m/px (CTX elevation + CTX image)
    "jezero": dict(west=77.0, east=78.0, south=18.0, north=18.8, px_per_deg=2048),
    # HiRISE close-up of the landing site + delta at ~10 m/px (HiRISE 1 m elevation, resampled)
    "jezero_hirise": dict(west=77.25, east=77.55, south=18.35, north=18.65, px_per_deg=6144),
    "gale":   dict(west=137.0, east=138.0, south=-5.2, north=-4.2, px_per_deg=256),
    "global": dict(west=-180.0, east=180.0, south=-90.0, north=90.0, px_per_deg=16),
}

# ---------------------------------------------------------------------------
# DATA SOURCES (one entry per band). Three kinds are supported:
#   {"kind": "file", "path": "..."}             a GeoTIFF you downloaded (most reliable)
#   {"kind": "cog",  "url":  "..."}             a remote GeoTIFF; only the needed window is read
#   {"kind": "wms",  "server": "...", "layer": "..."}  a USGS WMS layer
# The builder tries each source in the list in order and uses the first that works.
# Set a "file" path once you have downloaded something -> it wins.
# ---------------------------------------------------------------------------
USGS_WMS = "https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl.map"
USGS_WMS_ELEV = "https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl_elev.map"

SOURCES = {
    # Elevation in meters (MOLA / MOLA-HRSC blend). REQUIRED: slope etc. are derived from it.
    "elevation": [
        # {"kind": "file", "path": "data/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif"},
        {"kind": "cog", "url": "https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif"},
        {"kind": "wms", "server": USGS_WMS_ELEV, "layer": "MOLA_elev", "match": ["mola"], "format": "image/tiff"},
    ],
    # THEMIS night-time IR brightness. Warm at night = high thermal inertia = rock/firm ground.
    # Cold at night = low thermal inertia = loose dust/sand (Spirit's trap). Used as a firmness proxy
    # until a calibrated thermal-inertia map is swapped in.
    "themis_night": [
        # {"kind": "file", "path": "data/THEMIS_night_jezero.tif"},
        {"kind": "wms", "server": USGS_WMS, "layer": "THEMIS_night", "match": ["themis", "night"], "format": "image/png"},
    ],
    # THEMIS day IR (optional, for display / temperature work)
    "themis_day": [
        {"kind": "wms", "server": USGS_WMS, "layer": "THEMIS", "match": ["themis"], "format": "image/png"},
    ],
    # Add more as the team finds them, e.g.:
    # "albedo":   [{"kind": "file", "path": "data/TES_albedo.tif"}],
    # "dust":     [{"kind": "file", "path": "data/TES_dust_cover_index.tif"}],
    # "minerals": [{"kind": "file", "path": "data/CRISM_jezero_clays.tif"}],
    # "hydrogen": [{"kind": "file", "path": "data/MONS_WEH.tif"}],
}

# ---------------------------------------------------------------------------
# Region-specific sources: these are tried BEFORE the global ones above.
# Official USGS products made for Perseverance's landing (Mars 2020 TRN).
# Download big ones into data/ for speed; the builder uses a local file if it exists.
# ---------------------------------------------------------------------------
M20 = "https://planetarymaps.usgs.gov/mosaic/mars2020_trn"
CTX_DEM = {"kind": "cog", "url": f"{M20}/CTX/ScienceInvestigationMaps_JPL/M20_JezeroCrater_CTXDEM_20m.tif"}  # 87 MB, whole crater
CTX_IMG = {"kind": "cog", "url": f"{M20}/CTX/JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0.tif"}          # 35 MB
HIRISE_DEM_FILE = {"kind": "file", "path": "data/JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif"}  # 1.8 GB
CTX_DEM_FILE = {"kind": "file", "path": "data/M20_JezeroCrater_CTXDEM_20m.tif"}
CTX_IMG_FILE = {"kind": "file", "path": "data/JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0.tif"}

REGION_SOURCES = {
    "jezero": {
        "elevation": [CTX_DEM_FILE, CTX_DEM],
        "imagery":   [CTX_IMG_FILE, CTX_IMG],
    },
    "jezero_hirise": {
        "elevation": [HIRISE_DEM_FILE, CTX_DEM_FILE, CTX_DEM],
        "imagery":   [CTX_IMG_FILE, CTX_IMG],
    },
}

# Hand-placed science targets per region (replace with Siddhi's CRISM-based picks).
# Coordinates are approximate and for the demo only.
_JEZERO_TARGETS = [
        {"name": "Perseverance landing site (Octavia E. Butler)", "lat": 18.4447, "lon": 77.4508},
        {"name": "Western delta front (approx.)", "lat": 18.50, "lon": 77.40},
]
SCIENCE_TARGETS = {"jezero": _JEZERO_TARGETS, "jezero_hirise": _JEZERO_TARGETS}

# Approximate places for the text target search ("valley with clay") when the cube has NO band for
# that material yet. Each zone is a circle; "tags" are the search words that select it.
# For pixel-level results, add a mineral map band named after the mineral (e.g. a CRISM clay map
# as "clay" in SOURCES) - the search uses a band of that name first and ignores these zones.
_JEZERO_ZONES = [
    {"name": "Western fan delta", "tags": ["delta", "clay"], "lat": 18.50, "lon": 77.40, "radius_km": 5.0,
     "source": "Fe/Mg smectite clays seen by CRISM in the delta (Ehlmann et al. 2008); outline approximate"},
]
SEARCH_ZONES = {"jezero": _JEZERO_ZONES, "jezero_hirise": _JEZERO_ZONES}

# Vehicle / walker profiles. Weights are tunable during the demo.
VEHICLES = {
    "astronaut": dict(label="Astronaut on foot (suited)", max_slope=18.0, base_speed_kmh=6.0,
                      suit_factor=0.5, sand_penalty=1.5, rough_penalty=1.0, uses_slip_table=False),
    "pressurized_rover": dict(label="Pressurized crew rover", max_slope=20.0, base_speed_kmh=10.0,
                              suit_factor=1.0, sand_penalty=3.0, rough_penalty=2.0, uses_slip_table=True),
    "small_rover": dict(label="Robotic rover (Curiosity-class)", max_slope=25.0, base_speed_kmh=0.15,
                        suit_factor=1.0, sand_penalty=4.0, rough_penalty=2.0, uses_slip_table=True),
}
