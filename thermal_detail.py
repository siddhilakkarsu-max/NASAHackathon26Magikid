"""Bounded viewport simulation with a global, NASA TES-derived 0.125° grid."""

from functools import lru_cache
from math import ceil, floor, isfinite
from pathlib import Path

import numpy as np

from surface_temperature import solve_temperature


DETAIL_PPD = 8
DETAIL_STEP = 1 / DETAIL_PPD
DETAIL_SHAPE = (180 * DETAIL_PPD, 360 * DETAIL_PPD)
DETAIL_PATH = Path(__file__).parent / "thermal_data" / "tes_detail_8ppd.npz"
MAX_VIEW_CELLS = 200_000
SOURCE_TI_SHAPE = (3600, 7200)
ALBEDO_SCALE = 10000
INERTIA_SCALE = 10
NO_ALBEDO = 65535


@lru_cache(maxsize=1)
def _detail_grid():
    with np.load(DETAIL_PATH, allow_pickle=False) as archive:
        albedo, inertia = archive["albedo"], archive["inertia"]
    if (albedo.shape != DETAIL_SHAPE or inertia.shape != DETAIL_SHAPE
            or albedo.dtype != np.uint16 or inertia.dtype != np.uint16):
        raise ValueError("Unexpected TES detail grid dimensions or storage type")
    return albedo, inertia


def _simulate_window(rows, cols, local_hour, ls):
    alb_grid, ti_grid = _detail_grid()
    area = np.ix_(rows, cols)
    albedo, inertia = alb_grid[area], ti_grid[area]
    albedo = np.where(albedo != NO_ALBEDO, albedo / ALBEDO_SCALE, np.nan)
    inertia = np.where(inertia != 0, inertia / INERTIA_SCALE, np.nan)
    return solve_temperature(
        albedo, inertia, 90 - (rows + 0.5) * DETAIL_STEP,
        -180 + (cols + 0.5) * DETAIL_STEP, local_hour, ls
    )


def _viewport_indices(west, south, east, north):
    if (not all(isfinite(k) for k in (west, south, east, north))
            or not (-180 <= west < east <= 180 and -90 <= south < north <= 90)):
        raise ValueError("Detail viewport must be a nonempty rectangle inside Mars bounds")
    r0 = min(floor((90 - north) * DETAIL_PPD), DETAIL_SHAPE[0] - 1)
    c0 = min(floor((west + 180) * DETAIL_PPD), DETAIL_SHAPE[1] - 1)
    r1 = max(r0 + 1, ceil((90 - south) * DETAIL_PPD))
    c1 = max(c0 + 1, ceil((east + 180) * DETAIL_PPD))
    if (r1 - r0) * (c1 - c0) > MAX_VIEW_CELLS:
        raise ValueError("Zoom in further to request TES detail for this view")
    return r0, r1, c0, c1


def detail_rect(west, south, east, north):
    """Return the extent snapped outward to native cell boundaries."""
    r0, r1, c0, c1 = _viewport_indices(west, south, east, north)
    return {"west": c0 * DETAIL_STEP - 180, "south": 90 - r1 * DETAIL_STEP,
            "east": c1 * DETAIL_STEP - 180, "north": 90 - r0 * DETAIL_STEP}


def detail_overlay(west, south, east, north, local_hour, ls):
    """Simulate intersecting native cells. Split antimeridian views before calling."""
    r0, r1, c0, c1 = _viewport_indices(west, south, east, north)
    raster = _simulate_window(np.arange(r0, r1), np.arange(c0, c1), local_hour, ls)
    return raster, detail_rect(west, south, east, north)


def detail_sample(lat, lon, local_hour, ls):
    """Return the same native value shown by the detail overlay at this location."""
    if not (isfinite(lat) and isfinite(lon) and -90 <= lat <= 90):
        raise ValueError("Invalid point on Mars")
    row = min(floor((90 - lat) * DETAIL_PPD), DETAIL_SHAPE[0] - 1)
    col = floor(((lon + 180) % 360) * DETAIL_PPD)
    return float(_simulate_window(np.array([row]), np.array([col]), local_hour, ls)[0, 0])


def _load_image(path, dtype, shape):
    size = np.dtype(dtype).itemsize * int(np.prod(shape))
    if path.stat().st_size != size:
        raise ValueError(f"Unexpected size for {path}")
    return np.memmap(path, dtype=dtype, mode="r", shape=shape)


def _longitude_reduce(values):
    """Integrate input columns into two bins per five source pixels."""
    cells = values.astype(np.float64).reshape(values.shape[0], -1, 5)
    left = cells[..., 0] + cells[..., 1] + 0.5 * cells[..., 2]
    right = 0.5 * cells[..., 2] + cells[..., 3] + cells[..., 4]
    return np.stack((left, right), axis=-1).reshape(values.shape[0], DETAIL_SHAPE[1])


def _area_reduce(values, first_row):
    """Integrate source/target intersections using longitude width × Δsin(latitude)."""
    rows = first_row + 5 * np.arange(values.shape[0] // 5)
    latitude = 90 - (rows[:, None] + np.array([0, 1, 2, 2.5, 3, 4, 5])) / 20
    weights = -np.diff(np.sin(np.deg2rad(latitude)), axis=1)
    cells = _longitude_reduce(values).reshape(len(rows), 5, DETAIL_SHAPE[1])
    north = (cells[:, :3, :] * weights[:, :3, None]).sum(axis=1)
    south = (cells[:, 2:, :] * weights[:, 3:, None]).sum(axis=1)
    return np.stack((north, south), axis=1).reshape(-1, DETAIL_SHAPE[1])


def _inertia_grid(source, kind):
    values = _load_image(source / f"global_ti_{kind}_2007.img", ">i2", SOURCE_TI_SHAPE)
    mask = _load_image(source / f"global_ti_msk_{kind}_2007.img", "u1", SOURCE_TI_SHAPE)
    result = np.zeros(DETAIL_SHAPE, dtype=np.uint16)
    strip_height = 100
    for start in range(0, SOURCE_TI_SHAPE[0], strip_height):
        data = values[start:start + strip_height]
        flags = mask[start:start + strip_height]
        if not ((flags == 0) | (flags == 1)).all():
            raise ValueError(f"Unexpected TES {kind} interpolation mask values")
        valid = (flags == 1) & (data >= 5) & (data <= 5000)
        area = _area_reduce(valid, start)
        summed = _area_reduce(np.where(valid, data, 0), start)
        result[start * 2 // 5:(start + strip_height) * 2 // 5] = np.rint(
            np.divide(summed * INERTIA_SCALE, area,
                      out=np.zeros_like(summed), where=area > 0)
        ).astype(np.uint16)
    return result


def build(albedo_source, inertia_source, destination=DETAIL_PATH):
    """Bundle native TES albedo and area-weighted masked TES thermal inertia."""
    albedo = _load_image(albedo_source, "<f4", DETAIL_SHAPE)
    valid = np.isfinite(albedo) & (albedo > 0) & (albedo <= 1)
    packed_albedo = np.rint(np.where(valid, albedo * ALBEDO_SCALE, NO_ALBEDO)).astype(np.uint16)
    night = _inertia_grid(inertia_source, "night")
    day = _inertia_grid(inertia_source, "day")
    packed_inertia = np.where(night != 0, night, day)
    print(f"Night: {np.count_nonzero(night):,}; "
          f"day fallback: {np.count_nonzero((night == 0) & (day != 0)):,}; "
          f"no inertia: {np.count_nonzero(packed_inertia == 0):,}")
    np.savez_compressed(destination, albedo=packed_albedo, inertia=packed_inertia)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=build.__doc__)
    parser.add_argument("albedo", type=Path, help="PDS global_albedo_8ppd.img")
    parser.add_argument("inertia_directory", type=Path, help="PDS mgst_9001/data directory")
    args = parser.parse_args()
    build(args.albedo, args.inertia_directory)
