"""Extract the competition's portable crop from the verified real Jezero DEM.

Install the source with ``python jezero_terrain.py --download`` first. No network
download, terrain synthesis, hole filling, or global-terrain blend occurs here.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.warp import transform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from competition_terrain import (DATASET_VERSION, MARS_RADIUS_M, SOURCE_DOCUMENTATION,
                                 SOURCE_SHA256, SOURCE_URL, STANDARD_PARALLEL_DEGREES,
                                 THERMAL_SHA256, calculate_slope, sha256_file)

MARS_CRS = "+proj=longlat +R=3396190 +no_defs"
# Fixed native-pixel window around 77.405 E, 18.457 N. One source halo pixel is
# retained during differentiation, then removed from the competition artifact.
CROP_COLUMN, CROP_ROW, NODES = 985, 2309, 321


def build(source, thermal_source, destination):
    if sha256_file(source) != SOURCE_SHA256:
        raise ValueError("DEM checksum does not match the verified USGS product")
    with rasterio.open(source) as dataset:
        if dataset.res != (20, 20) or dataset.shape != (5067, 4456):
            raise ValueError("Unexpected source DEM layout")
        halo = dataset.read(1, window=Window(CROP_COLUMN - 1, CROP_ROW - 1, NODES + 2, NODES + 2), masked=True)
        halo_valid = ~np.ma.getmaskarray(halo) & np.isfinite(halo.data)
        halo_elevation = np.where(halo_valid, halo.data, np.nan).astype(np.float32)
        halo_slope, slope_valid = calculate_slope(halo_elevation, halo_valid, 20)
        elevation = halo_elevation[1:-1, 1:-1].copy()
        valid = (halo_valid & slope_valid)[1:-1, 1:-1].copy()
        slope = halo_slope[1:-1, 1:-1].copy()
        easting, northing = map(float, dataset.xy(CROP_ROW + NODES - 1, CROP_COLUMN))
        west_east, south_north = transform(dataset.crs, MARS_CRS,
                                         [easting, easting + 6400], [northing, northing + 6400])
        projection_wkt = dataset.crs.to_wkt()
        source_transform = list(dataset.transform)[:6]
    thermal = np.full(elevation.shape, np.nan, dtype=np.float32)
    thermal_valid = np.zeros(elevation.shape, dtype=bool)
    west, east = west_east
    south, north = south_north
    longitude_scale = MARS_RADIUS_M * math.cos(math.radians(STANDARD_PARALLEL_DEGREES))
    lon = np.degrees((easting + np.arange(NODES) * 20) / longitude_scale)
    lat = np.degrees((northing + (NODES - 1 - np.arange(NODES)) * 20) / MARS_RADIUS_M)
    rows, cols = np.floor((90 - lat) * 8).astype(int), np.floor((lon + 180) * 8).astype(int)
    thermal_cells = []
    thermal_present = thermal_source.exists()
    if thermal_present:
        if sha256_file(thermal_source) != THERMAL_SHA256:
            raise ValueError("Thermal archive checksum differs from the documented TES derivative")
        with np.load(thermal_source, allow_pickle=False) as archive:
            packed = archive["inertia"]
            if packed.shape != (1440, 2880) or packed.dtype != np.uint16:
                raise ValueError("Unexpected TES derivative layout")
            sampled = packed[np.ix_(rows, cols)]
            thermal_valid = sampled != 0
            thermal = np.where(thermal_valid, sampled / 10, np.nan).astype(np.float32)
            for row in sorted(set(rows.tolist())):
                for col in sorted(set(cols.tolist())):
                    value = int(packed[row, col])
                    thermal_cells.append({"source_row": row, "source_column": col,
                                          "geographic_bounds": {"west": col / 8 - 180, "east": (col + 1) / 8 - 180,
                                                                "north": 90 - row / 8, "south": 90 - (row + 1) / 8},
                                          "value": value / 10 if value else None, "valid": bool(value)})
    destination.mkdir(parents=True, exist_ok=True)
    artifact = destination / "jezero_west_delta_20m.npz"
    np.savez_compressed(artifact, elevation_m=elevation, valid=valid, slope_degrees=slope,
                        thermal_inertia=thermal, thermal_valid=thermal_valid)
    manifest = {
        "dataset_version": DATASET_VERSION, "name": "Jezero western delta mission area",
        "artifact": {"filename": artifact.name, "sha256": sha256_file(artifact), "size_bytes": artifact.stat().st_size},
        "grid": {"shape": list(elevation.shape), "resolution_m": 20, "row_order": "north_to_south",
                 "column_order": "west_to_east", "sample_location": "native DEM pixel centres",
                 "source_transform": source_transform,
                 "source_window": {"row": CROP_ROW, "column": CROP_COLUMN, "height": NODES, "width": NODES}},
        "projection": {"name": "Source equirectangular projection, local translated metres",
                       "radius_m": MARS_RADIUS_M, "standard_parallel_degrees": STANDARD_PARALLEL_DEGREES,
                       "central_meridian_degrees": 0, "origin_easting_m": easting, "origin_northing_m": northing,
                       "origin_longitude": west, "origin_latitude": south, "x_axis": "east", "y_axis": "north",
                       "latitude_type": "planetocentric", "longitude_direction": "east", "source_wkt": projection_wkt},
        "geographic_bounds": {"west": west, "south": south, "east": east, "north": north},
        "elevation": {"label": "Measured CTX elevation", "units": "m", "resolution_m": 20,
                      "source_url": SOURCE_URL, "documentation_url": SOURCE_DOCUMENTATION, "source_sha256": SOURCE_SHA256,
                      "credit": "NASA/JPL/USGS; Fred Calef, Mars 2020 Science Investigation CTX DEM Mosaic (2021)",
                      "vertical_reference": "Source DEM elevations, controlled vertically to MOLA",
                      "processing": "Exact native-pixel crop; no resampling, exaggeration, smoothing, hole filling or boundary blend",
                      "minimum_m": float(np.nanmin(elevation)), "maximum_m": float(np.nanmax(elevation)),
                      "valid_nodes": int(valid.sum()), "total_nodes": int(valid.size)},
        "slope": {"label": "Slope derived from measured elevation", "units": "degrees", "resolution_m": 20,
                  "derivative_baseline_m": 40, "required_stencil_nodes": [3, 3],
                  "processing": "Central differences at 20 m spacing (40 m baseline); arctan of gradient magnitude. A full 3x3 measured stencil is required.",
                  "maximum_degrees": float(np.nanmax(slope))},
        "thermal_inertia": {"label": "Surface-material estimate (thermal inertia)", "units": "J m^-2 K^-1 s^-1/2",
                            "available": thermal_present, "grid_resolution_degrees": 0.125,
                            "resolution_north_south_m": MARS_RADIUS_M * math.radians(0.125),
                            "resolution_east_west_m_at_center": MARS_RADIUS_M * math.radians(0.125) * math.cos(math.radians((south + north) / 2)),
                            "original_product_grid_degrees": 0.05,
                            "source_url": "https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html",
                            "source_dataset_id": "MGS-M-TES-5-TIMAP-V1.0", "source_derived_file": "thermal_data/tes_detail_8ppd.npz",
                            "source_derived_sha256": THERMAL_SHA256 if thermal_present else None,
                            "processing": "Existing area-weighted 0.125 degree TES derivative; observed source pixels only, nightside preferred with dayside fallback. Display uses constant geographic cells, without interpolation.",
                            "missing_data": "Zero in the source derivative becomes invalid/NaN; serialized missing values are null. No fill or material classification.",
                            "interpretation": "A coarse estimate of resistance to temperature change. It does not measure firmness, traction, bearing strength, rocks, or drivable ground.",
                            "cells": thermal_cells},
        "limitations": ["20 m DEM samples do not resolve rover-scale rocks, small ledges, or soil bearing strength.",
                        "The local route boundary is a game mission boundary within measured coverage, not a physical wall.",
                        "Projection distances use the source equirectangular metric frame; this 6.4 km area has less than 0.04% longitude scale variation.",
                        "TES thermal inertia is about 7.4 km north-south and 7.0 km east-west here; it cannot support 20 m material detail.",
                        "The GeoTIFF uses radius 3396190 m; this is retained exactly despite the catalogue listing 3396160 m."],
        "suggested_reference_route_m": [[3900, 2500], [4100, 2650], [4300, 2550], [4450, 2750]],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data" / "M20_JezeroCrater_CTXDEM_20m.tif")
    parser.add_argument("--thermal", type=Path, default=ROOT / "thermal_data" / "tes_detail_8ppd.npz")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "competition")
    args = parser.parse_args()
    result = build(args.source, args.thermal, args.output)
    print(json.dumps({"dataset_version": result["dataset_version"], "artifact": result["artifact"],
                      "geographic_bounds": result["geographic_bounds"], "valid_nodes": result["elevation"]["valid_nodes"]}, indent=2))
