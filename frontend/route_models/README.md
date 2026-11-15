# Route playback models

Select **Play route** on a successful manual route or mission candidate. The vehicle follows the outbound path in compressed time, with its display size enlarged when zoomed out. Pause, resume, or replay from the map. The animation and model dimensions are for visualization.

These original low-poly GLB files were rebuilt against the rover reference pack and the mission references below. The supplied NASA renderings served as visual comparisons. The route assets retain their own articulated suit and wheel animations. The two walking profiles share the same suit. The mission scout bike, open rover, and pressurized buggy are illustrative concepts.

The pack includes an ISS EVA photograph and a picture of the ExoMy educational rover. The corresponding route assets use NASA's xEMU prototype and ESA's Rosalind Franklin flight-rover imagery as their primary visual references.

The 60-round model gauntlet raises these assets to mid-poly route detail: 24x16 spheres, 24-sided cylinders, 32-segment tires, denser treads, panel seams, fasteners, cable runs, camera bezels, drill teeth, harnesses, and rack crossbars. Metal and foil use restrained metallic response, solar cells receive a very small blue emissive lift, and glass/visors use lower roughness so close views remain readable under Cesium lighting. The review log is generated at `outputs/marswalk-model-gauntlet-60.html`.

The latest detail review removes the overextended Sojourner side rails and loose canopy pieces, keeps its nuts flush to the chassis, and adds Perseverance avionics modules with mast camera and deck harness wires.

| Model | Visual reference |
|---|---|
| Suited astronaut | [NASA xEMU prototype](https://www.nasa.gov/image-article/new-spacesuit-artemis-generation-astronauts/) |
| Perseverance | [NASA Mars 2020 rover components](https://science.nasa.gov/mission/mars-2020-perseverance/rover-components/) |
| Curiosity-class rover | [NASA Curiosity 3D model](https://science.nasa.gov/resource/curiosity-rover-3d-model/) |
| Sojourner and Spirit/Opportunity | [NASA Mars rover comparison photo](https://science.nasa.gov/photojournal/rovers-and-sojourner/) |
| Zhurong | [CNSA rover and lander photo](https://www.cnsa.gov.cn/english/n6465652/n6465653/c6840321/content.html) |
| Rosalind Franklin | [ESA ExoMars rover 360° view](https://www.esa.int/ESA_Multimedia/Videos/2020/03/ExoMars_Rosalind_Franklin_rover_3601/%28lang%29/en) |
| Open crew rover and four-wheel concept | [NASA Apollo 17 Lunar Roving Vehicle](https://science.nasa.gov/resource/apollo-17-gene-cernan-in-lunar-roving-vehicle/) |
| Pressurized crew rover and buggy | [NASA Space Exploration Vehicle concept](https://science.nasa.gov/3d-resources/space-exploration-vehicle/) |
| Scout bike | [NASA lunar mobility study, Figure 10](https://ntrs.nasa.gov/api/citations/20200002475/downloads/20200002475.pdf) |

Regenerate the assets from the repository root with `python build_route_models.py`. The generator uses NumPy and writes glTF 2.0 binaries with embedded geometry, material colors, and one looping animation per model.
