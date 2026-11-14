# TES ground-temperature detail grid

`tes_detail_8ppd.npz` combines two NASA Mars Global Surveyor Thermal Emission Spectrometer archives. It stores a 1,440 × 2,880 raster on the **0.125°** native TES albedo grid (about 7.4 km north–south). The grid is planetocentric, north-first, and east-positive from −180° to 180°. The app loads it to improve the simulation as you zoom in.

- Broadband (bolometric) albedo is the TES 8 pixel/degree archive product, with no spatial resampling. Each unsigned integer is the albedo × 10,000, with 65,535 reserved for missing data. [NASA PDS TES special products](https://pds-geosciences.wustl.edu/missions/mgs/tesspecial.html)
- Apparent thermal inertia is from the NASA PDS TES 20 pixel/degree nightside and dayside maps. Each target cell uses the spherical intersection area of overlapping, observed source cells. The published interpolation masks exclude archive-filled source cells. The nightside summary is used when available. If it is missing, the same procedure uses dayside cells. The stored unsigned integer is thermal inertia × 10, with 0 for missing data. [NASA PDS TES derived thermal inertia maps](https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html) · [Putzig and Mellon, 2007](https://doi.org/10.1016/j.icarus.2007.05.013)

The resulting grid has **3,986,488** cells with nighttime-derived thermal inertia, **21,765** with daytime fallback, and **138,947** without a supported thermal inertia estimate. Polar gaps and holes are retained. The small-unit rounding is for storage and does not indicate instrument precision. Temperature is computed from these surface properties and the existing coarse 5° atmospheric input. The fine grid supports finer spatial structure in the simulation, with the same approximate surface energy model.

To reproduce the asset using NumPy and the raw files from the PDS archives, run `python thermal_detail.py path/to/global_albedo_8ppd.img path/to/mgst_9001/data` from the app directory.

| Input PDS product | SHA-256 |
| --- | --- |
| `global_albedo_8ppd.img` | `47ee17fc9aca6aa9fd5d49e383c1acc366d4cb31cab4635bc823bc27a33283c7` |
| `global_ti_day_2007.img` | `d8b1ac57c5f2c6d4f43d7e5331591fae0254f48af7629bd0d230c2603da48f9a` |
| `global_ti_msk_day_2007.img` | `23bab175ab99e5aa7b68a4b664f3d616f08c92fcc410188c116d5083103d16cb` |
| `global_ti_night_2007.img` | `faee32838da40045ee7ebd21bed156cc649620312c01165b556d77a2128258f4` |
| `global_ti_msk_night_2007.img` | `fca7ec6fab8b3e81226e1d14dbb3a22509ad111bda4e03bf2b64f050bd550d0b` |
