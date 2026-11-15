"""Refresh the compact USGS CTX DTM footprint/asset inventory, not the rasters."""
import gzip
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import murray

API = "https://stac.astrogeology.usgs.gov/api/collections/mro_ctx_controlled_usgs_dtms/items"
OUTPUT = ROOT / "terrain_catalog" / "ctx_dtms.json.gz"
FIELDS = ("id,bbox,properties.gsd,assets.geoid_adjusted_dem.href,assets.dtm.href,-geometry,-links,-stac_extensions,"
          "-assets.thumbnail,-assets.dem,-assets.hillshade,-assets.intersection_error,-assets.orthoimage,"
          "-assets.final_offsets,-assets.provenance,-assets.qa_metrics")


def repair_dateline(records):
    ambiguous = [record for record in records if record["bbox"][2] - record["bbox"][0] >= 180]
    def repair(record):
        item = json.loads(murray._fetch(API + "/" + urllib.parse.quote(record["id"], safe=""), timeout=20))
        longitudes = []
        def visit(coordinates):
            if len(coordinates) >= 2 and isinstance(coordinates[0], (int, float)):
                longitudes.append(float(coordinates[0]) % 360)
            else:
                for child in coordinates:
                    visit(child)
        visit(item["geometry"]["coordinates"])
        values = sorted(set(longitudes))
        gaps = [(values[(i + 1) % len(values)] - value) % 360 for i, value in enumerate(values)]
        cut = max(range(len(gaps)), key=gaps.__getitem__)
        width = 360 - gaps[cut]
        if not 0 < width < 20:
            raise ValueError("Unable to unambiguously unwrap source footprint: " + record["id"])
        west = (values[(cut + 1) % len(values)] + 180) % 360 - 180
        east = (west + width + 180) % 360 - 180
        record["original_bbox"] = record["bbox"]
        record["bbox"] = [west, record["bbox"][1], east, record["bbox"][3]]
        record["dateline_geometry_verified"] = True
    list(ThreadPoolExecutor(max_workers=4).map(repair, ambiguous))
    return len(ambiguous)


def build():
    url = API + "?" + urllib.parse.urlencode({"limit": 1000, "fields": FIELDS})
    records, seen, network_bytes = [], set(), 0
    pages = 0
    matched = None
    while url:
        if urllib.parse.urlparse(url).hostname not in ("stac.astrogeology.usgs.gov", "g6goyz4w56.execute-api.us-west-2.amazonaws.com"):
            raise ValueError("Unexpected STAC pagination host")
        raw = murray._fetch(url, timeout=30)
        network_bytes += len(raw)
        page = json.loads(raw)
        matched = page.get("numberMatched", matched)
        for feature in page.get("features", []):
            identifier = feature["id"]
            if identifier in seen:
                raise ValueError("Repeated source ID in paginated catalogue")
            seen.add(identifier)
            assets = feature.get("assets", {})
            asset_key = "geoid_adjusted_dem" if "geoid_adjusted_dem" in assets else "dtm"
            asset = assets.get(asset_key, {}).get("href")
            bounds = feature.get("bbox")
            spacing = feature.get("properties", {}).get("gsd")
            if not asset or not bounds or not spacing:
                raise ValueError(f"A DTM item is missing its actual elevation asset: {identifier}")
            records.append({"id": identifier, "bbox": bounds, "resolution_m": spacing, "url": asset, "asset_key": asset_key})
        pages += 1
        print(f"CTX catalogue: {len(records)}/{matched} items, {network_bytes / 1e6:.1f} MB metadata", flush=True)
        next_url = next((link["href"] for link in page.get("links", []) if link.get("rel") == "next"), None)
        # The service emits JSON-encoded fields in its next link, but its GET
        # parser expects comma-separated fields. Preserve the official cursor
        # while rebuilding that parameter, or subsequent pages lose gsd.
        if next_url:
            cursor = urllib.parse.parse_qs(urllib.parse.urlparse(next_url).query)["next"][0]
            url = API + "?" + urllib.parse.urlencode({"limit": 1000, "fields": FIELDS, "next": cursor})
        else:
            url = None
        if pages > 100:
            raise ValueError("Unexpected catalogue pagination size")
    if len(records) != matched:
        raise ValueError(f"Incomplete catalogue: {len(records)} of {matched}")
    repaired = repair_dateline(records)
    payload = {"collection": "mro_ctx_controlled_usgs_dtms", "source": API,
               "documentation_url": "https://stac.astrogeology.usgs.gov/docs/data/mars/ctxdtms/",
               "retrieved_utc": datetime.now(timezone.utc).isoformat(), "source_count": len(records),
               "metadata_download_bytes": network_bytes, "dateline_geometry_repairs": repaired, "items": records}
    data = json.dumps(payload, separators=(",", ":")).encode()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".part")
    temporary.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    temporary.replace(OUTPUT)
    print(f"Saved {OUTPUT}: {OUTPUT.stat().st_size:,} compressed bytes; zero DEM rasters downloaded.")


if __name__ == "__main__":
    build()
