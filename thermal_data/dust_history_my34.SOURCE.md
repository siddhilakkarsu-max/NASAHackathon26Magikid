# Mars Year 34 atmospheric dust reconstruction

`dust_history_my34.npz` adapts daily reconstructed 9.3 μm absorption column dust optical depth maps by Luca Montabone, Aymeric Spiga, David M. Kass, Armin Kleinböhl, François Forget, and Ehouarn Millour. The v2.5 source uses NASA Mars Reconnaissance Orbiter Mars Climate Sounder retrievals. The observation retrievals were binned and spatially interpolated by the authors. [Archive and license](https://www-mars.lmd.jussieu.fr/mars/dust_climatology/index.html) · [Research article](https://doi.org/10.1029/2019JE006111)

The adapted dataset is distributed under [CC BY-SA 3.0 Unported](https://creativecommons.org/licenses/by-sa/3.0/). It retains the source `Ls`, `SOY` and pressure-normalized `cdod610` variables for all 669 sols, averages adjacent longitude columns to align cell centers to the equirectangular display, and stores opacity with IEEE float16 precision. The source longitude wraps at ±180°. This is a reconstruction of a past event from measured retrievals, with interpolation between observations. The app's optical-depth display threshold is illustrative.

- Source filename `dustscenario_MY34_v2-5.nc`
- SHA-256 `032b9627247e9cc4397c9f007cc8f97a01acf689006b46ff3a51e5abed828797`
- [Original NetCDF](https://www-mars.lmd.jussieu.fr/mars/dust_climatology/dataset_v2/dustscenario_MY34_v2-5.nc)
