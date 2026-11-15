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
    "global": dict(west=-180.0, east=180.0, south=-90.0, north=90.0, px_per_deg=16),
}

# ---------------------------------------------------------------------------
# PLANNING ANYWHERE ELSE. Any other place is a square SITE_SIZE_DEG box built on demand from global data
# (HRSC-MOLA 200 m elevation, THEMIS, TES albedo, THEMIS thermal inertia, CRISM): pick a named site below or
# click the globe. A spot's region id is "site_<lat>_<lon>" (e.g. site_-4.59_137.44), so the builder and the
# server can rebuild it from the name alone:  python build_cube.py gale   /   python build_cube.py site_-4.59_137.44
# ---------------------------------------------------------------------------
SITE_SIZE_DEG = 0.8          # ~47 km across at the equator: room for a 100 km buggy round trip
SITE_PX_PER_DEG = 512        # ~115 m/px, the scale the mineral thresholds and landing rules were tuned at
# Named places. lat/lon (east-positive) is the box centre; "landed" marks a real landing site (a NASA
# candidate spot for the landing check). Coordinates from NASA/JPL mission pages; ~0.01 deg.
SITES = {
    "gale": dict(label="Gale crater (Curiosity)", lat=-4.5895, lon=137.4417, landed="Curiosity (Bradbury Landing, 2012)"),
    "gusev": dict(label="Gusev crater (Spirit)", lat=-14.5684, lon=175.4726, landed="Spirit (Columbia Memorial Station, 2004)"),
    "meridiani": dict(label="Meridiani Planum (Opportunity)", lat=-1.9462, lon=-5.5266, landed="Opportunity (Eagle crater, 2004)"),
    "utopia": dict(label="Utopia Planitia (Zhurong)", lat=25.066, lon=109.925, landed="Zhurong (2021)"),
    "elysium": dict(label="Elysium Planitia (InSight)", lat=4.5024, lon=135.6234, landed="InSight (Homestead hollow, 2018)"),
    "ares_vallis": dict(label="Ares Vallis (Pathfinder)", lat=19.13, lon=-33.22, landed="Mars Pathfinder (Carl Sagan Memorial Station, 1997)"),
    "chryse": dict(label="Chryse Planitia (Viking 1)", lat=22.27, lon=-47.95, landed="Viking 1 (Thomas Mutch Memorial Station, 1976)"),
    "mawrth": dict(label="Mawrth Vallis (clay-rich layers)", lat=24.0, lon=-19.0),
    "eberswalde": dict(label="Eberswalde delta", lat=-23.8, lon=-33.6),
    "holden": dict(label="Holden crater", lat=-26.4, lon=-34.0),
    "melas": dict(label="Melas Chasma (Valles Marineris)", lat=-9.8, lon=-76.5),
    "arcadia": dict(label="Arcadia Planitia (shallow ice)", lat=40.0, lon=-160.0),
}
_SITE_ID = r"site_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)"


def site_id(lat, lon):
    """Region id for a box centred on (lat, lon), rounded to 0.01 deg."""
    return f"site_{round(lat, 2):g}_{round((lon + 180) % 360 - 180, 2):g}"


def region_box(name):
    """Bounds + grid density of any region: one of REGIONS, a named SITE or a site_<lat>_<lon> id. None if unknown."""
    import re
    if name in REGIONS:
        return dict(REGIONS[name])
    m = re.fullmatch(_SITE_ID, name)
    lat, lon = (SITES[name]["lat"], SITES[name]["lon"]) if name in SITES else \
               (float(m.group(1)), float(m.group(2))) if m else (None, None)
    if lat is None or not (-88 <= lat <= 88 and -180 <= lon <= 180):
        return None
    h = SITE_SIZE_DEG / 2
    return dict(west=lon - h, east=lon + h, south=max(-89.9, lat - h), north=min(89.9, lat + h),
                px_per_deg=SITE_PX_PER_DEG)


def region_label(name):
    import re
    if name in SITES:
        return SITES[name]["label"]
    m = re.fullmatch(_SITE_ID, name)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return f"Site {abs(lat):.2f}°{'S' if lat < 0 else 'N'} {abs(lon):.2f}°{'W' if lon < 0 else 'E'}"
    return {"jezero": "Jezero crater (Perseverance)", "jezero_hirise": "Jezero close-up (HiRISE)"}.get(
        name, name.replace("_", " ").capitalize())


def mc_quadrangle(lat, lon):
    """Mars Chart quadrangle number (MC-01..30) holding (lat, lon east-positive)."""
    x = (lon + 180) % 360
    if lat > 65:
        return 1
    if lat < -65:
        return 30
    if lat >= 30:
        return 2 + int(x // 60)
    if lat >= 0:
        return 8 + int(x // 45)
    if lat >= -30:
        return 16 + int(x // 45)
    return 24 + int(x // 60)

# ---------------------------------------------------------------------------
# DATA SOURCES (one entry per band). These kinds are supported:
#   {"kind": "file", "path": "..."}             a GeoTIFF you downloaded (most reliable)
#   {"kind": "cog",  "url":  "..."}             a remote GeoTIFF; only the needed window is read
#   {"kind": "download", "url": "...", "path": "data/..."}  fetched once into data/, then read as a file
#   {"kind": "wms",  "server": "...", "layer": "..."}  a USGS WMS layer
#   {"kind": "crism"}                           CRISM mineral maps, found automatically (see MINERALS)
#   {"kind": "table", "path": ..., "lon_col": 0, "lat_col": 1, "value_col": 2}   point table, interpolated
# Optional on file/cog/download: "nodata": 0 (extra no-data value), "resampling": "nearest" (class maps).
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
    "crism": [{"kind": "crism"}],
    # TES bolometric albedo, whole planet (USGS, 16 MB). Dark = absorbs more sunlight.
    "albedo": [
        {"kind": "download", "url": "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif",
         "path": "data/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif"},
        # team table (lon, lat, albedo, TI) if someone has it:
        {"kind": "table", "path": "data/mars_albedo_ti.txt", "lon_col": 0, "lat_col": 1, "value_col": 2, "valid_min": 0},
    ],
    # Calibrated thermal inertia: region-specific maps first (see REGION_SOURCES), then the team table
    "thermal_inertia": [
        {"kind": "table", "path": "data/mars_albedo_ti.txt", "lon_col": 0, "lat_col": 1, "value_col": 3, "valid_min": 1},
    ],
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
# label: plain name shown to everyone ("clay"); science: the precise name, shown in the advanced view.
# detect: below this, treat as no detection (noise); strong: a clear, strong signature.
# Thresholds are for ~100 m cube pixels: averaging 18 m CRISM pixels lowers band depths, so they sit below
# full-resolution values. Checked at Jezero against published maps (Ehlmann 2008, Goudge 2015, Horgan 2020):
# clays NW of the crater and on the delta, carbonates on the inner NW margin and floor, olivine near Seitah.
# The text search ("clay", "carbonate near base", ...), map layers and pixel panel all use this table;
# add a mineral here and rebuild the cube.
# ---------------------------------------------------------------------------
MINERALS = {
    "clay": dict(label="clay", science="Fe/Mg clay (smectite)", params=["D2300"], detect=0.010, strong=0.020, words=[
        "clay", "clays", "smectite", "phyllosilicate", "nontronite", "saponite", "clay minerals", "mud",
        "mudstone", "clay rich"]),
    "carbonate": dict(label="carbonate", science="carbonate (Mg/Fe/Ca)", params=["MIN2295_2480", "MIN2345_2537"], detect=0.002, strong=0.006,
                      words=["carbonate", "magnesite", "siderite", "calcite"]),
    "olivine": dict(label="olivine", science="olivine (Fe/Mg silicate)", params=["OLINDEX3"], detect=0.12, strong=0.16, words=[
        "olivine", "forsterite", "ultramafic"]),
    "pyroxene": dict(label="pyroxene", science="pyroxene (low/high-Ca)", params=["LCPINDEX2", "HCPINDEX2"], detect=0.010, strong=0.020, words=[
        "pyroxene", "augite", "pigeonite", "basaltic"]),
    "sulfate": dict(label="sulfate", science="sulfate (polyhydrated)", params=["SINDEX2"], detect=0.010, strong=0.020, words=[
        "sulfate", "sulphate", "gypsum", "jarosite"]),
    "hydrated_silica": dict(label="silica", science="hydrated silica (opal)", params=["MIN2250"], detect=0.005, strong=0.010,
                            words=["hydrated silica", "opal", "opaline", "silica"]),
    "hydrated": dict(label="water-bearing minerals", science="hydrated minerals (1.9 µm water band)", params=["BD1900_2"], detect=0.008, strong=0.015, words=[
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
# Jezero thermal inertia (THEMIS, calibrated, J m-2 K-1 s-1/2) - Zenodo record 4931348
JEZ_TI = {"kind": "download", "url": "https://zenodo.org/records/4931348/files/Jezero_Thermal_Inertia_v1.tiff?download=1",
          "path": "data/Jezero_Thermal_Inertia_v1.tiff", "nodata": 0}
# Jezero CRISM dominant-mineral map (classes, 0 = no data) - Zenodo record 5575824
JEZ_MIN = {"kind": "download", "url": "https://zenodo.org/records/5575824/files/jezeroFinal.tif?download=1",
           "path": "data/jezeroFinal.tif", "nodata": 0, "resampling": "nearest"}

REGION_SOURCES = {
    "jezero": {
        "elevation": [CTX_DEM_FILE, CTX_DEM],
        "imagery":   [CTX_IMG_FILE, CTX_IMG],
        "thermal_inertia": [JEZ_TI, themis_ti(13)],  # calibrated Jezero map, else MC-13 Syrtis Major (1 km)
        "minerals":  [JEZ_MIN],
    },
    "jezero_hirise": {
        "elevation": [HIRISE_DEM_FILE, CTX_DEM_FILE, CTX_DEM],
        "imagery":   [CTX_IMG_FILE, CTX_IMG],
        "thermal_inertia": [JEZ_TI, themis_ti(13)],
        "minerals":  [JEZ_MIN],
    },
}
# Every other region gets the THEMIS thermal-inertia tile of its quadrangle automatically (build_cube.sources_for).

# Hand-placed science targets per region (replace with Siddhi's CRISM-based picks).
# Coordinates are approximate and for the demo only.
_JEZERO_TARGETS = [
        {"name": "Perseverance landing site (Octavia E. Butler)", "lat": 18.4447, "lon": 77.4508},
        {"name": "Western delta front (approx.)", "lat": 18.50, "lon": 77.40},
]
SCIENCE_TARGETS = {"jezero": _JEZERO_TARGETS, "jezero_hirise": _JEZERO_TARGETS}
SCIENCE_TARGETS.update({k: [{"name": f"{s['landed']} landing site", "lat": s["lat"], "lon": s["lon"]}]
                        for k, s in SITES.items() if s.get("landed")})

# Approximate places for the text target search when the cube has NO band for that material (e.g. a
# region without CRISM coverage). Each zone is a circle; "tags" are the search words that select it.
# A cube band of the same name (built from CRISM, see MINERALS) always wins over these zones.
_JEZERO_ZONES = [
    {"name": "Western fan delta", "tags": ["delta", "clay"], "lat": 18.50, "lon": 77.40, "radius_km": 5.0,
     "source": "Fe/Mg smectite clays seen by CRISM in the delta (Ehlmann et al. 2008); outline approximate"},
]
SEARCH_ZONES = {"jezero": _JEZERO_ZONES, "jezero_hirise": _JEZERO_ZONES}

# ---------------------------------------------------------------------------
# CONSUMABLES: how fast each traveller drinks its supply, and how much it carries.
# rated_hours  = design endurance for one excursion (a hard ceiling, separate from the user's budget)
# consumables  = the rate + capacity the plan is costed against (only the ones that apply)
#   o2_rate_kg_per_h / o2_capacity_kg            breathing supply carried on the suit
#   energy_idle_kw / energy_per_km_kwh / energy_capacity_kwh   battery or fuel-cell load
# consumable_source names the entry in CONSUMABLE_SOURCES shown to the user, so a number can
# always be traced back. Anything tagged "estimate" is NOT a published NASA figure.
# ---------------------------------------------------------------------------
CONSUMABLE_SOURCES = {
    "suit_o2": "NASA's Mars suit design basis (SBIR topic EVA.2.S26B, 2026): oxygen supply sized for "
               "1.9 g/min averaged over 8 h, i.e. 0.114 kg/h and 0.912 kg carried. That is a sizing "
               "average for a whole EVA. On a planned route the rate is adjusted for slope (Minetti "
               "et al. 2002) and for carried load. For comparison NASA's baseline document gives "
               "0.076 kg/h for current EVAs and Apollo walk-back ran at 0.181 kg/h.",
    "mmrtg_energy": "Capacity 2.5 kWh: MSL's MMRTG delivers ~110 W electrical, 2.5-2.7 kWh per "
                    "sol (NASA/JPL). Loads: at least 150 W whenever the rover is awake, up to "
                    "500 W while driving (JPL), which at the 0.15 km/h this profile assumes is "
                    "~3.3 kWh per km.",
    "estimate": "Engineering estimate for a conceptual crew rover - no published NASA figure was "
                "available for these loads. Treat the numbers as tunable, not as fact.",
    "lrv_battery": "Apollo LRV: two 36 V silver-zinc batteries of 121 A-h each (about 8.7 kWh together) "
                   "and a 92 km range, so about 0.095 kWh per km averaged over everything the batteries "
                   "ran. The crew breathe suit oxygen at the astronaut rate. NASA's DRA 5.0 proposes "
                   "open rovers roughly like the LRV for Mars.",
    "mer_solar": "Spirit and Opportunity: arrays gave about 140 W for up to four hours per sol, about "
                 "900 Wh per sol early in the mission and less as dust settled; the rover needs about "
                 "100 W to drive. Modelled as 0.9 kWh per sol with the 100 W draw for the whole crossing.",
    "sojourner_solar": "Sojourner: 0.22 m2 of solar cells giving about 13 to 15 W on Mars, plus a "
                       "non-rechargeable 150 Wh battery. No driving load was published, so energy is not "
                       "modelled; only the rated window applies.",
    "zhurong_solar": "Zhurong: four solar panels. China has not published its energy budget, so energy "
                     "is not modelled; only the rated window applies.",
    "rfm_solar": "Rosalind Franklin: about 1,200 Wh per sol from its arrays and a 1,142 Wh battery "
                 "(ESA). No driving load is published, so energy is not modelled; only the rated "
                 "window applies.",
}

# The astronaut's suit oxygen. Shared by every traveller whose crew breathes from suits.
_SUIT_O2_SUPPLY = dict(o2_rate_kg_per_h=0.114, o2_capacity_kg=0.912)

# Who is walking: used to charge carried load in proportion to the mass moved.
# suit_kg: NASA's 230 lbm starting maximum for a Mars suit (ICES-2026-127). body_kg: an assumption.
WALKER = dict(body_kg=80.0, suit_kg=104.0)

# Contingency held back from O2 and battery on every route: 15 %, raised to 20 % in the dust-storm
# season (Ls 180-330). From the team's resource research (Gia): "15-20 % dust-storm/obstacle contingency".
CONSUMABLE_RESERVE = dict(normal=0.15, dust_season=0.20, dust_season_ls=(180.0, 330.0))

# Power source and mass per planner vehicle, for climbing energy and dust on solar panels.
#   source: nuclear (dust does not matter), solar, battery (recharged), primary (non-rechargeable)
#   sol_kwh: published array output per sol in clear conditions, where one exists
#   recharge_ratio: hours of charging per hour of driving (team research, Gia), used only where
#                   no published array figure exists
VEHICLE_POWER = {
    "pressurized_rover": dict(source="battery", mass_kg=4000.0, recharge_ratio=2.0,
                              note="SEV concept: cabin 3,000 kg + chassis 1,000 kg. Recharge ratio 2:1 is the "
                                   "team's resource research figure, not a NASA one."),
    "unpressurized_rover": dict(source="primary", mass_kg=210.0,
                                note="Apollo LRV mass; its silver-zinc batteries were not rechargeable."),
    "small_rover": dict(source="nuclear", mass_kg=899.0, note="Curiosity, MMRTG."),
    "perseverance": dict(source="nuclear", mass_kg=1025.0, note="Perseverance, MMRTG."),
    "sojourner": dict(source="solar", mass_kg=11.5, note="13-15 W array; output per sol not published."),
    "mer": dict(source="solar", mass_kg=185.0, sol_kwh=0.9, note="About 900 Wh per sol early in the mission."),
    "zhurong": dict(source="solar", mass_kg=240.0, note="Array output not published."),
    "rosalind_franklin": dict(source="solar", mass_kg=310.0, sol_kwh=1.2, note="About 1,200 Wh per sol (ESA)."),
}

# Vehicle / walker profiles. Weights are tunable during the demo.
VEHICLES = {
    "astronaut": dict(label="Astronaut on foot (suited)", max_slope=18.0, base_speed_kmh=6.0,
                      suit_factor=0.5, sand_penalty=1.5, rough_penalty=1.0, uses_slip_table=False,
                      rated_hours=8.0, consumable_source="suit_o2",
                      consumables=dict(_SUIT_O2_SUPPLY)),
    "pressurized_rover": dict(label="Pressurized crew rover", max_slope=20.0, base_speed_kmh=10.0,
                              suit_factor=1.0, sand_penalty=3.0, rough_penalty=2.0, uses_slip_table=True,
                              rated_hours=12.0, consumable_source="estimate",
                              consumables=dict(energy_capacity_kwh=20.0, energy_idle_kw=1.5,
                                               energy_per_km_kwh=0.12)),
    # Apollo LRV figures (flown 1971-72). Design top speed 10 km/h; NASA's LRV mobility report found
    # 20-23 deg slopes workable (spec 25), so 20 here. Terrain penalties copied from the crew rover.
    "unpressurized_rover": dict(label="Open crew rover (Apollo LRV-class)", max_slope=20.0, base_speed_kmh=10.0,
                                suit_factor=1.0, sand_penalty=3.0, rough_penalty=2.0, uses_slip_table=True,
                                rated_hours=8.0, consumable_source="lrv_battery",
                                consumables=dict(_SUIT_O2_SUPPLY, energy_capacity_kwh=8.71, energy_idle_kw=0.0,
                                                 energy_per_km_kwh=0.095)),
    "small_rover": dict(label="Robotic rover (Curiosity-class)", max_slope=25.0, base_speed_kmh=0.15,
                        suit_factor=1.0, sand_penalty=4.0, rough_penalty=2.0, uses_slip_table=True,
                        rated_hours=8.0, consumable_source="mmrtg_energy",
                        consumables=dict(energy_capacity_kwh=2.5, energy_idle_kw=0.15,
                                         energy_per_km_kwh=3.33)),
    # Mars 2020. NASA rover page: top speed about 152 m/h, avoid tilts over 30 deg. Same MMRTG power
    # system as Curiosity, so the energy numbers are the same published MMRTG ones as above.
    "perseverance": dict(label="Perseverance rover (Mars 2020)", max_slope=30.0, base_speed_kmh=0.152,
                         suit_factor=1.0, sand_penalty=4.0, rough_penalty=2.0, uses_slip_table=True,
                         rated_hours=8.0, consumable_source="mmrtg_energy",
                         consumables=dict(energy_capacity_kwh=2.5, energy_idle_kw=0.15,
                                          energy_per_km_kwh=3.33)),
    # Earlier Mars rovers and the next one. Speeds are each rover's published top speed; terrain
    # penalties are copied from the Curiosity-class profile. Rovers with no published driving load
    # have no energy model (see their CONSUMABLE_SOURCES entry) and are limited by rated_hours only.
    # Mars Pathfinder, 1997: top speed 1 cm/s; steered away from slopes over 30 deg (tips at 45).
    # It also stayed within about 500 m of its lander for radio contact, which the planner does not check.
    "sojourner": dict(label="Sojourner (Mars Pathfinder, 1997)", max_slope=30.0, base_speed_kmh=0.036,
                      suit_factor=1.0, sand_penalty=4.0, rough_penalty=2.0, uses_slip_table=True,
                      rated_hours=8.0, consumable_source="sojourner_solar"),
    # Spirit and Opportunity, 2004: top speed 5 cm/s; hazard software kept tilts under 30 deg.
    # rated_hours = the up-to-four hours a sol of full array output.
    "mer": dict(label="Spirit / Opportunity (MER, 2004)", max_slope=30.0, base_speed_kmh=0.18,
                suit_factor=1.0, sand_penalty=4.0, rough_penalty=2.0, uses_slip_table=True,
                rated_hours=4.0, consumable_source="mer_solar",
                consumables=dict(energy_capacity_kwh=0.9, energy_idle_kw=0.10, energy_per_km_kwh=0.0)),
    # Tianwen-1, 2021: about 200 m/h top speed, slopes up to 20 deg (Xinhua).
    "zhurong": dict(label="Zhurong (Tianwen-1, 2021)", max_slope=20.0, base_speed_kmh=0.2,
                    suit_factor=1.0, sand_penalty=4.0, rough_penalty=2.0, uses_slip_table=True,
                    rated_hours=8.0, consumable_source="zhurong_solar"),
    # ExoMars, launch planned 2028: 100 m/h on a straight line; ESA gives about 20 deg as the worst case
    # it can pass (15 on bedrock, 10 on bedrock under thin regolith).
    "rosalind_franklin": dict(label="Rosalind Franklin (ExoMars, launch 2028)", max_slope=20.0, base_speed_kmh=0.1,
                              suit_factor=1.0, sand_penalty=4.0, rough_penalty=2.0, uses_slip_table=True,
                              rated_hours=8.0, consumable_source="rfm_solar"),
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
# suit oxygen (SUIT below).
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
# Suit oxygen = the astronaut profile in VEHICLES (NASA-sourced, see CONSUMABLE_SOURCES["suit_o2"]). The same rate
# applies walking, riding an open rover and sampling; mission.py adds the extra cost of walking uphill.
_SUIT_O2 = VEHICLES["astronaut"]["consumables"]
SUIT = dict(o2_kg=_SUIT_O2["o2_capacity_kg"], o2_walk_kg_h=_SUIT_O2["o2_rate_kg_per_h"],
            o2_ride_kg_h=_SUIT_O2["o2_rate_kg_per_h"], o2_site_kg_h=_SUIT_O2["o2_rate_kg_per_h"],
            source=CONSUMABLE_SOURCES["suit_o2"])
SITE_HOURS = 1.0           # time spent sampling at the destination

# Mission season -> Mars solar longitude and dust risk (global/regional storms mostly start Ls 180-330).
# dust_risk raises route cost, energy use (dimmer sun, dusty panels) and the reserve.
SEASONS = {
    "northern_spring": dict(label="Northern spring (Ls 0-90)", ls=45, dust_risk=0.10),
    "northern_summer": dict(label="Northern summer (Ls 90-180)", ls=135, dust_risk=0.10),
    "northern_autumn": dict(label="Northern autumn (Ls 180-270): dust-storm season", ls=225, dust_risk=0.50),
    "northern_winter": dict(label="Northern winter (Ls 270-360): dust-storm season", ls=315, dust_risk=0.35),
}


BASE_SEASONS = list(SEASONS)          # the four named seasons, Ls 0-90 / 90-180 / 180-270 / 270-360 in order


def season_for_ls(ls):
    """Season entry for any solar longitude from the season slider: the dust risk of the SEASONS range it falls in,
    planned at that exact Ls. Registered in SEASONS under "ls_<deg>" so the planner can use it like the others."""
    ls = round(float(ls) % 360, 1)
    key = f"ls_{ls:g}"
    if key not in SEASONS:
        base = SEASONS[BASE_SEASONS[min(3, int(ls // 90))]]       # spring 0-90, summer, autumn, winter 270-360
        name, dusty = base["label"].split(" (")[0], base["dust_risk"] >= 0.3
        SEASONS[key] = dict(label=f"{name} (Ls {ls:g}°)" + (": dust-storm season" if dusty else ""), ls=ls,
                            dust_risk=base["dust_risk"])
    return key


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
NASA_SITES.update({k: [dict(name=f"{s['landed']} landing site", kind="past landing site", lat=s["lat"], lon=s["lon"],
                            radius_km=0.6)] for k, s in SITES.items() if s.get("landed")})

# COSPAR planetary-protection Special Regions (where liquid water or Earth microbes might survive, e.g.
# recurring slope lineae, gullies, shallow ice). None are known inside the current regions; add circles as
# dict(name=..., lat=..., lon=..., radius_km=..., source=...).
SPECIAL_REGIONS = {"jezero": [], "jezero_hirise": []}
