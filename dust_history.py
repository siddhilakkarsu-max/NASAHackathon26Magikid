"""Daily LMD reconstruction of the 2018/Mars Year 34 atmospheric dust event."""

from functools import lru_cache
from pathlib import Path

import numpy as np


SOURCE = ("https://www-mars.lmd.jussieu.fr/mars/dust_climatology/"
          "dataset_v2/dustscenario_MY34_v2-5.nc")
ARCHIVE = "https://www-mars.lmd.jussieu.fr/mars/dust_climatology/index.html"
REFERENCE = "https://doi.org/10.1029/2019JE006111"
SATELLITE_IMAGERY = "https://science.nasa.gov/photojournal/2018-giant-dust-storm-on-mars/"
DATA_FILE = Path(__file__).parent / "thermal_data" / "dust_history_my34.npz"

# A visualization cutoff on the 9.3 μm absorption product at 610 Pa.
# It does not define storm boundaries or declare where dust was lifted.
STORM_THRESHOLD = 0.8


@lru_cache(maxsize=1)
def _history():
    with np.load(DATA_FILE, allow_pickle=False) as data:
        ls, sol, opacity = data["ls"], data["sol"], data["opacity"]
    if opacity.shape != (len(ls), 60, 120) or sol.shape != ls.shape:
        raise ValueError("Unexpected Mars Year 34 daily gridded dust dimensions")
    return ls, sol, opacity


def dust_calendar():
    """Native solar longitude for each archived sol in chronological order."""
    return _history()[0].astype("float64")


def dust_sols():
    """Native integer sol labels matching dust_calendar()."""
    return _history()[1].copy()


def dust_sol_to_ls(sol):
    ls, sols, _ = _history()
    match = np.searchsorted(sols, sol)
    if match == len(sols) or sols[match] != sol:
        raise ValueError(f"Sol must be in the archived range {sols[0]}–{sols[-1]}")
    return float(ls[match])


def dust_snapshot(ls):
    """Return (opacity grid, archive sol, archive Ls) for the closest daily map."""
    longitudes, sols, opacity = _history()
    index = int(np.argmin(np.abs(longitudes - ls)))
    return opacity[index].astype("float32"), int(sols[index]), float(longitudes[index])


def historical_dust(ls):
    """Return the north-first dust opacity grid for the closest daily map."""
    return dust_snapshot(ls)[0]


def build(source, destination=DATA_FILE):
    """Subset the LMD NetCDF to the 610-Pa opacity and time coordinates."""
    from scipy.io import netcdf_file

    with netcdf_file(source, mmap=False) as dataset:
        variables = dataset.variables
        time = variables["Time"][:].astype("float64")
        sol = variables["SOY"][:].astype("int16")
        ls = variables["Ls"][:].astype("float32")
        latitude = variables["latitude"][:].astype("float64")
        longitude = variables["longitude"][:].astype("float64")
        field = variables["cdod610"]
        opacity = field[:].astype("float32")
        for name in ("_FillValue", "missing_value"):
            if hasattr(field, name):
                opacity[opacity == getattr(field, name)] = np.nan

    if opacity.shape != (len(ls), 60, 120) or not np.all(np.diff(ls) > 0):
        raise ValueError("Unexpected shape or ordering in the LMD dust archive")
    if not np.array_equal(time, sol.astype("float64") - 0.5) or not np.all(np.diff(sol) == 1):
        raise ValueError("LMD time does not represent consecutive sols")
    if not np.allclose(latitude, 88.5 - 3 * np.arange(60)):
        raise ValueError("Unexpected LMD dust latitude registration")
    if not np.allclose(longitude, -180 + 3 * np.arange(120)):
        raise ValueError("Unexpected LMD dust longitude registration")

    opacity[~np.isfinite(opacity) | (opacity < 0)] = np.nan
    # Source columns are centered on -180°, -177°, …; align the display
    # to -178.5°, -175.5°, … with the dateline treated as periodic.
    opacity = (opacity + np.roll(opacity, -1, axis=2)) / 2
    np.savez_compressed(destination, ls=ls, sol=sol, opacity=opacity.astype("float16"))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("netcdf", type=Path, help="LMD dustscenario_MY34_v2-5.nc")
    args = parser.parse_args()
    build(args.netcdf)
