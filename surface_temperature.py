"""Approximate diurnal surface temperatures from the half-degree Mars grid."""

from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from mars_weather import visible_dust_grid


GRID_PATH = Path(__file__).parent / "thermal_data" / "mars_grid.zip"
GRID_SHAPE = (360, 720)
SOL_SECONDS = 88775.244
EMISSIVITY = 0.95
STEFAN_BOLTZMANN = 5.670374419e-8
HOUR_SAMPLES = 48


@lru_cache(maxsize=1)
def thermal_grid():
    """Read the bundled, north-first CSV and retain unavailable cells as NaN."""
    with ZipFile(GRID_PATH) as archive:
        with archive.open("mars_grid_0p5deg_simple.csv") as csv_file:
            data = np.genfromtxt(csv_file, delimiter=",", skip_header=1,
                                 missing_values="n/a", filling_values=np.nan)
    if data.shape != (np.prod(GRID_SHAPE), 4):
        raise ValueError("Unexpected Mars thermal grid dimensions")
    grid = data.reshape(*GRID_SHAPE, 4)
    if (not np.all(grid[:, :, 0] == (89.75 - np.arange(360) / 2)[:, None])
            or not np.all(grid[:, :, 1] == (-179.75 + np.arange(720) / 2)[None, :])):
        raise ValueError("Unexpected Mars thermal grid coordinates")
    return grid[:, :, 2], grid[:, :, 3]


def _simulate_cells(lat, albedo, inertia, opacity, local_hour, ls):
    """Solve a periodic, linearized radiative/conductive energy balance."""
    season = np.deg2rad(ls % 360)
    declination = np.arcsin(np.sin(np.deg2rad(25.19)) * np.sin(season))
    # Incoming irradiance scales with inverse square of Mars-Sun distance.
    eccentricity = 0.0934
    anomaly = season - np.deg2rad(251.0)
    distance_ratio = (1 - eccentricity**2) / (1 + eccentricity * np.cos(anomaly))
    top_of_atmosphere = 590.0 / distance_ratio**2
    latitude = np.deg2rad(lat)[:, None]
    sample_angle = 2 * np.pi * (np.arange(HOUR_SAMPLES) / HOUR_SAMPLES - 0.5)
    cos_zenith = (np.sin(latitude) * np.sin(declination)
                  + np.cos(latitude) * np.cos(declination) * np.cos(sample_angle))
    direct = np.maximum(cos_zenith, 0)
    transmission = np.exp(-opacity[:, None] / np.maximum(direct, 0.05))
    absorbed = (1 - albedo[:, None]) * top_of_atmosphere * direct * transmission
    mean_flux = absorbed.mean(axis=1) + 25.0  # fixed downwelling longwave, W/m²
    emission = EMISSIVITY * STEFAN_BOLTZMANN
    mean_temperature = (mean_flux / emission)**0.25
    radiative_response = 4 * emission * mean_temperature**3

    # A semi-infinite substrate adds a frequency-dependent response. Its
    # imaginary part delays the temperature peak and retains heat after sunset.
    harmonics = np.arange(1, HOUR_SAMPLES // 2)
    conduction = inertia[:, None] * np.sqrt(1j * 2 * np.pi * harmonics / SOL_SECONDS)
    forcing = 2 * np.fft.rfft(absorbed, axis=1)[:, 1:-1] / HOUR_SAMPLES
    phase = np.exp(2j * np.pi * harmonics * (local_hour % 24) / 24)
    perturbation = (forcing / (radiative_response[:, None] + conduction)) @ phase
    return mean_temperature + perturbation.real


def solve_temperature(albedo, inertia, lat, lon, local_hour, ls):
    """Solve at the supplied native raster cell centers without filling gaps."""
    temperature = np.full(albedo.shape, np.nan, dtype=np.float32)
    valid_rows, valid_cols = np.nonzero(
        np.isfinite(albedo) & np.isfinite(inertia) & (inertia > 0)
    )
    if not valid_rows.size:
        return temperature
    # Interpolate the coarser atmosphere at the centers of the thermal cells.
    # Dust columns are centered on -180°, -175°, … and wrap at the date line.
    dust = visible_dust_grid(ls)
    y = np.clip((87.5 - lat) / 5, 0, dust.shape[0] - 1)
    x = ((lon + 180) % 360) / 5
    y0, x0 = y.astype(int), x.astype(int)
    y1 = np.minimum(y0 + 1, dust.shape[0] - 1)
    x1 = (x0 + 1) % dust.shape[1]
    fy, fx = (y - y0)[:, None], (x - x0)[None, :]
    north = dust[np.ix_(y0, x0)] * (1 - fx) + dust[np.ix_(y0, x1)] * fx
    south = dust[np.ix_(y1, x0)] * (1 - fx) + dust[np.ix_(y1, x1)] * fx
    opacity = north * (1 - fy) + south * fy
    for start in range(0, len(valid_rows), 4096):
        r = valid_rows[start:start + 4096]
        c = valid_cols[start:start + 4096]
        temperature[r, c] = _simulate_cells(
            lat[r], albedo[r, c], inertia[r, c], opacity[r, c], local_hour, ls
        )
    return temperature


def temperature_overlay(rect, shape, local_hour, ls):
    """Sample model cells onto the map rectangle using pixel-center coordinates."""
    height, width = shape
    lat = rect["north"] - (np.arange(height) + 0.5) * (rect["north"] - rect["south"]) / height
    lon = rect["west"] + (np.arange(width) + 0.5) * (rect["east"] - rect["west"]) / width
    rows = np.clip(np.floor((90 - lat) * 2).astype(int), 0, 359)
    cols = np.floor(((lon + 180) % 360) * 2).astype(int)
    unique_rows, row_index = np.unique(rows, return_inverse=True)
    unique_cols, col_index = np.unique(cols, return_inverse=True)
    albedo, inertia = thermal_grid()
    area = np.ix_(unique_rows, unique_cols)
    temperature = solve_temperature(
        albedo[area], inertia[area], 89.75 - unique_rows / 2,
        -179.75 + unique_cols / 2, local_hour, ls
    )
    return temperature[np.ix_(row_index, col_index)]
