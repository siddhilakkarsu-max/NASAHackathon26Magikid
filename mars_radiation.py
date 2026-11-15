"""Published AtRIS surface GCR scenario, sampled with historical pressure.

This is a pressure-interpolated model, not a global radiation observation or
forecast. Effective dose is already radiation weighted in the source table;
never apply a second quality factor or optical-dust attenuation to it.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from mars_weather import weather_layer

DATA_DIR = Path(__file__).parent / "radiation_data"
LABEL = "Modeled GCR effective dose"
UNIT = "µSv/h"
MODEL_LABEL = "AtRIS surface scenario"
# Fixed across all three solar scenarios and all pressure/season/hour selections.
SCALE = (12.0, 30.0, "mars_radiation")


@lru_cache(maxsize=1)
def reference_data():
    return json.loads((DATA_DIR / "surface_effective_dose.json").read_text(encoding="utf-8"))


def dose_from_pressure(pressure_pa, solar_mv=700):
    """Linear interpolation in Pa; outside the published domain stays missing.

    mSv/year * 1000 µSv/mSv / hours/year -> µSv/h. The Earth-year display
    convention is explicit in the bundled metadata, not a Martian sol/year.
    """
    ref = reference_data()
    pressure = np.asarray(pressure_pa, dtype="float64")
    knots = np.asarray(ref["pressure_pa"], dtype="float64")
    if str(solar_mv) not in ref["scenarios"]:
        raise ValueError("Choose the published 400, 700 or 1000 MV solar scenario")
    dose = np.asarray(ref["scenarios"][str(solar_mv)]["effective_dose_msv_per_year"], dtype="float64")
    valid = np.isfinite(pressure) & (pressure >= knots[0]) & (pressure <= knots[-1])
    annual = np.interp(pressure, knots, dose)
    return np.where(valid, annual * 1000 / ref["year_hours"], np.nan)


def color_scale(solar_mv=700, spatial_contrast=True):
    """Stable within a solar scenario; never stretch to a viewport or season."""
    if not spatial_contrast:
        return SCALE
    values = dose_from_pressure(reference_data()["pressure_pa"], solar_mv)
    return math.floor(values.min() * 10) / 10, math.ceil(values.max() * 10) / 10, SCALE[2]


def radiation_fields(local_hour, ls, solar_mv=700):
    """North-first 5° grid, at the same local solar hour at every longitude."""
    pressure = weather_layer("surface_pressure", local_hour, ls)
    return dose_from_pressure(pressure, solar_mv), pressure


def radiation_metadata(field, solar_mv=700, spatial_contrast=True):
    ref = reference_data()
    valid = np.isfinite(field)
    return {
        "model_label": f"{MODEL_LABEL} · { {400: 'solar minimum', 700: 'intermediate solar activity', 1000: 'solar maximum'}[solar_mv]} ({solar_mv} MV)",
        "note": "Pressure-interpolated research scenario, not a measured global map or current forecast. "
                "Season and local hour change the historical pressure input. " +
                ("Colors emphasize small spatial differences within this solar scenario; compare numeric rates across scenarios."
                 if spatial_contrast else "Shared color scale for comparing solar scenarios."),
        "color_scale_mode": "spatial" if spatial_contrast else "shared",
        "valid_pressure_pa": [ref["pressure_pa"][0], ref["pressure_pa"][-1]],
        "coverage_percent": round(100 * int(valid.sum()) / valid.size, 1),
        "solar_modulation_mv": solar_mv,
        "dust_note": "Dust optical depth is seasonal infrared opacity at 9.3 µm, normalized to 610 Pa. "
                     "It is context only; no direct dust-to-dose conversion is applied.",
        "limitations": [
            "GCR = galactic cosmic rays. Solar particle events, UV, suit/habitat shielding and local terrain shielding are excluded.",
            "Research estimate of effective dose using the paper's body-response assumptions; not personal astronaut dosimetry.",
            f"Fixed BON solar modulation: {solar_mv} MV. Uniform dry regolith; six published pressure scenarios.",
            "5° historical OpenMARS pressure (Mars Year 29); same local hour everywhere, not one simultaneous planetary snapshot.",
            "Spatial contrast uses fixed bounds from the selected solar scenario; shared scale uses 12–30 µSv/h for all scenarios. "
            "Colors are not safety categories or measured precision.",
            "No quantified global uncertainty is available for this interpolation. Outside the source pressure range is N/A.",
            f"Source mSv/year converted using {ref['year_hours']} hours per Earth year (365.25 days).",
        ],
        "sources": [
            {"title": "Zhang et al. (2022) · AtRIS radiation study", "url": "https://doi.org/10.1029/2021JE007157"},
            {"title": "Published numeric figure data · CC BY 4.0", "url": "https://doi.org/10.5281/zenodo.5953666"},
            {"title": "NASA PDS · Curiosity RAD observations (benchmark, not global coverage)", "url": "https://doi.org/10.17189/1519761"},
            {"title": "OpenMARS · historical pressure input", "url": "https://doi.org/10.57967/hf/8741"},
            {"title": "LMD · seasonal dust context", "url": "https://www-mars.lmd.jussieu.fr/mars/dust_scenarios/index.html"},
            {"title": "Local method and provenance", "url": "/api/radiation/method"},
        ],
    }


def sample_radiation(lat, lon, local_hour, ls, solar_mv=700):
    dose, pressure = radiation_fields(local_hour, ls, solar_mv)
    height, width = dose.shape
    row = min(int((90 - lat) * height / 180), height - 1)
    col = int(((lon + 180) % 360) * width / 360)
    value, p = dose[row, col], pressure[row, col]
    dust = weather_layer("dust_opacity", local_hour, ls)[row, col]
    knots = reference_data()["pressure_pa"]
    low, high = knots[0], knots[-1]
    return {
        "value": round(float(value), 2) if np.isfinite(value) else None,
        "unit": UNIT, "label": LABEL, "model_label": MODEL_LABEL, "grid_step_deg": 5,
        "pressure_pa": round(float(p), 1) if np.isfinite(p) else None,
        "dust_opacity": round(float(dust), 3) if np.isfinite(dust) else None,
        "reason": (None if np.isfinite(value) else "Pressure input is unavailable" if not np.isfinite(p)
                   else f"Pressure outside published {low}–{high} Pa model range"),
    }
