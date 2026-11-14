"""
Makes a FAKE Jezero-shaped cube so the back end and front end can be built
before the real data download works. Same file format as build_cube.py.

    python make_demo_cube.py        -> cubes/jezero.npz  (overwrite later with real data)
"""
import numpy as np
from scipy.ndimage import gaussian_filter

from build_cube import derive_terrain, make_grid, normalize01, save


def main(region="jezero", seed=7):
    rng = np.random.default_rng(seed)
    grid = make_grid(region)
    H, W = grid["height"], grid["width"]
    y, x = np.mgrid[0:H, 0:W] / max(H, W)
    # crater bowl + rim + rolling noise + a delta lobe on the west side
    cx, cy = 0.45, 0.42
    r = np.hypot(x - cx, (y - cy) * 1.2)
    elev = -2600 + 600 * np.clip(r / 0.42, 0, 1) ** 3 + 900 * np.exp(-((r - 0.45) / 0.04) ** 2)
    elev += 80 * np.exp(-(((x - 0.30) / 0.08) ** 2 + ((y - 0.38) / 0.10) ** 2))  # delta
    elev += gaussian_filter(rng.normal(0, 1, (H, W)), 6) * 120
    elev = elev.astype("float32")
    # night IR: sand patches are cold (low), rock warm (high)
    night = gaussian_filter(rng.normal(0, 1, (H, W)), 10)
    night += 2.0 * np.exp(-(((x - 0.62) / 0.06) ** 2 + ((y - 0.55) / 0.05) ** 2)) * -3  # sand trap
    night = (night - night.min()) / (night.max() - night.min()) * 255
    cube = {"elevation": elev, "themis_night": night.astype("float32")}
    cube["slope"], cube["aspect"], cube["roughness"] = derive_terrain(elev, grid)
    cube["firmness"] = normalize01(night)
    save(region, grid, cube, {"elevation": "SYNTHETIC DEMO", "themis_night": "SYNTHETIC DEMO"})


if __name__ == "__main__":
    main()
