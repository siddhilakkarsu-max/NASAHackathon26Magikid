"""
Make frontend/mars-disk.webp: a full-disk view of Mars for the landing page, rendered from the NASA Viking
MDIM 2.1 colour mosaic (NASA Trek tiles) as an orthographic globe with soft limb shading.

    python tools/make_mars_disk.py
"""
import io
import ssl
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "frontend" / "mars-disk.webp"
TREK = ("https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm/"
        "{z}/{y}/{x}.jpg")
LEVEL = 3                      # 16 x 8 tiles of 256 px -> 4096 x 2048 equirectangular
CENTER_LAT, CENTER_LON = 22.0, -62.0     # Valles Marineris and Tharsis, north polar cap near the top
SIZE = 1000


def ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def mosaic():
    rows = []
    for y in range(2 ** LEVEL):
        row = []
        for x in range(2 ** (LEVEL + 1)):
            req = urllib.request.Request(TREK.format(z=LEVEL, y=y, x=x), headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60, context=ctx()) as r:
                row.append(np.asarray(Image.open(io.BytesIO(r.read())).convert("RGB")))
        rows.append(np.hstack(row))
    return np.vstack(rows).astype("float32")


def main():
    eq = mosaic()
    H, W = eq.shape[:2]
    v, u = np.mgrid[0:SIZE, 0:SIZE]
    x, y = (u + 0.5) / SIZE * 2 - 1, 1 - (v + 0.5) / SIZE * 2
    r2 = x * x + y * y
    inside = r2 <= 1
    z = np.sqrt(np.clip(1 - r2, 0, 1))
    phi0, lam0 = np.radians(CENTER_LAT), np.radians(CENTER_LON)
    lat = np.arcsin(np.clip(z * np.sin(phi0) + y * np.cos(phi0), -1, 1))       # inverse orthographic
    lon = lam0 + np.arctan2(x, z * np.cos(phi0) - y * np.sin(phi0))
    lon = (lon + np.pi) % (2 * np.pi) - np.pi
    px = ((lon + np.pi) / (2 * np.pi) * W).astype(int).clip(0, W - 1)
    py = ((np.pi / 2 - lat) / np.pi * H).astype(int).clip(0, H - 1)
    rgb = eq[py, px]
    rgb = rgb * (0.55 + 0.45 * z)[..., None] ** 0.8                           # limb darkening
    lum = rgb.mean(axis=2, keepdims=True)                                       # warmer, more saturated orange
    rgb = lum + (rgb - lum) * 1.6
    rgb = rgb * np.array([1.2, 0.95, 0.55])
    rgb = np.clip((rgb - 12) * 1.12, 0, 255)
    edge = np.clip((1 - np.sqrt(r2)) * SIZE / 2, 0, 1)                          # 1-px anti-aliased rim
    img = np.dstack([rgb, (edge * inside * 255)]).astype("uint8")
    Image.fromarray(img, "RGBA").save(OUT, quality=86, method=6)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
