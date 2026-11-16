# Mars elevation inventory

`ctx_dtms.json.gz` is a compact metadata snapshot, not an elevation raster archive.
It contains the 44,628 DTM items returned by the official USGS
`mro_ctx_controlled_usgs_dtms` collection on 2026-11-15. Each record includes its
source ID, footprint bounds, catalog grid spacing, and actual elevation asset URL.
The exporter selects geoid-adjusted DEM or legacy DTM assets, excluding pictures,
hillshade and unadjusted DEM assets. Sixteen ambiguous dateline bounding boxes
were resolved using the items' published geometries.

- [USGS source collection](https://stac.astrogeology.usgs.gov/api/collections/mro_ctx_controlled_usgs_dtms)
- [Processing, datum and quality documentation](https://stac.astrogeology.usgs.gov/docs/data/mars/ctxdtms/)
- [Verified HRSC source inventory](../docs/planner/hrsc50m_sources.json)

Refresh from the repository root with:

```sh
python tools/build_terrain_catalog.py
```

Restart the app after refreshing. The backend streams needed windows from the
referenced official rasters. Published coverage can contain missing pixels and
stereo artifacts; catalog inclusion is not a validation of every elevation.
The global measured elevation remains the fallback, and tile response headers
identify which sources actually contributed.
