"""Read the bundled global seasonal OpenMARS and LMD weather grids."""

from functools import lru_cache
from pathlib import Path

import numpy as np


WEATHER_LAYERS = {
    "openmars_surface_temperature": ("OpenMARS ground temperature", "K", 145, 315, "mars_thermal"),
    "air_temperature": ("Near-surface air temperature", "K", 140, 290, "coolwarm"),
    "surface_pressure": ("Surface pressure", "Pa", 200, 1400, "viridis"),
    "wind_speed": ("Near-surface wind speed", "m/s", 0, 30, "plasma"),
    "wind_direction": ("Near-surface wind", "m/s", 0, 30, "plasma"),
    "dust_opacity": ("Atmospheric dust optical depth (9.3 µm, 610 Pa)", "τ", 0, 0.7, "YlOrBr"),
}
GLOBAL_RECT = {"west": -180, "south": -90, "east": 180, "north": 90}


@lru_cache(maxsize=1)
def weather_data():
    path = Path(__file__).parent / "thermal_data" / "weather.npz"
    with np.load(path, allow_pickle=False) as data:
        return {name: data[name] for name in data.files}


def _season(values, seasons, ls):
    extended = np.r_[seasons[-1] - 360, seasons, seasons[0] + 360]
    hi = np.searchsorted(extended, ls % 360, side="right")
    weight = ((ls % 360) - extended[hi - 1]) / (extended[hi] - extended[hi - 1])
    return (values[(hi - 2) % len(seasons)].astype("float32") * (1 - weight)
            + values[(hi - 1) % len(seasons)].astype("float32") * weight)


def dust_map(ls):
    data = weather_data()
    return _season(data["dust_opacity"], data["dust_ls"], ls)


def visible_dust_grid(ls):
    """Return the daily mean visible opacity at the surface for the thermal model."""
    data = weather_data()
    return _season(data["visible_dust"], data["ls"], ls).mean(axis=0)


def _local_hour(values, local_hour):
    # Source samples use prime-meridian time. Convert each longitude independently.
    longitude = weather_data()["longitude"]
    index = ((local_hour % 24 - longitude.astype("float64") / 15) % 24) / 2
    lo = np.floor(index).astype(int)
    col = np.arange(len(longitude))
    weight = index - lo
    return values[lo, :, col].T * (1 - weight) + values[(lo + 1) % 12, :, col].T * weight


def _centered(field):
    # Register source centers (-180, -175, ...) to the display centers
    # (-177.5, -172.5, ...), including the periodic longitude seam.
    return (field + np.roll(field, -1, axis=1)) / 2


def _weather_at_hour(field, local_hour, ls):
    data = weather_data()
    return _centered(_local_hour(_season(data[field], data["ls"], ls), local_hour))


def wind_components(local_hour, ls):
    return (_weather_at_hour("east_wind", local_hour, ls),
            _weather_at_hour("north_wind", local_hour, ls))


def weather_layer(name, local_hour, ls):
    """Return a north-first 5° global map at the same local hour everywhere."""
    if name == "dust_opacity":
        return _centered(dust_map(ls))
    if name in ("wind_speed", "wind_direction"):
        east, north = wind_components(local_hour, ls)
        speed = np.hypot(east, north)
        return speed if name == "wind_speed" else np.where(
            speed >= 0.1, np.degrees(np.arctan2(-east, -north)) % 360, np.nan)
    return _weather_at_hour(name, local_hour, ls)
