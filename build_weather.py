"""Build a compact OpenMARS weather lookup. Requires blosc2 and zstandard."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import blosc2
import numpy as np
import zstandard
from scipy.io import netcdf_file


SOURCE = ("https://huggingface.co/datasets/ananyo01/ARCO-OpenMars/resolve/"
          "c3cceb6/openmars_MY28-35.zarr")
DUST = "https://www-mars.lmd.jussieu.fr/mars/dust_scenarios/dataset/dust_clim.nc"
OUTPUT = Path(__file__).parent / "thermal_data" / "weather.npz"
SEASON_CHUNKS = (66, 72, 78, 85, 92, 99, 105, 110, 115, 119, 124, 129)
FIELDS = {"air_temperature": "temp", "openmars_surface_temperature": "tsurf",
          "surface_pressure": "ps", "east_wind": "u",
          "north_wind": "v", "visible_dust": "dustcol"}


def fetch(url, dest):
    if not dest.exists():
        partial = dest.with_suffix(".part")
        subprocess.run(["curl", "-fLsS", "--retry", "3", "--max-time", "180",
                        "-o", str(partial), url], check=True)
        partial.replace(dest)
    return dest


def read_dust(path):
    with netcdf_file(path, mmap=False) as data:
        return {"dust_" + key: data.variables[source][:].astype("float32")
                for key, source in (("ls", "Ls"), ("latitude", "latitude"),
                                    ("longitude", "longitude"), ("opacity", "cdod"))}


def build(scratch):
    metadata = json.loads(fetch(f"{SOURCE}/zarr.json", scratch / "metadata.json").read_bytes())
    arrays = metadata["consolidated_metadata"]["metadata"]

    def chunk(field, index):
        info = arrays[field]
        shape = info["chunk_grid"]["configuration"]["chunk_shape"]
        path = "/".join([str(index)] + ["0"] * (len(shape) - 1))
        url = f"{SOURCE}/{field}/c/{path}"
        payload = fetch(url, scratch / f"{field}-{index}.bin").read_bytes()
        if info["codecs"][-1]["name"] == "zstd":
            payload = zstandard.ZstdDecompressor().decompress(payload)
        else:
            payload = blosc2.decompress(payload)
        return np.frombuffer(payload, "<f4").reshape(shape)

    lat = chunk("lat", 0)
    lon = chunk("lon", 0)
    level = chunk("lev", 0)[0]
    time = np.concatenate([chunk("time", index) for index in (0, 1)])
    def summarize(index):
        ls = chunk("Ls", index)
        year = chunk("MY", index)
        keep = year == 29
        if not keep.any():
            raise ValueError(f"Chunk {index} contains no Mars Year 29 data")
        hour = np.rint(time[index*120:(index+1)*120] * 12).astype(int) % 12
        result = {}
        for key, field in FIELDS.items():
            values = chunk(field, index)
            if values.ndim == 4:
                values = values[:, 0]
            result[key] = np.stack([np.nanmean(values[keep & (hour == i)], axis=0)
                                    for i in range(12)])
            if not np.isfinite(result[key]).all():
                raise ValueError(f"Missing weather data in {field} at chunk {index}")
        return float(ls[keep].mean()), result

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = sorted(pool.map(summarize, SEASON_CHUNKS), key=lambda entry: entry[0])
    dust = read_dust(fetch(DUST, scratch / "dust_clim.nc"))
    # Sample the daily opacity series to 2-degree season steps to keep the bundle small.
    indices = np.unique(np.searchsorted(dust["dust_ls"], np.arange(0, 360, 2)))
    dust["dust_ls"] = dust["dust_ls"][indices]
    dust["dust_opacity"] = dust["dust_opacity"][indices].astype("float16")
    fields = {key: np.stack([data[key] for _, data in records]).astype("float16") for key in FIELDS}
    np.savez_compressed(OUTPUT, latitude=lat, longitude=lon, sigma=level,
                        ls=[ls for ls, _ in records], **fields, **dust)
    print(f"Wrote {OUTPUT} at seasons: {[round(ls, 2) for ls, _ in records]}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        scratch = Path(sys.argv[1])
        scratch.mkdir(parents=True, exist_ok=True)
        build(scratch)
    else:
        with TemporaryDirectory() as directory:
            build(Path(directory))
