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
# DATA SOURCES (one entry per band). These kinds are supported:
#   {"kind": "file", "path": "..."}             a GeoTIFF you downloaded (most reliable)
#   {"kind": "cog",  "url":  "..."}             a remote GeoTIFF; only the needed window is read
#   {"kind": "download", "url": "...", "path": "data/..."}  fetched once into data/, then read as a file
#   {"kind": "wms",  "server": "...", "layer": "..."}  a USGS WMS layer
#   {"kind": "crism"}                           CRISM mineral maps, found automatically (see MINERALS)
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
    # THEMIS night-time IR brightness (100 m picture, not calibrated). Warm at night = rock, cold = loose
    # sand/dust. Gives sub-km detail to "firmness"; the absolute level comes from thermal_inertia.
    "themis_night": [
        # {"kind": "file", "path": "data/THEMIS_night_jezero.tif"},
        {"kind": "wms", "server": USGS_WMS, "layer": "THEMIS_night", "match": ["themis", "night"], "format": "image/png"},
    ],
    # THEMIS day IR (optional, for display / temperature work)
    "themis_day": [
        {"kind": "wms", "server": USGS_WMS, "layer": "THEMIS", "match": ["themis"], "format": "image/png"},
    ],
    # CRISM (MRO) mineral maps -> one band per entry in MINERALS below. The builder asks NASA's Orbital
    # Data Explorer for every CRISM product over the region: targeted observations (MTRDR, ~18-36 m)
    # first, the multispectral mapping tile (MRDR, ~180 m) fills the gaps. Skipped for huge regions.
    "minerals": [{"kind": "crism"}],
    # Add more as the team finds them, e.g.:
    # "albedo":   [{"kind": "file", "path": "data/TES_albedo.tif"}],
    # "dust":     [{"kind": "file", "path": "data/TES_dust_cover_index.tif"}],
    # "hydrogen": [{"kind": "file", "path": "data/MONS_WEH.tif"}],
}

# THEMIS thermal inertia (J m^-2 K^-1 s^-1/2), Huang 2026, 1 km browse version, one GeoTIFF per Mars Chart
# quadrangle (35S-45N): https://zenodo.org/records/23527756 (CC BY 4.0). The full 100 m product is at
# Science Data Bank (scidb.cn). Use: <150 fine dust, 150-300 sand, 300-600 coarse/crusted, >600 bedrock.
def themis_ti(mc):
    name = f"THEMIS_TI_2026_MC{mc:02d}_ti_1km.tif"
    return {"kind": "download", "url": f"https://zenodo.org/records/23527756/files/{name}?download=1",
            "path": f"data/{name}"}


# ---------------------------------------------------------------------------
# MINERALS from CRISM spectral summary parameters (Viviano-Beck et al. 2014, JGR Planets 119, 1403).
# Each mineral band in the cube = the strongest of its CRISM parameters (a band depth, no unit).
# detect: below this, treat as no detection (noise); strong: a clear, strong signature.
# Thresholds are for ~100 m cube pixels: averaging 18 m CRISM pixels lowers band depths, so they sit below
# full-resolution values. Checked at Jezero against published maps (Ehlmann 2008, Goudge 2015, Horgan 2020):
# clays NW of the crater and on the delta, carbonates on the inner NW margin and floor, olivine near Seitah.
# The text search ("clay", "carbonate near base", ...), map layers and pixel panel all use this table;
# add a mineral here and rebuild the cube.
# ---------------------------------------------------------------------------
MINERALS = {
    "clay": dict(label="Fe/Mg clay (smectite)", params=["D2300"], detect=0.010, strong=0.020, words=[
        "clay", "clays", "smectite", "phyllosilicate", "nontronite", "saponite", "clay minerals", "mud",
        "mudstone", "clay rich"]),
    "carbonate": dict(label="carbonate", params=["MIN2295_2480", "MIN2345_2537"], detect=0.002, strong=0.006,
                      words=["carbonate", "magnesite", "siderite", "calcite"]),
    "olivine": dict(label="olivine", params=["OLINDEX3"], detect=0.12, strong=0.16, words=[
        "olivine", "forsterite", "ultramafic"]),
    "pyroxene": dict(label="pyroxene", params=["LCPINDEX2", "HCPINDEX2"], detect=0.010, strong=0.020, words=[
        "pyroxene", "augite", "pigeonite", "basaltic"]),
    "sulfate": dict(label="sulfate", params=["SINDEX2"], detect=0.010, strong=0.020, words=[
        "sulfate", "sulphate", "gypsum", "jarosite"]),
    "hydrated_silica": dict(label="hydrated silica (opal)", params=["MIN2250"], detect=0.005, strong=0.010,
                            words=["hydrated silica", "opal", "opaline", "silica"]),
    "hydrated": dict(label="water-bearing minerals", params=["BD1900_2"], detect=0.008, strong=0.015, words=[
        "hydrated", "hydrated minerals", "water bearing", "water bearing minerals", "water", "h2o", "aqueous", "wet"]),
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
        "thermal_inertia": [themis_ti(13)],          # MC-13 Syrtis Major
    },
    "jezero_hirise": {
        "elevation": [HIRISE_DEM_FILE, CTX_DEM_FILE, CTX_DEM],
        "imagery":   [CTX_IMG_FILE, CTX_IMG],
        "thermal_inertia": [themis_ti(13)],
    },
    "gale": {
        "thermal_inertia": [themis_ti(23)],          # MC-23 Aeolis
    },
}

# Hand-placed science targets per region (replace with Siddhi's CRISM-based picks).
# Coordinates are approximate and for the demo only.
_JEZERO_TARGETS = [
        {"name": "Perseverance landing site (Octavia E. Butler)", "lat": 18.4447, "lon": 77.4508},
        {"name": "Western delta front (approx.)", "lat": 18.50, "lon": 77.40},
]
SCIENCE_TARGETS = {"jezero": _JEZERO_TARGETS, "jezero_hirise": _JEZERO_TARGETS}

# Approximate places for the text target search when the cube has NO band for that material (e.g. a
# region without CRISM coverage). Each zone is a circle; "tags" are the search words that select it.
# A cube band of the same name (built from CRISM, see MINERALS) always wins over these zones.
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


# ===========================================================================
# MISSION PLANNER (mission.py). Every number below is a first-order assumption for the demo:
# tune freely, and say "approximate" if judges ask.
# ===========================================================================

# Real rover traverses (NASA/JPL mission maps), fetched with: python fetch_tracks.py <region>
ROVER_TRACKS = {
    "jezero": {"rover": "Perseverance",
               "traverse": "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_traverse.json",
               "waypoints": "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json"},
}
TRACK_RULES = dict(
    yellow_tilt_deg=12.0,     # rover tilt recorded at a waypoint: a hard, power-hungry drive
    yellow_slope_deg=12.0,    # or terrain this steep under the segment (cube slope)
    yellow_ti=200.0,          # or loose ground under it (thermal inertia below this)
    green_factor=0.7,         # route cost x0.7 on green, rover-verified track
    yellow_factor=1.5,        # route cost x1.5 on yellow, high-strain track
)

# Vehicles. max_slope / range_km are hard limits. Suited crews (on foot, open rovers) are also limited by
# suit oxygen: o2_kg per EVA (~8 h), used at o2_walk_kg_h walking at ~250 W or o2_ride_kg_h riding.
# Battery vehicles: battery_wh, wh_per_km on flat firm ground, hotel_w for computers/heaters/radios.
MISSION_VEHICLES = {
    "on_foot": dict(label="On foot (suited astronaut)", max_slope=15.0, range_km=2.0, base_speed_kmh=6.0,
                    suit_factor=0.5, sand_penalty=1.5, rough_penalty=1.0, uses_slip_table=False,
                    mass_kg=170, suited=True, battery_wh=None),
    "two_wheel": dict(label="2-wheel scout bike", max_slope=15.0, range_km=15.0, base_speed_kmh=8.0,
                      suit_factor=1.0, sand_penalty=3.5, rough_penalty=2.5, uses_slip_table=True,
                      mass_kg=250, suited=True, battery_wh=2500, wh_per_km=60, hotel_w=30),
    "four_wheel": dict(label="4-wheel open rover (LRV-class)", max_slope=20.0, range_km=30.0, base_speed_kmh=10.0,
                       suit_factor=1.0, sand_penalty=2.5, rough_penalty=2.0, uses_slip_table=True,
                       mass_kg=550, suited=True, battery_wh=12000, wh_per_km=150, hotel_w=100),
    "buggy": dict(label="Pressurized buggy (6-wheel)", max_slope=20.0, range_km=100.0, base_speed_kmh=12.0,
                  suit_factor=1.0, sand_penalty=2.0, rough_penalty=1.5, uses_slip_table=True,
                  mass_kg=3000, suited=False, battery_wh=90000, wh_per_km=600, hotel_w=1500),
}
SUIT = dict(o2_kg=1.2, o2_walk_kg_h=0.075, o2_ride_kg_h=0.05, o2_site_kg_h=0.06)   # ~8 h EVA
SITE_HOURS = 1.0           # time spent sampling at the destination

# Mission season -> Mars solar longitude and dust risk (global/regional storms mostly start Ls 180-330).
# dust_risk raises route cost, energy use (dimmer sun, dusty panels) and the reserve.
SEASONS = {
    "northern_spring": dict(label="Northern spring (Ls 0-90)", ls=45, dust_risk=0.10),
    "northern_summer": dict(label="Northern summer (Ls 90-180)", ls=135, dust_risk=0.10),
    "northern_autumn": dict(label="Northern autumn (Ls 180-270): dust-storm season", ls=225, dust_risk=0.50),
    "northern_winter": dict(label="Northern winter (Ls 270-360): dust-storm season", ls=315, dust_risk=0.35),
}

# Priority: how the route cost map weighs time, energy/oxygen and terrain risk, and which decision-matrix
# criterion gets +10 points (the rest are scaled down so weights still sum to 100).
PRIORITIES = {
    "safety": dict(label="Safety", cost=dict(time=1.0, energy=1.0, risk=3.0), boost="safety", reserve=0.20),
    "speed": dict(label="Speed", cost=dict(time=3.0, energy=1.0, risk=1.0), boost="time", reserve=0.15),
    "energy": dict(label="Energy", cost=dict(time=1.0, energy=3.0, risk=1.0), boost="resources", reserve=0.15),
}
MATRIX_CRITERIA = {   # key: (label, default weight %)
    "science": ("Science value at B", 25),
    "safety": ("Route safety (slope, slip, hazards)", 20),
    "resources": ("Resource use (oxygen or energy, reserve left)", 15),
    "green": ("Share of the route on green, rover-verified track", 15),
    "time": ("Travel time and distance", 10),
    "landing": ("Landing spot quality", 10),
    "confidence": ("Data confidence", 5),
}

# Equipment. "for": goal features that call for it (see search.FEATURES); "*" = any goal.
TOOLS = [
    dict(name="Handheld spectrometer (VNIR / Raman)", kg=3.0, w=15, for_=["clay", "carbonate", "olivine", "pyroxene",
         "sulfate", "hydrated_silica", "hydrated", "any_mineral", "delta"]),
    dict(name="Core drill (1 m)", kg=12.0, w=300, for_=["clay", "carbonate", "sulfate", "hydrated_silica", "hydrated",
         "ice", "delta"]),
    dict(name="Sample tubes + sealing kit (x10)", kg=2.5, w=0, for_=["clay", "carbonate", "olivine", "pyroxene",
         "sulfate", "hydrated_silica", "hydrated", "any_mineral", "delta"]),
    dict(name="Ground-penetrating radar", kg=8.0, w=40, for_=["ice", "hydrated"]),
    dict(name="Neutron spectrometer (hydrogen / water)", kg=5.0, w=10, for_=["ice", "hydrated"]),
    dict(name="Rock hammer + scoop", kg=2.0, w=0, for_=["olivine", "pyroxene", "rough", "firm", "sand"]),
    dict(name="Multispectral context camera", kg=1.5, w=10, for_=["*"]),
]
ESSENTIALS = [
    dict(name="Oxygen (suit tanks + 30 min emergency bottle)", kg=6.0, w=0),
    dict(name="Battery pack (instruments, 1 kWh)", kg=7.0, w=0),
    dict(name="Radio relay", kg=4.0, w=20),
    dict(name="Repair kit (wheel, suit, tools)", kg=6.0, w=0),
]

# Landing rules for a safe touchdown spot A (checked over a circle of area_radius_m around the spot).
LANDING_RULES = dict(max_slope_deg=5.0, max_rough_percentile=60, min_ti=200.0, max_elevation_m=-500.0,
                     max_abs_lat=50.0, area_radius_m=500.0)

# NASA's known sites per region. Spots inside a landing site / landing ellipse are "NASA candidate";
# exploration zones are shown on the detail card for context.
NASA_SITES = {
    "jezero": [
        dict(name="Perseverance landing site (Octavia E. Butler Landing, 2021)", kind="past landing site",
             lat=18.4447, lon=77.4508, radius_km=0.6),
        dict(name="Mars 2020 landing ellipse (7.7 x 6.6 km; approx., centred on the landing site)",
             kind="landing ellipse", lat=18.4447, lon=77.4508, radius_km=3.5),
        dict(name="Jezero Human Exploration Zone (2015 NASA workshop; USGS CTX EZ mosaic)", kind="exploration zone",
             bounds=[75.154, 15.906, 78.872, 19.445]),
    ],
}

# COSPAR planetary-protection Special Regions (where liquid water or Earth microbes might survive, e.g.
# recurring slope lineae, gullies, shallow ice). None are known inside the current regions; add circles as
# dict(name=..., lat=..., lon=..., radius_km=..., source=...).
SPECIAL_REGIONS = {"jezero": [], "jezero_hirise": [], "gale": []}
