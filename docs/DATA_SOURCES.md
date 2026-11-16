# Data sources

Every dataset, mission product and published figure Marswalk Planner uses, what it feeds, and where it comes
from. **This is also our NASA Space Apps 2026 "NASA data used" list**: copy the NASA rows into the submission.

Add a source? Put it here in the same PR, next to the code that uses it (`config.SOURCES` / `REGION_SOURCES` /
`CONSUMABLE_SOURCES`, `gear/sources.py`, a `*.SOURCE.md` file), and add a `CHANGELOG.md` line.

Where the code gives no link, the row says "no link in the repo yet"; please add one when you find it.

## Orbital data (maps of the surface)

| Dataset | Mission / provider | Feeds | Link |
|---|---|---|---|
| MOLA-HRSC blended DEM, 200 m | MGS MOLA + Mars Express HRSC, USGS | Elevation (then slope, aspect, roughness, air column) for cubes outside Jezero; `/api/point` | [GeoTIFF](https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif) |
| MOLA elevation WMS layer | MGS MOLA, USGS | Fallback elevation source in `config.SOURCES` | [USGS WMS](https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl_elev.map) |
| MDEM200M (MOLA + HRSC, 200 m) | Esri OnMars | The globe's 3D terrain (`/murray/elevation`) and the elevation of "anywhere on Mars" cubes | [ImageServer](https://astro.arcgis.com/arcgis/rest/services/OnMars/MDEM200M/ImageServer) |
| MOLA colour shaded relief | MGS MOLA, Esri OnMars | Murray Lab map "MOLA topography" | [MapServer](https://astro.arcgis.com/arcgis/rest/services/OnMars/MColorDEM/MapServer) |
| CTX DEM of Jezero, 20 m | MRO CTX, Mars 2020 TRN products, USGS | `jezero` cube elevation | [GeoTIFF](https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/ScienceInvestigationMaps_JPL/M20_JezeroCrater_CTXDEM_20m.tif) |
| CTX orthomosaic of Jezero, 6 m | MRO CTX, Mars 2020 TRN products, USGS | `imagery` band, photo overlay | [GeoTIFF](https://planetarymaps.usgs.gov/mosaic/mars2020_trn/CTX/JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0.tif) |
| HiRISE DTM of Jezero, 1 m | MRO HiRISE, Mars 2020 TRN products, USGS | `jezero_hirise` cube (built locally) | [GeoTIFF](https://planetarymaps.usgs.gov/mosaic/mars2020_trn/HiRISE/JEZ_hirise_soc_006_DTM_MOLAtopography_DeltaGeoid_1m_Eqc_latTs0_lon0_blend40.tif) |
| HiRISE footprints | MRO HiRISE, via Murray Lab | Footprint layer and the clicked-point list (`/murray/hirise`) | [HiRISE](https://www.uahirise.org/), [Murray Lab viewer](https://murray-lab.caltech.edu/CTX/V01/SceneView/MurrayLabCTXmosaic.html) |
| Global CTX mosaic, 5 m | MRO CTX, Murray Lab (Caltech), Esri OnMars | Sharp-imagery box, Murray Lab map, `/ctxtiles`, CTX tile map with download links | [MapServer](https://astro.arcgis.com/arcgis/rest/services/OnMars/CTX1/MapServer), [Murray Lab](https://murray-lab.caltech.edu/CTX/V01/SceneView/MurrayLabCTXmosaic.html) |
| Viking MDIM 2.1 colour mosaic | Viking Orbiters, NASA/JPL Mars Trek | Globe base map (`frontend/viking-mdim.jpg`, `/tiles` relay), colour for `/ctxtiles`, Murray Lab map | [Mars Trek API](https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=mars) |
| THEMIS day and night IR mosaics, 100 m | Mars Odyssey THEMIS, USGS WMS | `themis_day`, `themis_night` bands; night IR gives local firmness detail; `/api/point` | [USGS WMS](https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/mars/mars_simp_cyl.map) |
| Calibrated THEMIS thermal inertia of Jezero | Mars Odyssey THEMIS, Zenodo record 4931348 | `thermal_inertia` and `firmness` at Jezero | [Zenodo 4931348](https://zenodo.org/records/4931348) |
| THEMIS thermal inertia, 1 km browse (Huang 2026), one tile per quadrangle, 35° S-45° N | Mars Odyssey THEMIS, Zenodo record 23527756 (CC BY 4.0) | `thermal_inertia` everywhere else; nearest firm ground search | [Zenodo 23527756](https://zenodo.org/records/23527756) |
| CRISM summary parameters (MTRDR targeted, MRDR map tiles) | MRO CRISM, PDS Geosciences ODE | Mineral bands `clay`, `carbonate`, `olivine`, `pyroxene`, `sulfate`, `hydrated_silica`, `hydrated` | [ODE REST](https://oderest.rsl.wustl.edu/live2/); parameters: [Viviano-Beck et al. 2014](https://doi.org/10.1002/2014JE004627) |
| CRISM dominant-mineral class map of Jezero | MRO CRISM, Zenodo record 5575824 | `minerals` and `science` bands at Jezero | [Zenodo 5575824](https://zenodo.org/records/5575824) |
| TES bolometric albedo, 7.4 km | MGS TES, USGS | `albedo` band, `/api/point` | [GeoTIFF](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif) |
| TES albedo 8 px/deg and TES apparent thermal inertia 20 px/deg | MGS TES, NASA PDS Geosciences | Simulated ground temperature (`thermal_data/mars_grid.zip`, `thermal_data/tes_detail_8ppd.npz`) | [TES special products](https://pds-geosciences.wustl.edu/missions/mgs/tesspecial.html), [TES thermal inertia maps](https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html), [method](../thermal_data/tes_detail_8ppd.SOURCE.md) |

Mineral thresholds were checked against published Jezero maps (Ehlmann 2008, Goudge 2015, Horgan 2020; see
`config.MINERALS`). Thermal-inertia classes (dust < 150, sand 150-300, coarse 300-600, bedrock > 600) follow
[Putzig et al. 2005](https://www.sciencedirect.com/science/article/abs/pii/S0019103504002957).

## Weather and climate

| Dataset | Provider | Feeds | Link |
|---|---|---|---|
| OpenMARS reanalysis (Holmes, Lewis and Patel), Mars Year 29, via the ARCO-OpenMARS conversion | The Open University; Bhattacharya (CC BY 4.0) | Air temperature, surface pressure, winds, visible dust, OpenMARS ground temperature (`thermal_data/weather.npz`); pressure for the radiation layer; dust for sunlight and recharge | [OpenMARS](https://doi.org/10.21954/ou.rd.c.4278950), [ARCO-OpenMARS](https://doi.org/10.57967/hf/8741) |
| LMD dust scenarios (Montabone et al. climatology) | Laboratoire de Météorologie Dynamique (CC BY-SA 3.0) | Displayed 9.3 µm dust opacity; sol-to-Ls calendar (`thermal_data/season_calendar.json`) | [Dust scenarios](https://www-mars.lmd.jussieu.fr/mars/dust_scenarios/), [climatology](https://www-mars.lmd.jussieu.fr/mars/dust_climatology/) |
| Mars 2020 MEDA derived TIRS, sol 30 | Perseverance MEDA, NASA PDS Atmospheres | Independent check of the temperature model at Jezero (README) | [MEDA archive](https://pds-atmospheres.nmsu.edu/data_and_services/atmospheres_data/PERSEVERANCE/meda.html), [flux method](https://doi.org/10.1029/2022JE007537) |

The full reviewed weather inventory, with each source's role (ingested, validation candidate, context), is
[`weather_sources.csv`](../weather_sources.csv), also served at `/api/weather/sources`.

## Radiation

| Source | Feeds | Link |
|---|---|---|
| Zhang and Guo 2022, AtRIS/GEANT4 surface effective dose, numerical figure data (CC BY 4.0) | Radiation layer: dose vs pressure for 400 / 700 / 1000 MV (`radiation_data/surface_effective_dose.json`) | [Paper](https://doi.org/10.1029/2021JE007157), [data](https://zenodo.org/records/5953666), [method](../radiation_data/README.md) |
| Guo et al. 2015 | Why dust is context only, not an attenuation factor | [arXiv](https://arxiv.org/html/1507.03473) |
| Curiosity RAD at Gale (~0.64 mSv/day) | Context and the `air_column_vs_gale` shielding band | [NASA](https://science.nasa.gov/resource/radiation-measurements-on-mars/), [PDS RAD data](https://doi.org/10.17189/1519761) |

## Rover tracks, landing sites and place names

| Source | Feeds | Link |
|---|---|---|
| Perseverance traverse and waypoints (with rover tilt) | Green / yellow track layer, track cost factors (`cubes/jezero_tracks.json`) | [M20 traverse](https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_traverse.json), [waypoints](https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json) |
| Mars 2020 (to sol 678) and MSL (to sol 3420) traverses, IAU feature names, CTX tile map | Murray Lab map layers | [Murray Lab features](https://murray-lab.caltech.edu/CTX/V01/SceneView/MurrayLabCTXmosaic.html) |
| IAU impact craters | Crater outlines layer | [Esri Mars nomenclature service](https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/Mars_Nomenclature_Mountains/FeatureServer/7) |
| Landing sites of Viking 1, Pathfinder, Spirit, Opportunity, Curiosity, InSight, Zhurong, Perseverance (`config.SITES`, `NASA_SITES`) | "NASA candidate" landing spots, named places | NASA/JPL mission pages (no link in the repo yet) |
| Mars 2020 landing ellipse (7.7 x 6.6 km, approximated as a 3.5 km circle); Jezero Human Exploration Zone (2015 NASA workshop, USGS CTX mosaic) | Landing spot labels and detail card | `config.NASA_SITES` (no link in the repo yet); exploration-zone background: [Hoffman and Bussey 2016](https://ntrs.nasa.gov/citations/20160001040) |
| COSPAR Special Regions (none known in the current regions) | Off-limits mask (`config.SPECIAL_REGIONS`) | [COSPAR policy](https://cosparhq.cnes.fr/assets/uploads/2024/07/PP-Policy_SRT_220-July-2024.pdf) |

## Physiology and suit

| Figure | Used in | Link |
|---|---|---|
| Suit O2 1.9 g/min over 8 h: 0.114 kg/h, 0.912 kg carried, 8 h rated | Astronaut consumables, mission `SUIT`, gear rule S1 | [NASA SBIR EVA.2.S26B](https://www.sbir.gov/topics/1012257) |
| 0.076 kg/h O2 for current EVAs (comparison) | `CONSUMABLE_SOURCES["suit_o2"]` text | [NASA BVAD Rev 2](https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf) |
| Apollo walk-back rate 0.181 kg/h (comparison) | `CONSUMABLE_SOURCES["suit_o2"]` text | [Norcross et al.](https://ntrs.nasa.gov/citations/20080014853) |
| Mars suit mass 104 kg (230 lbm starting maximum) | `WALKER`, carried-load factor | [ICES-2026-127](https://ntrs.nasa.gov/citations/20260003038) |
| Walking cost vs grade (Minetti et al. 2002) | Oxygen on slopes: route, walk-back zone, mission resources, gear budget | [J Appl Physiol](https://journals.physiology.org/doi/full/10.1152/japplphysiol.01177.2001) |
| Suit sized for slopes up to 20°; walking traverses up to 2 km from the lander | Astronaut `max_slope` 18, mission `on_foot` range 2 km | NASA Exploration EVA ConOps EVA-EXP-0075, 2020 (no link in the repo yet) |
| Apollo crews' unassisted slope limit 20-26° | Astronaut `max_slope` margin | [Scheuring et al. 2007](https://ntrs.nasa.gov/citations/20070030109) |
| Upslope slip table (< 10°: 0-25 %, 10-17°: 25-80 %, > 17°: > 80 %) | `physics.slip_fraction` for rovers | MSL Engineering User Guide (no link in the repo yet) |
| Tobler's hiking function | Walking speed on slopes (`physics.speed_kmh`) | (no link in the repo yet) |
| 50 lbm (22.7 kg) tool and sample allowance per person | Gear hand-carry limit (`gear/budget.py`) | NASA's Mars suit study, excerpt-level source (no link in the repo yet) |
| Body mass 80 kg; reserve 15 % (20 % in dust season, Ls 180-330); 2:1 charge-to-drive | `WALKER`, `CONSUMABLE_RESERVE`, `VEHICLE_POWER` | Team assumptions and team resource research, not NASA figures |

## Vehicles

| Vehicle (`config.VEHICLES` key) | Figures | Link |
|---|---|---|
| Curiosity-class (`small_rover`), Perseverance (`perseverance`) | MMRTG ~110 W, 2.5-2.7 kWh per sol; 150 W awake, up to 500 W driving; Perseverance ~152 m/h, 30° tilt limit | NASA/JPL MMRTG figures (no link in the repo yet); [Perseverance rover page](https://mars.nasa.gov/mars2020/spacecraft/rover/) |
| Pressurized crew rover (`pressurized_rover`, mission `buggy`) | 5,193 kg, 60 kWh, 1.85 kW hotel load, 0.80 kWh/km, traverses within ~20 km | [Chappell, Hoffman and Bekdash 2022](https://ntrs.nasa.gov/api/citations/20210022250/downloads/MarsSurfacePowerOps_IEEE_final.pdf); 10 km/h from the NASA SEV / Lunar Electric Rover ([SEV](https://en.wikipedia.org/wiki/Space_Exploration_Vehicle)) |
| Open crew rover (`unpressurized_rover`, mission `four_wheel`) | Apollo LRV: 8.7 kWh, 92 km range, 0.095 kWh/km, 10 km/h, 20° | [LRV](https://en.wikipedia.org/wiki/Lunar_Roving_Vehicle), [Costes, NASA TR R-401](https://ntrs.nasa.gov/api/citations/19730008090/downloads/19730008090.pdf), [DRA 5.0](https://www.nasa.gov/wp-content/uploads/2015/09/373665main_nasa-sp-2009-566.pdf) |
| Spirit / Opportunity (`mer`) | ~140 W for up to 4 h, ~900 Wh per sol, 100 W to drive, 5 cm/s | [MER](https://en.wikipedia.org/wiki/Mars_Exploration_Rover) |
| Sojourner (`sojourner`) | 13-15 W array, 150 Wh primary battery, 1 cm/s | [Sojourner](https://en.wikipedia.org/wiki/Sojourner_(rover)) |
| Zhurong (`zhurong`) | ~200 m/h, 20° | [Spaceflight Now, citing Xinhua](https://spaceflightnow.com/2021/05/25/chinese-rover-drives-onto-surface-of-mars/) |
| Rosalind Franklin (`rosalind_franklin`) | ~1,200 Wh per sol, 1,142 Wh battery, 100 m/h, 20° | [ESA ExoMars FAQ](https://www.cosmos.esa.int/web/exomars/missions) |
| 2-wheel scout bike (mission `two_wheel`) | Team estimate, no published source | - |

## Gear evidence

Every catalog item and rule on the gear page cites one of these (`gear/sources.py`, 82 sources). Evidence tags
(V verified, P published, E excerpt, I inferred, N none) are explained in
[MISSION_EQUIPMENT_RESEARCH.md](../MISSION_EQUIPMENT_RESEARCH.md) and [gear/README.md](../gear/README.md).

**Standards and requirements**

- [NASA-STD-3001 Vol 1, s4 Human Performance (radiation limits, shelter shielding)](https://www.nasa.gov/reference/4-0-human-performance/) (`std3001_v1_s4`)
- [NASA-STD-3001 Vol 1, s3 Health and Medical Care](https://www.nasa.gov/reference/3-0-health-and-medical-care/) (`std3001_s3`)
- [NASA-STD-3001 Vol 1, s6 Medical Operations](https://www.nasa.gov/reference/6-0-medical-operations/) (`std3001_s6`)
- [NASA-STD-3001 Vol 2, s11 Spacesuits (hydration, CO2, rescue)](https://www.nasa.gov/reference/11-0-spacesuits-vol-2) (`std3001_v2_s11`)
- [NASA-STD-6001 flammability and offgassing](https://standards.nasa.gov/standard/NASA/NASA-STD-6001) (`std6001`)

**Suits and EVA**

- [NASA SBIR EVA.2.S26B, Mars EVA suit PLSS design basis](https://www.sbir.gov/topics/1012257) (`sbir_mars_plss`)
- [ICES-2026-127, Mars spacesuit mass requirements](https://ntrs.nasa.gov/citations/20260003038) (`ices2026_mars_suit`)
- [ICES 2026, Mars PLSS trade study](https://ntrs.nasa.gov/api/citations/20260005204/downloads/ICES_Mars_PLSS_Presentation_2026_1.pdf) (`ices2026_mars_plss`)
- [NASA Baseline Values and Assumptions Document, Rev 2](https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf) (`bvad2`)
- [Ichimura and Yamashiki 2025, BVAD per-crew-day values](https://www.frontiersin.org/journals/space-technologies/articles/10.3389/frspt.2024.1461389/full) (`frontiers_bvad`)
- [Norcross et al., feasibility of a suited 10 km walk-back](https://ntrs.nasa.gov/citations/20080014853) (`norcross_walkback`)
- [Chappell et al., EVA injuries and compromised performance](https://www.lpi.usra.edu/lunar/artemis/ChappellEtAl_NASA-JSC-CN-39092_EVA-Ops-Injuries-And-Compromised-Performance.pdf) (`chappell_eva`)
- [NASA EMU Data Book (ISS suit)](https://www.lpi.usra.edu/lunar/artemis/NASA-EMU-Data-Book-JSC-E-DAA-TN55224.pdf) (`emu_databook`)
- [Extravehicular Mobility Unit (ISS suit)](https://en.wikipedia.org/wiki/Extravehicular_Mobility_Unit) (`wiki_emu`)
- [Strock et al. 2026, EVA fitness review](https://www.nature.com/articles/s41526-026-00619-8) (`strock_eva`)
- [Minetti et al. 2002, energy cost of walking at extreme uphill and downhill slopes](https://journals.physiology.org/doi/full/10.1152/japplphysiol.01177.2001) (`minetti2002`)
- [Team resource research (Gia): reserve, recharge ratio](https://github.com/siddhilakkarsu-max/NASAHackathon26Magikid) (`team_resources`)
- [Kluis and Diaz-Artiles 2021, prebreathe and suit pressure](https://pmc.ncbi.nlm.nih.gov/articles/PMC8594431) (`kluis_prebreathe`)
- [NASA, EVA and human surface mobility program](https://www.nasa.gov/suits-and-rovers) (`nasa_suits_rovers`)

**Radiation, dust, medical**

- [SwRI 2013, first radiation measurements on the Martian surface](https://www.swri.org/newsroom/press-releases/swri-scientists-publish-first-radiation-measurements-the-surface-of-mars) (`swri_rad`)
- [Lowe et al. 2025, nowcasting solar energetic particle events for Mars](https://arxiv.org/html/2502.02469v1) (`lowe2025`)
- [NASA SRAG, protecting astronauts from space radiation](https://srag.jsc.nasa.gov/spaceradiation/how/how.cfm) (`srag`)
- [NASA, crew exposure limits of Martian dust](https://www.nasa.gov/general/establishing-crew-exposure-limits-of-martian-dust/) (`nasa_dust_pel`)
- [NASA, Perseverance clues to protect crews from Mars dust](https://www.nasa.gov/missions/mars-2020-perseverance/nasas-perseverance-offers-clues-to-protect-crews-from-mars-dust) (`nasa_perseverance_dust`)
- [Wang et al. 2025, Martian dust and human health](https://pmc.ncbi.nlm.nih.gov/articles/PMC11815326/) (`wang_dust`)
- [Hecht et al. 2009, perchlorate at the Phoenix site](https://pubmed.ncbi.nlm.nih.gov/19574385/) (`hecht_perchlorate`)
- [NASA Orion crew systems (medical kits, radiation shelter, procedures)](https://www.nasa.gov/reference/crew-systems-2) (`orion_crew`)
- [Gakis and Atri, radiation shielding on Mars](https://arxiv.org/html/2205.13786v3) (`gakis_shield`)

**Mobility and terrain**

- [Costes, mobility performance of the Apollo rover (NASA TR R-401)](https://ntrs.nasa.gov/api/citations/19730008090/downloads/19730008090.pdf) (`costes_lrv`)
- [NASA Space Exploration Vehicle (2008 concept)](https://en.wikipedia.org/wiki/Space_Exploration_Vehicle) (`wiki_sev`)
- [Chappell, Hoffman and Bekdash 2022, Human Mars mission surface power impacts on timeline and traverse capabilities (NASA Mars pressurized rover)](https://ntrs.nasa.gov/api/citations/20210022250/downloads/MarsSurfacePowerOps_IEEE_final.pdf) (`nasa_mars_pr`)
- [Modular Equipment Transporter (Apollo hand cart)](https://en.wikipedia.org/wiki/Modular_Equipment_Transporter) (`wiki_met`)
- [NASA Moon Base systems (lunar rover requirements)](https://www.nasa.gov/moonbase-systems/) (`nasa_moonbase`)
- [NASA, Perseverance rover components](https://mars.nasa.gov/mars2020/spacecraft/rover/) (`nasa_rover_page`)
- [NASA, RIMFAX ground-penetrating radar](https://mars.nasa.gov/mars2020/spacecraft/instruments/rimfax/) (`nasa_rimfax`)
- [Lunar Roving Vehicle (Apollo 15 to 17)](https://en.wikipedia.org/wiki/Lunar_Roving_Vehicle) (`wiki_lrv`)
- [Sojourner rover (Mars Pathfinder)](https://en.wikipedia.org/wiki/Sojourner_(rover)) (`wiki_sojourner`)
- [Mars Exploration Rover (Spirit and Opportunity)](https://en.wikipedia.org/wiki/Mars_Exploration_Rover) (`wiki_mer`)
- [Opportunity rover](https://en.wikipedia.org/wiki/Opportunity_(rover)) (`wiki_opportunity`)
- [Spaceflight Now, Chinese rover drives onto the surface of Mars (citing Xinhua)](https://spaceflightnow.com/2021/05/25/chinese-rover-drives-onto-surface-of-mars/) (`zhurong_xinhua`)
- [Zhurong rover](https://en.wikipedia.org/wiki/Zhurong_(rover)) (`wiki_zhurong`)
- [ESA COSMOS, ExoMars missions FAQ (Rosalind Franklin speed, slope, energy)](https://www.cosmos.esa.int/web/exomars/missions) (`esa_rfm_faq`)
- [Rosalind Franklin rover (ExoMars)](https://en.wikipedia.org/wiki/Rosalind_Franklin_(rover)) (`wiki_rfm`)
- [JPL, Ingenuity mission ends](https://www.jpl.nasa.gov/news/after-three-years-on-mars-nasas-ingenuity-helicopter-mission-ends/) (`jpl_ingenuity`)
- [JPL, attempts to free the sand-trapped Spirit rover](https://www.jpl.nasa.gov/news/nasa-to-begin-attempts-to-free-sand-trapped-mars-rover/) (`jpl_spirit_trap`)
- [NASA, looking back at Purgatory Dune](https://mars.nasa.gov/resources/5855/looking-back-at-purgatory-dune/) (`purgatory_dune`)
- [JPL, breaks observed in Curiosity wheel treads](https://jpl.nasa.gov/news/breaks-observed-in-rover-wheel-treads) (`jpl_curiosity_wheels`)
- [Putzig et al. 2005, global thermal inertia and surface properties of Mars from MGS TES](https://www.sciencedirect.com/science/article/abs/pii/S0019103504002957) (`putzig_ti`)
- [Golombek et al., rover slope limits from landing-site work](https://mars.asu.edu/christensen/docs/golombek_mersites_jgr.pdf) (`golombek_slopes`)
- [Cushing et al. 2007, possible cave skylights on Mars](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2007GL030709) (`cushing_skylights`)

**Science tools**

- [Allton, catalog of Apollo geological sampling tools](https://repository-dev.hou.usra.edu/server/api/core/bitstreams/f74b6eee-9954-4c4b-9b3f-17f87af32348/content) (`allton_apollo_tools`)
- [Kring, geologic tools for the Moon](https://www.lpi.usra.edu/science/kring/lunar_exploration/geologicTools.pdf) (`kring_tools`)
- [Naids et al., Artemis geology sampling tools](https://ntrs.nasa.gov/api/citations/20210000242/downloads/Developing%20Geology%20Sampling%20Tools_Lunar%20Surface%20Science%20Workshop_FINAL_2021.pdf) (`naids_artemis_tools`)
- [Artemis III science definition report](https://science.nasa.gov/wp-content/uploads/2023/07/artemis-iii-science-definition-report-12042020c.pdf) (`artemis3_sdt`)
- [MEPAG human Mars mission science objectives](https://www.lpi.usra.edu/mepag/reports/reports/MHMSOTT-report-final.pdf) (`mepag_human_sci`)
- [JPL, Perseverance sample tubes](https://www.jpl.nasa.gov/news/a-martian-roundtrip-nasas-perseverance-rover-sample-tubes/) (`jpl_sample_tubes`)
- [Leonardo, ExoMars drill datasheet](https://space.leonardo.com/documents/16277711/19573930/ExoMars_LQ_mm07795_.pdf?t=1538987564303) (`leonardo_drill`)
- [NASA, human Mars surface science operations (drill mass)](https://ntrs.nasa.gov/api/citations/20140006398/downloads/20140006398.pdf) (`ntrs_human_drill`)
- [Sehlke et al. 2019, portable instrument suites for human Mars exploration](https://pmc.ncbi.nlm.nih.gov/articles/PMC6442242) (`sehlke_instruments`)
- [Beaton et al. 2019, BASALT science operations concepts](https://pmc.ncbi.nlm.nih.gov/articles/PMC6442237) (`beaton_basalt`)
- [Bruker TRACER handheld XRF specifications](https://www.bergeng.com/mm5/downloads/bruker/Bruker_TRACER_Specifications_Comparison.pdf) (`bruker_tracer`)
- [ASD TerraSpec Halo datasheet](https://www.geopool.fi/wp-content/uploads/2022/01/asd-terraspec-halo-mineral-identifier.pdf) (`asd_halo`)
- [PHOENIX handheld Raman, LIBS and XRF (ESA)](https://analyticalsciencejournals.onlinelibrary.wiley.com/doi/10.1002/jrs.6840) (`phoenix_raman`)
- [COSPAR policy on planetary protection](https://cosparhq.cnes.fr/assets/uploads/2024/07/PP-Policy_SRT_220-July-2024.pdf) (`cospar_pp`)
- [NEEMO 22 EVA overview and debrief](https://www.nasa.gov/wp-content/uploads/2017/02/neemo_22_eva_overview_and_debrief_eva-exp-0054.pdf) (`neemo22`)
- [Desert RATS 2010 field geology on EVA](https://www.lpi.usra.edu/meetings/lpsc2011/pdf/1951.pdf) (`desert_rats`)

**Power, ISRU, construction**

- [NASA fission surface power](https://www.nasa.gov/exploration-systems-development-mission-directorate/fission-surface-power/) (`nasa_fsp`)
- [NASA, MOXIE completes its Mars mission](https://www.nasa.gov/missions/mars-2020-perseverance/perseverance-rover/nasas-oxygen-generating-experiment-moxie-completes-mars-mission/) (`moxie_nasa`)
- [Hoffman et al. 2022, MOXIE, Science Advances](https://pmc.ncbi.nlm.nih.gov/articles/PMC9432831/) (`moxie_sciadv`)
- [Kleinhenz and Paz, ISRU ascent-propellant plant](https://ntrs.nasa.gov/citations/20170001421) (`ntrs_isru_plant`)
- [JPL, SWIM subsurface water ice map](https://www.jpl.nasa.gov/news/nasa-is-locating-ice-on-mars-with-this-new-map/) (`swim_ice`)
- [JPL, InSight solar-array dust cleaning](https://www.jpl.nasa.gov/news/for-insight-dust-cleanings-will-yield-new-science/) (`insight_dust`)
- [ISS National Lab, tools in space](https://issnationallab.org/iss360/innovation-in-focus-tools-in-space/) (`iss_tools`)
- [NASA, Hazard 5: environments (spares and repair)](https://www.nasa.gov/johnson/HWHAP/hazard-5-environments) (`nasa_podcast_spares`)
- [NASA 3D-printed habitat challenge](https://www.nasa.gov/prizes-challenges-and-crowdsourcing/centennial-challenges/3d-printed-habitat-challenge/) (`nasa_3d_habitat`)

**Mission architecture and comms**

- [NASA Mars Design Reference Architecture 5.0 (SP-2009-566)](https://www.nasa.gov/wp-content/uploads/2015/09/373665main_nasa-sp-2009-566.pdf) (`dra5`)
- [NASA Moon-to-Mars architecture definition 2023](https://ntrs.nasa.gov/api/citations/20230002706/downloads/M2MADD_ESDMD-001(TP-20230002706).pdf) (`m2m_2023`)
- [Hoffman and Bussey 2016, Mars landing sites and surface operations](https://ntrs.nasa.gov/citations/20160001040) (`hoffman_ez`)
- [Mashal et al. 2025, exploration-zone screening](https://iopscience.iop.org/article/10.3847/PSJ/ade30e) (`mashal_ez`)
- [NASA Mars Relay Network](https://science.nasa.gov/mars/mars-relay-network/) (`mars_relay`)
- [ASCEND 2022, Mars communication delays and blackouts](https://ntrs.nasa.gov/citations/20220013418) (`ascend_delay`)
- [Lynch et al., logistics rates beyond low Earth orbit](https://ntrs.nasa.gov/api/citations/20230012635/downloads/Logistics%20Rates%20and%20Assumptions%20Beyond%20LEO%20V5.pdf) (`lynch_logistics`)

## Software and services

- [CesiumJS](https://cesium.com/platform/cesiumjs/) 1.147.0, bundled in `frontend/vendor/Cesium/` (Apache 2.0).
- AI text: any OpenAI-compatible server, by default free models on [OpenRouter](https://openrouter.ai/) (README
  section 6). No data comes from the model; it only reads goals and words explanations.


## Game driving envelopes (PR #73)

The Apollo-class game vehicle uses 13 km/h, the observed Apollo 15 level-ground maximum documented in
[NASA's LRV performance report](https://history.nasa.gov/wp-content/uploads/static/history/alsj/WOTM/WOTM-LRVPerformance.html).
The pressurized vehicle uses the [NASA SEV concept's approximately 10 km/h](https://science.nasa.gov/3d-resources/space-exploration-vehicle/).
These are lunar/concept analogies for the Mars game, not Mars crew-rover measurements. Scout-bike and
walking envelopes remain game assumptions. Terrain reduces speed. AI timing is an ideal mathematical
path benchmark without reaction or acceleration delay, not measured NASA autonomous driving.
