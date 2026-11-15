# Modeled GCR effective dose

`surface_effective_dose.json` extracts the surface row from the authors' [published numerical dataset](https://zenodo.org/records/5953666), licensed CC BY 4.0. Credit Jian Zhang and Jingnan Guo (2022). The underlying [AtRIS/GEANT4 study](https://doi.org/10.1029/2021JE007157) uses Mars Climate Database atmospheric profiles. These are model scenarios, not NASA global measurements or a current radiation forecast.

Extraction uses `PAPER1/figure11_eff_depth.txt`, physical line 45, at exactly **height 0 km**. Negative heights are subsurface; the next positive sample is 0.00101 km. Column 1 is height. The published pressure knots are 82, 305, 529, 753, 975 and 1200 Pa. The original header assigns columns 2-7 to 400 MV, 8-13 to 700 MV and 14-19 to 1000 MV. All 18 surface values are retained unchanged.

The app interpolates linearly in pressure and returns N/A outside 82-1200 Pa. This is an app approximation, not a new transport calculation. The authors separately simulated heavy ions at three pressures (82, 753 and 1200 Pa), then interpolated their contribution to the other pressure scenarios; the intermediate values are therefore published model estimates as well. Local irregularities in the table are retained rather than imposing a monotonic trend.

Choose a published solar-modulation scenario: 400 MV (solar minimum, higher GCR), 700 MV (medium activity), or 1000 MV (solar maximum, lower GCR). These are assumptions, not solar activity inferred from a chosen weather date. Solar particle events are excluded; higher solar activity does not mean those events are safer.

For display, multiply mSv/year by 1000/8766 to obtain microsieverts per hour (µSv/h). The conversion assumes a Julian Earth year of 365.25 days; the source says annual without specifying 365 versus 365.25. The convention changes rates by 0.0685%. At 753 Pa, the three scenarios display 27.9733, 19.1101 and 14.3992 µSv/h. Use restrained display precision.

The quantity is **body effective dose**, using tissue-weighted conversion factors described in article section 2.3. It is distinct from detector absorbed dose and water-sphere dose equivalent. No further radiation quality factor is applied. Dry-regolith modeling does not resolve local water/ice, terrain shelter, or suits/habitats. The numerical table supplies no per-point uncertainty, so that remains N/A.

The spatial display uses the source scenario's minimum and maximum rates, rounded outward to 0.1 µSv/h. These bounds stay fixed when season, hour or viewport changes. Small differences are visually emphasized; colors between different solar scenarios must not be compared in this mode. The shared scale (12–30 µSv/h) allows those comparisons. Both modes return identical physical values. The historical OpenMARS pressure input has a 5° grid. Bilinear display smoothing does not create finer evidence, and each missing source cell stays transparent. Hover values use the native grid cell.

Season and local time affect the pressure input. [Guo et al. (2015), section IV.1.2](https://arxiv.org/html/1507.03473), finds airborne dust's direct contribution negligible compared with atmospheric pressure. Dust opacity therefore remains contextual, not a cosmic-ray attenuation factor.

[NASA Curiosity RAD observations](https://science.nasa.gov/resource/radiation-measurements-on-mars/) provide context at Gale Crater. [NASA PDS RAD reduced data](https://doi.org/10.17189/1519761) describes actual detector data. Such observations help evaluate transport models; they do not establish measured doses at every map point.

Source archive MD5: `f65945053d690414dbbbb9481073333d`. Figure 11 table SHA-256: `0da024d59e554f4a6f635271d251feb655715f92907cab3cf3230dbed633bc0f`. Original archive metadata is in `zenodo_record.json`. Extraction checks require one exact zero-height row and equality to the retained source values.
