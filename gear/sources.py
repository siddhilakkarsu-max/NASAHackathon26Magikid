"""
Evidence registry for the gear system.

Every catalog item and every rule points at source ids defined here, so a URL is written once
and the front end can show the same citation wherever it is used.

Confidence tags (same meaning as MISSION_EQUIPMENT_RESEARCH.md):
    V  verified   - the page was re-opened and the number found
    P  published  - read by a research agent, not re-checked
    E  excerpt    - seen only as a search-result excerpt (usually a PDF); check before relying on it
    I  inferred   - arithmetic or judgement built on sourced inputs
    N  none       - searched for and not found; the item is a proposal, not a specification
"""

CONFIDENCE = {
    "V": {"label": "Verified", "rank": 5, "meaning": "Source page re-opened and the figure found."},
    "P": {"label": "Published", "rank": 4, "meaning": "Read in the source by a research agent; not re-checked."},
    "E": {"label": "Excerpt", "rank": 3, "meaning": "Seen only in a search excerpt (often a PDF). Verify before relying on it."},
    "I": {"label": "Inferred", "rank": 2, "meaning": "Reasoning or arithmetic on sourced inputs. Tunable."},
    "N": {"label": "No source", "rank": 1, "meaning": "No published basis found. A proposal, not a specification."},
}

SOURCES = {
    # --- standards and requirements
    "std3001_v1_s4": ("NASA-STD-3001 Vol 1, s4 Human Performance (radiation limits, shelter shielding)",
                      "https://www.nasa.gov/reference/4-0-human-performance/"),
    "std3001_s3": ("NASA-STD-3001 Vol 1, s3 Health and Medical Care",
                   "https://www.nasa.gov/reference/3-0-health-and-medical-care/"),
    "std3001_s6": ("NASA-STD-3001 Vol 1, s6 Medical Operations",
                   "https://www.nasa.gov/reference/6-0-medical-operations/"),
    "std3001_v2_s11": ("NASA-STD-3001 Vol 2, s11 Spacesuits (hydration, CO2, rescue)",
                       "https://www.nasa.gov/reference/11-0-spacesuits-vol-2"),
    "std6001": ("NASA-STD-6001 flammability and offgassing", "https://standards.nasa.gov/standard/NASA/NASA-STD-6001"),
    # --- suits and EVA
    "sbir_mars_plss": ("NASA SBIR EVA.2.S26B, Mars EVA suit PLSS design basis", "https://www.sbir.gov/topics/1012257"),
    "ices2026_mars_suit": ("ICES-2026-127, Mars spacesuit mass requirements", "https://ntrs.nasa.gov/citations/20260003038"),
    "ices2026_mars_plss": ("ICES 2026, Mars PLSS trade study",
                           "https://ntrs.nasa.gov/api/citations/20260005204/downloads/ICES_Mars_PLSS_Presentation_2026_1.pdf"),
    "bvad2": ("NASA Baseline Values and Assumptions Document, Rev 2",
              "https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf"),
    "frontiers_bvad": ("Ichimura and Yamashiki 2025, BVAD per-crew-day values",
                       "https://www.frontiersin.org/journals/space-technologies/articles/10.3389/frspt.2024.1461389/full"),
    "norcross_walkback": ("Norcross et al., feasibility of a suited 10 km walk-back", "https://ntrs.nasa.gov/citations/20080014853"),
    "chappell_eva": ("Chappell et al., EVA injuries and compromised performance",
                     "https://www.lpi.usra.edu/lunar/artemis/ChappellEtAl_NASA-JSC-CN-39092_EVA-Ops-Injuries-And-Compromised-Performance.pdf"),
    "emu_databook": ("NASA EMU Data Book (ISS suit)",
                     "https://www.lpi.usra.edu/lunar/artemis/NASA-EMU-Data-Book-JSC-E-DAA-TN55224.pdf"),
    "wiki_emu": ("Extravehicular Mobility Unit (ISS suit)", "https://en.wikipedia.org/wiki/Extravehicular_Mobility_Unit"),
    "strock_eva": ("Strock et al. 2026, EVA fitness review", "https://www.nature.com/articles/s41526-026-00619-8"),
    "minetti2002": ("Minetti et al. 2002, energy cost of walking at extreme uphill and downhill slopes",
                    "https://journals.physiology.org/doi/full/10.1152/japplphysiol.01177.2001"),
    "team_resources": ("Team resource research (Gia): reserve, recharge ratio",
                       "https://github.com/siddhilakkarsu-max/NASAHackathon26Magikid"),
    "kluis_prebreathe": ("Kluis and Diaz-Artiles 2021, prebreathe and suit pressure", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8594431"),
    "nasa_suits_rovers": ("NASA, EVA and human surface mobility program", "https://www.nasa.gov/suits-and-rovers"),
    # --- radiation, dust, medical
    "swri_rad": ("SwRI 2013, first radiation measurements on the Martian surface",
                 "https://www.swri.org/newsroom/press-releases/swri-scientists-publish-first-radiation-measurements-the-surface-of-mars"),
    "lowe2025": ("Lowe et al. 2025, nowcasting solar energetic particle events for Mars", "https://arxiv.org/html/2502.02469v1"),
    "srag": ("NASA SRAG, protecting astronauts from space radiation", "https://srag.jsc.nasa.gov/spaceradiation/how/how.cfm"),
    "nasa_dust_pel": ("NASA, crew exposure limits of Martian dust", "https://www.nasa.gov/general/establishing-crew-exposure-limits-of-martian-dust/"),
    "nasa_perseverance_dust": ("NASA, Perseverance clues to protect crews from Mars dust",
                               "https://www.nasa.gov/missions/mars-2020-perseverance/nasas-perseverance-offers-clues-to-protect-crews-from-mars-dust"),
    "wang_dust": ("Wang et al. 2025, Martian dust and human health", "https://pmc.ncbi.nlm.nih.gov/articles/PMC11815326/"),
    "hecht_perchlorate": ("Hecht et al. 2009, perchlorate at the Phoenix site", "https://pubmed.ncbi.nlm.nih.gov/19574385/"),
    "orion_crew": ("NASA Orion crew systems (medical kits, radiation shelter, procedures)", "https://www.nasa.gov/reference/crew-systems-2"),
    "gakis_shield": ("Gakis and Atri, radiation shielding on Mars", "https://arxiv.org/html/2205.13786v3"),
    # --- mobility and terrain
    "costes_lrv": ("Costes, mobility performance of the Apollo rover (NASA TR R-401)",
                   "https://ntrs.nasa.gov/api/citations/19730008090/downloads/19730008090.pdf"),
    "wiki_sev": ("NASA Space Exploration Vehicle (2008 concept)", "https://en.wikipedia.org/wiki/Space_Exploration_Vehicle"),
    "wiki_met": ("Modular Equipment Transporter (Apollo hand cart)", "https://en.wikipedia.org/wiki/Modular_Equipment_Transporter"),
    "nasa_moonbase": ("NASA Moon Base systems (lunar rover requirements)", "https://www.nasa.gov/moonbase-systems/"),
    "nasa_rover_page": ("NASA, Perseverance rover components", "https://mars.nasa.gov/mars2020/spacecraft/rover/"),
    "nasa_rimfax": ("NASA, RIMFAX ground-penetrating radar", "https://mars.nasa.gov/mars2020/spacecraft/instruments/rimfax/"),
    "wiki_lrv": ("Lunar Roving Vehicle (Apollo 15 to 17)", "https://en.wikipedia.org/wiki/Lunar_Roving_Vehicle"),
    "wiki_sojourner": ("Sojourner rover (Mars Pathfinder)", "https://en.wikipedia.org/wiki/Sojourner_(rover)"),
    "wiki_mer": ("Mars Exploration Rover (Spirit and Opportunity)", "https://en.wikipedia.org/wiki/Mars_Exploration_Rover"),
    "wiki_opportunity": ("Opportunity rover", "https://en.wikipedia.org/wiki/Opportunity_(rover)"),
    "zhurong_xinhua": ("Spaceflight Now, Chinese rover drives onto the surface of Mars (citing Xinhua)",
                       "https://spaceflightnow.com/2021/05/25/chinese-rover-drives-onto-surface-of-mars/"),
    "wiki_zhurong": ("Zhurong rover", "https://en.wikipedia.org/wiki/Zhurong_(rover)"),
    "esa_rfm_faq": ("ESA COSMOS, ExoMars missions FAQ (Rosalind Franklin speed, slope, energy)",
                    "https://www.cosmos.esa.int/web/exomars/missions"),
    "wiki_rfm": ("Rosalind Franklin rover (ExoMars)", "https://en.wikipedia.org/wiki/Rosalind_Franklin_(rover)"),
    "jpl_ingenuity": ("JPL, Ingenuity mission ends", "https://www.jpl.nasa.gov/news/after-three-years-on-mars-nasas-ingenuity-helicopter-mission-ends/"),
    "jpl_spirit_trap": ("JPL, attempts to free the sand-trapped Spirit rover",
                        "https://www.jpl.nasa.gov/news/nasa-to-begin-attempts-to-free-sand-trapped-mars-rover/"),
    "purgatory_dune": ("NASA, looking back at Purgatory Dune", "https://mars.nasa.gov/resources/5855/looking-back-at-purgatory-dune/"),
    "jpl_curiosity_wheels": ("JPL, breaks observed in Curiosity wheel treads", "https://jpl.nasa.gov/news/breaks-observed-in-rover-wheel-treads"),
    "putzig_ti": ("Putzig et al. 2005, global thermal inertia and surface properties of Mars from MGS TES",
                  "https://www.sciencedirect.com/science/article/abs/pii/S0019103504002957"),
    "golombek_slopes": ("Golombek et al., rover slope limits from landing-site work", "https://mars.asu.edu/christensen/docs/golombek_mersites_jgr.pdf"),
    "cushing_skylights": ("Cushing et al. 2007, possible cave skylights on Mars", "https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2007GL030709"),
    # --- science tools
    "allton_apollo_tools": ("Allton, catalog of Apollo geological sampling tools",
                            "https://repository-dev.hou.usra.edu/server/api/core/bitstreams/f74b6eee-9954-4c4b-9b3f-17f87af32348/content"),
    "kring_tools": ("Kring, geologic tools for the Moon", "https://www.lpi.usra.edu/science/kring/lunar_exploration/geologicTools.pdf"),
    "naids_artemis_tools": ("Naids et al., Artemis geology sampling tools",
                            "https://ntrs.nasa.gov/api/citations/20210000242/downloads/Developing%20Geology%20Sampling%20Tools_Lunar%20Surface%20Science%20Workshop_FINAL_2021.pdf"),
    "artemis3_sdt": ("Artemis III science definition report",
                     "https://science.nasa.gov/wp-content/uploads/2023/07/artemis-iii-science-definition-report-12042020c.pdf"),
    "mepag_human_sci": ("MEPAG human Mars mission science objectives",
                        "https://www.lpi.usra.edu/mepag/reports/reports/MHMSOTT-report-final.pdf"),
    "jpl_sample_tubes": ("JPL, Perseverance sample tubes", "https://www.jpl.nasa.gov/news/a-martian-roundtrip-nasas-perseverance-rover-sample-tubes/"),
    "leonardo_drill": ("Leonardo, ExoMars drill datasheet",
                       "https://space.leonardo.com/documents/16277711/19573930/ExoMars_LQ_mm07795_.pdf?t=1538987564303"),
    "ntrs_human_drill": ("NASA, human Mars surface science operations (drill mass)",
                         "https://ntrs.nasa.gov/api/citations/20140006398/downloads/20140006398.pdf"),
    "sehlke_instruments": ("Sehlke et al. 2019, portable instrument suites for human Mars exploration", "https://pmc.ncbi.nlm.nih.gov/articles/PMC6442242"),
    "beaton_basalt": ("Beaton et al. 2019, BASALT science operations concepts", "https://pmc.ncbi.nlm.nih.gov/articles/PMC6442237"),
    "bruker_tracer": ("Bruker TRACER handheld XRF specifications",
                      "https://www.bergeng.com/mm5/downloads/bruker/Bruker_TRACER_Specifications_Comparison.pdf"),
    "asd_halo": ("ASD TerraSpec Halo datasheet", "https://www.geopool.fi/wp-content/uploads/2022/01/asd-terraspec-halo-mineral-identifier.pdf"),
    "phoenix_raman": ("PHOENIX handheld Raman, LIBS and XRF (ESA)", "https://analyticalsciencejournals.onlinelibrary.wiley.com/doi/10.1002/jrs.6840"),
    "cospar_pp": ("COSPAR policy on planetary protection", "https://cosparhq.cnes.fr/assets/uploads/2024/07/PP-Policy_SRT_220-July-2024.pdf"),
    "neemo22": ("NEEMO 22 EVA overview and debrief", "https://www.nasa.gov/wp-content/uploads/2017/02/neemo_22_eva_overview_and_debrief_eva-exp-0054.pdf"),
    "desert_rats": ("Desert RATS 2010 field geology on EVA", "https://www.lpi.usra.edu/meetings/lpsc2011/pdf/1951.pdf"),
    # --- power, ISRU, construction
    "nasa_fsp": ("NASA fission surface power", "https://www.nasa.gov/exploration-systems-development-mission-directorate/fission-surface-power/"),
    "moxie_nasa": ("NASA, MOXIE completes its Mars mission",
                   "https://www.nasa.gov/missions/mars-2020-perseverance/perseverance-rover/nasas-oxygen-generating-experiment-moxie-completes-mars-mission/"),
    "moxie_sciadv": ("Hoffman et al. 2022, MOXIE, Science Advances", "https://pmc.ncbi.nlm.nih.gov/articles/PMC9432831/"),
    "ntrs_isru_plant": ("Kleinhenz and Paz, ISRU ascent-propellant plant", "https://ntrs.nasa.gov/citations/20170001421"),
    "swim_ice": ("JPL, SWIM subsurface water ice map", "https://www.jpl.nasa.gov/news/nasa-is-locating-ice-on-mars-with-this-new-map/"),
    "insight_dust": ("JPL, InSight solar-array dust cleaning", "https://www.jpl.nasa.gov/news/for-insight-dust-cleanings-will-yield-new-science/"),
    "iss_tools": ("ISS National Lab, tools in space", "https://issnationallab.org/iss360/innovation-in-focus-tools-in-space/"),
    "nasa_podcast_spares": ("NASA, Hazard 5: environments (spares and repair)", "https://www.nasa.gov/johnson/HWHAP/hazard-5-environments"),
    "nasa_3d_habitat": ("NASA 3D-printed habitat challenge",
                        "https://www.nasa.gov/prizes-challenges-and-crowdsourcing/centennial-challenges/3d-printed-habitat-challenge/"),
    # --- mission architecture and comms
    "dra5": ("NASA Mars Design Reference Architecture 5.0 (SP-2009-566)",
             "https://www.nasa.gov/wp-content/uploads/2015/09/373665main_nasa-sp-2009-566.pdf"),
    "m2m_2023": ("NASA Moon-to-Mars architecture definition 2023",
                 "https://ntrs.nasa.gov/api/citations/20230002706/downloads/M2MADD_ESDMD-001(TP-20230002706).pdf"),
    "hoffman_ez": ("Hoffman and Bussey 2016, Mars landing sites and surface operations", "https://ntrs.nasa.gov/citations/20160001040"),
    "mashal_ez": ("Mashal et al. 2025, exploration-zone screening", "https://iopscience.iop.org/article/10.3847/PSJ/ade30e"),
    "mars_relay": ("NASA Mars Relay Network", "https://science.nasa.gov/mars/mars-relay-network/"),
    "ascend_delay": ("ASCEND 2022, Mars communication delays and blackouts", "https://ntrs.nasa.gov/citations/20220013418"),
    "lynch_logistics": ("Lynch et al., logistics rates beyond low Earth orbit",
                        "https://ntrs.nasa.gov/api/citations/20230012635/downloads/Logistics%20Rates%20and%20Assumptions%20Beyond%20LEO%20V5.pdf"),
}


def source(sid):
    title, url = SOURCES[sid]
    return {"id": sid, "title": title, "url": url}


def sources(ids):
    return [source(s) for s in ids]
