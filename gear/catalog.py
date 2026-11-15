"""
The gear catalog: every item a Mars crew might be told to bring.

Rules of the road for editing this file
  - Only write a mass, power or rate you can point at a source for. Leave it None otherwise.
    The kit totals then say "mass not published" instead of quietly using a guess.
  - `conf` describes the evidence for the item's SPECIFICATION (its mass, rate, size), using the tags
    in sources.py. An item can be clearly needed and still be conf "N" because nobody has published
    what it should be.
  - `eva_carry` is how many units a two-person EVA team carries on one outing. It drives the
    carry-load check. 0 means the item lives at the base or on a vehicle.
  - `carried_by` is the default carrier. The engine moves hand-carried items onto a rover when the
    team's carry cap is exceeded or the traverse is by crewed rover.
"""
from dataclasses import asdict, dataclass, field
from typing import Optional

from .sources import CONFIDENCE, SOURCES

CATEGORIES = [
    ("life_support", "Suit and life support"),
    ("consumables", "Consumables"),
    ("mobility", "Vehicles and traverse gear"),
    ("sampling", "Sampling and field tools"),
    ("instruments", "Instruments"),
    ("drilling", "Drilling and subsurface"),
    ("power_isru", "Power and resource production"),
    ("shelter", "Shelter, radiation and habitat"),
    ("medical", "Medical and exercise"),
    ("comms_nav", "Communications and navigation"),
    ("safety", "Safety and rescue"),
    ("maintenance", "Repair and construction"),
]
CATEGORY_LABEL = dict(CATEGORIES)
CARRIERS = ("worn", "astronaut", "rover", "base", "deployed")


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    category: str
    summary: str                      # one line: what it is for
    carried_by: str = "astronaut"
    per: str = "team"                 # how default quantity scales: astronaut | team | mission
    eva_carry: float = 0.0            # units one EVA team carries per outing (hand-carried items only)
    mass_kg: Optional[float] = None
    mass_basis: str = "unknown"       # published | analog (Apollo/lunar/ISS value) | derived | unknown
    power_w: Optional[str] = None     # text: a number or a range, with its basis
    rate: Optional[str] = None        # consumption or capability, with units
    planner_vehicle: Optional[str] = None  # key in config.VEHICLES when the item IS a planner vehicle
    conf: str = "I"
    sources: tuple = ()
    note: str = ""                    # caveats, conflicts, why the number is what it is
    tags: tuple = ()

    def public(self):
        d = asdict(self)
        d["category_label"] = CATEGORY_LABEL[self.category]
        d["confidence"] = {"tag": self.conf, **CONFIDENCE[self.conf]}
        d["sources"] = [{"id": s, "title": SOURCES[s][0], "url": SOURCES[s][1]} for s in self.sources]
        d.pop("conf")
        return d


_ITEMS = []


def _i(id, name, category, summary, **kw):
    assert category in CATEGORY_LABEL, category
    assert kw.get("carried_by", "astronaut") in CARRIERS
    assert all(s in SOURCES for s in kw.get("sources", ())), id
    _ITEMS.append(Item(id=id, name=name, category=category, summary=summary, **kw))


# ---------------------------------------------------------------- suit and life support
_i("suit_pgs", "EVA suit with life-support backpack", "life_support",
   "Pressure garment plus portable life support, one per crew member.",
   carried_by="worn", per="astronaut", mass_kg=177.0, mass_basis="analog", conf="E",
   sources=("ices2026_mars_suit",), tags=("eva",),
   note="xEMU is just under 400 lbm (391 lbm in the paper). NASA's 2026 study calls it not workable on Mars at "
        "that mass and recommends about 230 lbm (about 104 kg) as a starting maximum for a Mars suit.")
_i("suit_backup_o2", "Emergency oxygen supply", "life_support",
   "Backup breathing gas if the primary supply fails.",
   carried_by="worn", per="astronaut", conf="P", sources=("wiki_emu",), tags=("eva", "contingency"),
   note="The ISS suit carries a 30 minute backup. No Mars figure is published.")
_i("suit_spares", "Suit spares and repair kit", "life_support",
   "Parts and tools to keep suits working across many EVAs.",
   carried_by="base", per="mission", conf="N", sources=("ices2026_mars_suit",), tags=("eva",),
   note="No Mars spare counts are published. NASA's Mars PLSS plan assumes a first short-stay mission with up to "
        "25 EVAs per suit, which gives a sense of the wear involved.")
_i("suit_battery", "Suit battery set", "life_support",
   "Powers fans, pumps, comms and displays for the EVA.",
   carried_by="worn", per="astronaut", conf="E", sources=("emu_databook",),
   power_w="about 64 W average (ISS suit: 3.8 A at 16.8 V)", rate="about 447 Wh for a 7 h EVA (ISS suit)",
   note="Both figures are for the ISS suit. xEMU and AxEMU battery capacity is not public.")
_i("suit_thermal", "Cold-weather suit insulation and heaters", "life_support",
   "Keeps the suit warm where ordinary insulation is not enough.",
   carried_by="worn", per="astronaut", conf="I", sources=("sbir_mars_plss",), tags=("cold",),
   note="NASA states that isolating the crew from the Mars thermal environment may not be possible "
        "(0.09 to 0.17 psia, down to -220 F). No heater specification is published.")
_i("suit_dust_removal", "Suit dust-removal and wash-down tools", "life_support",
   "Clean the suit before it enters the habitat.",
   carried_by="base", per="mission", conf="P", sources=("nasa_dust_pel", "nasa_perseverance_dust"), tags=("dust",),
   note="NASA's dust standard expects prompt pre-entry suit cleaning and fast air turnover. "
        "Fine and ultrafine dust (about 100 nm) sticks to suit-like fabric.")
_i("suitport", "Suitport or dual-chamber airlock", "life_support",
   "Keeps dust out of the cabin on every ingress.",
   carried_by="base", per="mission", conf="P", sources=("nasa_perseverance_dust",), tags=("dust",),
   note="NASA suggests suitports and dual-chamber airlocks on the basis of the Perseverance dust findings.")
_i("helmet_lamp", "Helmet and tool lighting", "life_support",
   "Light for shadowed terrain, pits and work near dawn or dusk.",
   carried_by="worn", per="astronaut", conf="I", sources=("nasa_suits_rovers",), tags=("shadow", "cave"),
   note="NASA names challenging lighting in shadowed regions as a design driver for lunar suits. No lamp spec for Mars.")
_i("eva_display", "Electronic procedures and heads-up display", "life_support",
   "Step-by-step procedures and suit status without waiting on Earth.",
   carried_by="worn", per="astronaut", conf="P", sources=("orion_crew", "ascend_delay"), tags=("autonomy",),
   note="Orion's electronic procedures are reported to reduce crew workload. One-way delay to Mars is 3 to 22 minutes.")

# ---------------------------------------------------------------- consumables
_i("c_suit_o2", "Suit oxygen", "consumables",
   "Breathing gas for every EVA hour, sized from the NASA Mars design rate.",
   carried_by="worn", per="astronaut", conf="V", sources=("sbir_mars_plss", "bvad2", "norcross_walkback"),
   rate="0.114 kg/h design (V), 0.076 kg/h current EVA (E), 0.181 kg/h walk-back (E)",
   note="0.114 kg/h is 1.9 g/min averaged over 8 h, from a NASA sizing requirement. It may include margin, "
        "so it is a design rate, not a measured one.")
_i("c_suit_water", "Suit drinking water", "consumables",
   "Hydration in the suit.", carried_by="worn", per="astronaut", conf="V", sources=("std3001_v2_s11",),
   rate="at least 0.24 kg per EVA hour (240 mL)")
_i("c_suit_cooling", "Suit cooling water", "consumables",
   "Evaporated to reject heat.", carried_by="worn", per="astronaut", conf="E", sources=("chappell_eva",),
   rate="Apollo: 0.44 kg/h nominal, 1.41 kg/h walk-back",
   note="Apollo-era figures. The Mars PLSS uses a different cooling approach and its water mass is not published.")
_i("c_eva_food", "In-suit nutrition", "consumables",
   "Food bar or drink for long EVAs.", carried_by="worn", per="astronaut", conf="P", sources=("std3001_v2_s11",),
   note="The standard calls for nutrition on surface EVAs longer than 4 hours. A 10 km walk-back used about 944 kcal.")
_i("c_cabin", "Cabin consumables (oxygen, water, food, hygiene, clothing)", "consumables",
   "Daily life support for every crew member for the whole stay.",
   carried_by="base", per="mission", conf="P", sources=("frontiers_bvad", "lynch_logistics"),
   rate="per crew member per day: O2 0.818 kg, water 4.350 kg, food 1.831 kg as shipped, hygiene 0.781 kg, clothing 0.22 kg",
   note="Values are from an older revision of the NASA baseline document, quoted in a 2025 review. "
        "See the consumables budget for the arithmetic.")
_i("c_personal", "Personal items allowance", "consumables",
   "Clothing, personal effects and small supplies, stepped by mission length.",
   carried_by="base", per="astronaut", conf="E", sources=("lynch_logistics",),
   rate="5 kg (0 to 14 days), 10 kg (15 to 60), 25 kg (61 to 360), 50 kg (361 to 1100) per crew member")

# ---------------------------------------------------------------- vehicles and traverse gear
_i("v_pressurized_rover", "Pressurized crew rover", "mobility",
   "A shirt-sleeve vehicle that carries the team out, serves as shelter and extends walk-back range.",
   carried_by="rover", per="mission", planner_vehicle="pressurized_rover", conf="P",
   sources=("nasa_mars_pr", "wiki_sev", "nasa_moonbase"),
   rate="SEV concept: 10 km/h, 125 km, up to 14 days, 2 crew (4 in emergency)",
   mass_kg=5193.0, mass_basis="published",
   note="Concept stage only. NASA's Mars pressurized rover study (Chappell et al. 2022) gives 5,193 kg with a "
        "60 kWh battery and a 1.85 kW hotel load, and keeps crewed traverses within about 20 km of the landing "
        "site. NASA's lunar pages list a 15 degree slope limit for a pressurized rover.")
_i("v_unpressurized_rover", "Open crew rover (Apollo LRV-class)", "mobility",
   "Open vehicle for two suited crew and a tool load over short distances.",
   carried_by="rover", per="mission", planner_vehicle="unpressurized_rover", conf="P",
   sources=("wiki_lrv", "costes_lrv", "dra5"),
   mass_kg=210.0, mass_basis="analog", rate="about 8.7 kWh of batteries, 92 km range, design top speed 10 km/h",
   note="Apollo figures; the crew still breathe from their suits. DRA 5.0 proposes open rovers roughly like the "
        "Apollo LRV for Mars. Tested on 18 to 23 degree slopes, specified to 25.")
_i("v_sojourner", "Sojourner-class micro-rover", "mobility",
   "An 11.5 kg scout that stays close to its lander.",
   carried_by="rover", per="mission", planner_vehicle="sojourner", conf="P", sources=("wiki_sojourner",),
   mass_kg=11.5, mass_basis="published", rate="top speed 1 cm/s; 13 to 15 W solar plus a 150 Wh battery",
   note="Mars Pathfinder, 1997. It kept within about 500 m of the lander for radio contact.")
_i("v_mer", "Spirit / Opportunity-class rover", "mobility",
   "A solar rover; Opportunity drove 45 km over 14 years.",
   carried_by="rover", per="mission", planner_vehicle="mer", conf="P", sources=("wiki_mer", "wiki_opportunity"),
   mass_kg=185.0, mass_basis="published", rate="top speed 5 cm/s; about 900 Wh per sol early, about 100 W to drive",
   note="Both rovers were stopped by terrain or dust: Spirit in soft sand at Troy in 2009, Opportunity by the 2018 "
        "global dust storm.")
_i("v_zhurong", "Zhurong-class rover", "mobility",
   "A solar rover with active suspension that can inch out of sand.",
   carried_by="rover", per="mission", planner_vehicle="zhurong", conf="P", sources=("zhurong_xinhua", "wiki_zhurong"),
   mass_kg=240.0, mass_basis="published", rate="about 200 m/h top speed; slopes up to 20 degrees",
   note="Tianwen-1, 2021, Utopia Planitia. Drove 1,921 m before dust stopped it. Its energy budget is not published.")
_i("v_rosalind_franklin", "Rosalind Franklin (ExoMars)", "mobility",
   "Solar rover with a 2 m drill, planned to launch in 2028.",
   carried_by="rover", per="mission", planner_vehicle="rosalind_franklin", conf="P",
   sources=("esa_rfm_faq", "wiki_rfm", "leonardo_drill"),
   mass_kg=310.0, mass_basis="published", rate="100 m/h straight-line; about 1,200 Wh per sol",
   note="Not yet flown. Can wheel-walk out of loose soil. ESA lists 15 degrees on bedrock and about 20 as the worst case.")
_i("v_perseverance", "Perseverance-class robotic rover", "mobility",
   "A robotic scout or precursor that surveys a site before people walk it.",
   carried_by="rover", per="mission", planner_vehicle="perseverance", conf="P", sources=("nasa_rover_page", "cospar_pp"),
   mass_kg=1025.0, mass_basis="published", rate="top speed about 152 m/h; avoid tilts over 30 degrees",
   note="Perseverance itself is operating in Jezero. COSPAR guidance calls for robotic precursors before crew "
        "reach an uncharacterised site.")
_i("v_small_rover", "Curiosity-class robotic rover", "mobility",
   "Smaller robotic support vehicle on radioisotope power.",
   carried_by="rover", per="mission", planner_vehicle="small_rover", conf="P", sources=("nasa_rover_page",),
   rate="MMRTG about 110 W electrical",
   note="Same drivetrain heritage as Perseverance. Energy figures are the MMRTG ones already in the planner.")
_i("m_hand_cart", "Hand-pulled equipment cart", "mobility",
   "Carries tools and samples so they are not on the astronaut's back.",
   carried_by="astronaut", per="team", eva_carry=1, conf="P", sources=("wiki_met",),
   mass_kg=13.6, mass_basis="analog", rate="payload up to about 154 kg",
   note="Apollo equipment transporter: empty weight at most 30 lb, payload at most 340 lb.")
_i("m_traction_aids", "Traction aids for soft sand", "mobility",
   "Planks, mats or wide footplates for crossing a short soft patch.",
   carried_by="rover", per="mission", conf="I", sources=("purgatory_dune", "jpl_spirit_trap"), tags=("sand",),
   note="No published crew equipment. The evidence is vehicle entrapments: Opportunity dug over 10 cm into a ripple "
        "and was stuck about 5.5 weeks; Spirit broke through a crust and never got free.")
_i("m_recovery_gear", "Vehicle recovery gear (line, winch, anchors)", "mobility",
   "Gets a stuck vehicle out without a second vehicle.",
   carried_by="rover", per="mission", conf="I", sources=("purgatory_dune", "jpl_spirit_trap"), tags=("sand",),
   note="No published spec. The need follows from the two entrapments above.")
_i("m_probe", "Ground probe or penetrometer", "mobility",
   "Test a crust before stepping or driving on it.",
   carried_by="astronaut", per="team", eva_carry=1, conf="P", sources=("wiki_met", "jpl_spirit_trap"), tags=("sand",),
   note="The Apollo equipment cart carried a penetrometer. Spirit's loss came from a crust over soft sand.")
_i("m_climbing_kit", "Rope, anchor and ascender set", "mobility",
   "For slopes and drops where walking is not safe.",
   carried_by="astronaut", per="team", eva_carry=1, conf="N", tags=("slope", "cliff"),
   note="No published Mars crew climbing equipment was found. Included because the terrain data can flag slopes "
        "beyond rover limits.")
_i("m_tether_lines", "Tethers and short rope set", "mobility",
   "Keep a team linked on slopes or near edges.",
   carried_by="astronaut", per="team", eva_carry=1, conf="I", sources=("iss_tools",), tags=("slope",),
   note="ISS tethers are a microgravity heritage item. Mars use is an inference.")
_i("m_aerial_scout", "Aerial scout (Ingenuity class)", "mobility",
   "Looks at ripple fields, cliffs and pits before anyone commits.",
   carried_by="rover", per="mission", conf="P", sources=("jpl_ingenuity",),
   mass_kg=1.8, mass_basis="published", rate="flights up to 90 s, 12 m maximum altitude, 72 flights",
   note="Ingenuity lost navigation over smooth ripples on its last flight, so it is not a substitute for ground checks.")
_i("m_spare_wheels", "Spare wheels or tyres", "mobility",
   "For vehicles crossing sharp rock.",
   carried_by="rover", per="mission", conf="I", sources=("jpl_curiosity_wheels",), tags=("rock",),
   note="Curiosity wheel damage: three broken grousers is about 60 percent of useful wheel life.")
_i("m_field_cache", "Field cache (life support, power, emergency shelter)", "mobility",
   "A pre-placed supply point that extends how far a team can go.",
   carried_by="deployed", per="mission", conf="E", sources=("dra5",),
   note="DRA 5.0 describes caches for life support, power and emergency habitation along traverses.")

# ---------------------------------------------------------------- sampling and field tools
_i("g_hammer", "Geology hammer", "sampling", "Break chips from rock and drive core tubes.",
   eva_carry=1, mass_kg=1.3, mass_basis="analog", conf="E", sources=("allton_apollo_tools", "kring_tools"),
   note="Apollo 14 to 17 hammer, 1,300 g. The lighter Apollo 11 and 12 hammer (860 g) could not drive tubes well.")
_i("g_tongs", "Tongs", "sampling", "Pick up small rocks without bending in the suit.",
   eva_carry=1, mass_kg=0.23, mass_basis="analog", conf="E", sources=("kring_tools", "allton_apollo_tools"),
   note="Apollo 15 to 17 tongs, 230 g. One flight list shows 454 g, so the mass is uncertain.")
_i("g_scoop", "Scoop", "sampling", "Take loose soil.", eva_carry=1, mass_kg=0.59, mass_basis="analog",
   conf="E", sources=("kring_tools",), note="Apollo large adjustable scoop.")
_i("g_rake", "Rake", "sampling", "Collect pebbles over 1 cm and leave the fines.", eva_carry=1,
   mass_kg=1.5, mass_basis="analog", conf="E", sources=("kring_tools", "allton_apollo_tools"))
_i("g_drive_tube", "Drive tube with caps and rammer", "sampling", "Soil core to about 70 cm.",
   eva_carry=2, mass_kg=0.5, mass_basis="analog", conf="E", sources=("kring_tools",),
   note="Apollo 4 cm tube (300 g), caps (110 g) and ram (90 g) summed. Quantity carried per outing is a planning choice.")
_i("g_handle", "Extension handle", "sampling", "One shaft shared by hammer, scoop, rake and tubes.",
   eva_carry=1, mass_kg=0.82, mass_basis="analog", conf="E", sources=("kring_tools",))
_i("g_gnomon", "Gnomon and scale", "sampling", "Gives scale, colour and orientation in every photograph.",
   eva_carry=1, mass_kg=0.272, mass_basis="analog", conf="E", sources=("allton_apollo_tools",))
_i("g_scale", "Sample balance", "sampling", "Weigh samples so the return mass limit is tracked.",
   carried_by="base", per="mission", mass_kg=0.227, mass_basis="analog", conf="E",
   sources=("allton_apollo_tools", "artemis3_sdt"),
   note="Artemis weighs samples after each EVA. Its candidate sample program is 83 kg against a 64 kg Apollo average.")
_i("g_tool_carrier", "Tool carrier for a vehicle", "sampling", "Holds the hand tools on a rover so people carry less.",
   carried_by="rover", per="mission", mass_kg=8.029, mass_basis="analog", conf="E", sources=("allton_apollo_tools",),
   note="Apollo 16 large tool carrier.")
_i("g_hand_lens", "Hand lens", "sampling", "Quick look at grain and texture before choosing a sample.",
   eva_carry=1, conf="E", sources=("desert_rats",),
   note="No hand lens was carried in Desert RATS 2010 and the crew wanted one. Mass not published.")
_i("g_bags", "Sample bags and dispensers", "sampling", "Individually numbered bags in more than one size.",
   eva_carry=1, conf="E", sources=("allton_apollo_tools", "desert_rats"),
   note="Apollo 17 flew eight 20-bag dispensers and 48 round bags. In Desert RATS one size did not fit large hard rocks.")
_i("g_sealed_tubes", "Sealed sample tubes", "sampling", "Hermetic tubes for samples that must stay intact.",
   carried_by="astronaut", per="mission", eva_carry=8, mass_kg=0.057, mass_basis="published", conf="P",
   sources=("jpl_sample_tubes",),
   note="Perseverance tube: titanium, under 57 g, under 15.2 cm. The BASALT protocol took 7 samples per site. "
        "Eight per outing is a planning figure.")
_i("g_witness_tubes", "Witness (blank) tubes", "sampling", "Open and close with nothing in them, to show what contamination arrived.",
   carried_by="astronaut", per="mission", eva_carry=1, mass_kg=0.057, mass_basis="published", conf="P",
   sources=("jpl_sample_tubes",), tags=("sterile",),
   note="Perseverance carried 5 witness tubes among 43.")
_i("g_sterile_kit", "Sterile sampling tools and gloves", "sampling", "Clean-handling kit for biosignature sampling.",
   eva_carry=1, conf="P", sources=("beaton_basalt", "jpl_sample_tubes"), tags=("sterile",),
   note="BASALT crews avoided touching a candidate site before sampling. Sterile sampling took longer. Mass not published.")
_i("g_swabs", "Glove and tool swabs", "sampling", "Track contamination carried between sites.",
   eva_carry=1, conf="P", sources=("beaton_basalt",), tags=("sterile",))
_i("g_markers", "Sample markers and scale bars", "sampling", "Let the crew and the science team agree on exactly what was sampled.",
   eva_carry=1, conf="P", sources=("beaton_basalt",),
   note="BASALT found temporary markers essential for crew and science-team communication.")
_i("g_camera", "Scientific stills camera", "sampling", "High-resolution stills of every sample and outcrop.",
   eva_carry=1, conf="P", sources=("beaton_basalt",),
   note="BASALT found stills more useful than helmet video.")
_i("g_vacuum_container", "Vacuum-sealed sample container", "sampling", "Keep volatiles from escaping.",
   carried_by="astronaut", per="mission", eva_carry=1, conf="E", sources=("naids_artemis_tools", "artemis3_sdt"))
_i("g_contact_sampler", "Contact soil sampler", "sampling", "Lift the undisturbed top layer.",
   eva_carry=1, conf="E", sources=("artemis3_sdt",))
_i("g_chisel", "Chisel and slide hammer", "sampling", "Extra ways to take rock and core.",
   eva_carry=1, conf="E", sources=("naids_artemis_tools",))
_i("g_hand_drill", "Hand-held powered core drill", "sampling", "Short rock cores without a vehicle-mounted drill.",
   eva_carry=1, conf="E", sources=("naids_artemis_tools",),
   note="On Artemis's proposed tool list. Mass and power not published.")
_i("g_stabilizer", "Sampling stabiliser (boom or foot restraint)", "sampling",
   "Gives a suited person something to push against while drilling.",
   eva_carry=1, conf="E", sources=("neemo22",),
   note="Low gravity limits how hard a crew member can press down. A breakaway core bit worked in NEEMO 22.")

# ---------------------------------------------------------------- instruments
_i("i_hand_nir", "Handheld near-infrared spectrometer", "instruments", "Identifies mineral groups in about 15 seconds.",
   eva_carry=1, mass_kg=2.5, mass_basis="published", conf="E", sources=("asd_halo", "sehlke_instruments"),
   power_w="16.5 W", note="ASD TerraSpec Halo with battery. Sunlight contaminated scans at a 10 mm gap in BASALT.")
_i("i_hand_xrf", "Handheld X-ray fluorescence analyser", "instruments", "Elemental composition in about 30 seconds.",
   eva_carry=1, mass_kg=2.0, mass_basis="published", conf="E", sources=("bruker_tracer", "sehlke_instruments"),
   power_w="about 4 W tube", note="Bruker TRACER IV-SD. Sodium and magnesium are weak. Quality dropped with gaps over 4 mm.")
_i("i_hand_raman", "Handheld Raman spectrometer", "instruments", "Organic and mineral identification.",
   eva_carry=1, conf="E", sources=("phoenix_raman",),
   note="ESA's PHOENIX combines Raman, LIBS and XRF for astronaut training. Mass and power not published.")
_i("i_gpr", "Ground-penetrating radar", "instruments", "Looks for buried layers, ice and voids.",
   carried_by="rover", per="mission", mass_kg=3.0, mass_basis="published", conf="P", sources=("nasa_rimfax",),
   power_w="5 to 10 W", rate="at least 10 m depth, 15 to 30 cm resolution",
   note="Figures are for RIMFAX on Perseverance. A crew-portable radar was not found.")
_i("i_weather", "Weather station", "instruments", "Wind, pressure, humidity and temperature at several heights.",
   carried_by="deployed", per="mission", mass_kg=5.5, mass_basis="published", conf="P", sources=("mepag_human_sci",),
   note="MEDA-class, about 5.5 kg. MEPAG's science objectives ask for four or more locations.")
_i("i_dosimeter_area", "Area radiation monitor", "instruments", "Dose and dose rate at the base, and the storm alarm sensor.",
   carried_by="base", per="mission", mass_kg=1.56, mass_basis="published", conf="P", sources=("srag", "swri_rad"),
   power_w="4.2 W", note="RAD-class. Measured surface dose equivalent was 0.67 mSv per day.")
_i("i_dosimeter_personal", "Personal dosimeter", "instruments", "Each crew member's running dose.",
   carried_by="worn", per="astronaut", conf="P", sources=("srag", "std3001_v2_s11"),
   note="The suit standard requires the suit to provide or accommodate radiation monitors.")
_i("i_seismometer", "Seismometer", "instruments", "Interior structure and ground-motion monitoring.",
   carried_by="deployed", per="mission", conf="E", sources=("mepag_human_sci",),
   note="SEIS mass is reported anywhere from 3 kg to 29.5 kg depending on source, so none is used here.")
_i("i_thermal_cam", "Handheld thermal camera", "instruments", "Surface temperature and thermal-inertia hints.",
   eva_carry=1, conf="P", sources=("beaton_basalt",), note="BASALT used a FLIR E60. Mass not published.")
_i("i_air_monitor", "Habitat dust and air-quality monitor", "instruments", "Checks the cabin against the dust limit.",
   carried_by="base", per="mission", conf="P", sources=("wang_dust", "nasa_dust_pel"), tags=("dust",),
   note="NASA's draft limit is 0.1 mg/m3 as a 24 h average for stays up to 30 days.")

# ---------------------------------------------------------------- drilling
_i("d_drill_2m", "Drill reaching 2 m", "drilling", "Subsurface samples below the radiation-damaged top layer.",
   carried_by="rover", per="mission", mass_kg=21.0, mass_basis="published", conf="E", sources=("leonardo_drill",),
   power_w="80 W", rate="2 m depth, 10 mm by 30 mm samples", note="ExoMars Rosalind Franklin drill.")
_i("d_drill_deep", "Deep drill rig", "drilling", "Tens to hundreds of metres, for ice and subsurface science.",
   carried_by="base", per="mission", mass_kg=1000.0, mass_basis="published", conf="E",
   sources=("ntrs_human_drill", "dra5"),
   note="DRA 5.0 allows 1,000 kg of drilling equipment. Studies range from 700 to 2,200 kg. Depth targets "
        "range from about 10 m to 1,000 m depending on the study.")
_i("d_ice_system", "Ice extraction system", "drilling", "Melt or mine subsurface ice for water.",
   carried_by="base", per="mission", conf="E", sources=("swim_ice", "ntrs_isru_plant"), tags=("ice",),
   note="NASA has evaluated the Rodriguez well approach for Mars. Mid-latitude ice is mapped within about 1 m of the surface.")

# ---------------------------------------------------------------- power and ISRU
_i("p_fission", "Fission surface power plant", "power_isru", "Power that does not depend on sun or dust.",
   carried_by="base", per="mission", mass_kg=6000.0, mass_basis="published", conf="P", sources=("nasa_fsp",),
   power_w="40 kWe class", note="Reactor under 6 tonnes, 10 years unattended. A newer directive is reported to ask for at "
   "least 100 kWe for long-term operations including ISRU, but it could not be opened.")
_i("p_solar", "Solar array", "power_isru", "Daytime power; needs a dust plan.",
   carried_by="base", per="mission", conf="P", sources=("insight_dust",),
   note="Typical dust loss about 0.2 percent per sol (observed 0.05 to 2). InSight output fell about 30 percent after landing.")
_i("p_array_cleaning", "Array dust-cleaning tools", "power_isru", "Restore array output after dust settles.",
   carried_by="base", per="mission", conf="E", sources=("insight_dust",), tags=("dust",))
_i("p_storm_storage", "Storm-season energy storage", "power_isru", "Carry the base through weeks of blocked sun.",
   carried_by="base", per="mission", conf="I", sources=("insight_dust",),
   note="The 2018 global dust storm halted Opportunity. No published threshold for sizing storage.")
_i("p_cable", "Power cable reels and connectors", "power_isru", "Link the power plant to the habitat and ISRU.",
   carried_by="base", per="mission", conf="N", note="One study mentions over 1,000 kg of cable for a remote power layout. Context not verified.")
_i("r_oxygen_plant", "Oxygen plant (scaled MOXIE type)", "power_isru", "Makes breathing and ascent oxygen from the atmosphere.",
   carried_by="base", per="mission", conf="P", sources=("moxie_nasa", "moxie_sciadv"),
   rate="MOXIE peak 12 g/h at 98 percent purity; scale-up target 2 to 3 kg/h",
   power_w="MOXIE 300 W; scaled plant 18 to 30 kW (sources disagree)",
   note="MOXIE made 122 g over 16 runs. A scaled plant could produce enough ascent oxygen over one 26-month cycle.")
_i("r_excavator", "Autonomous excavator", "power_isru", "Moves regolith for ISRU feedstock and shielding.",
   carried_by="base", per="mission", conf="E", sources=("ntrs_isru_plant",),
   note="NASA's exploration-zone study expects mining to run automatically, likely when no crew are present.")
_i("r_water_test", "Water quality test kit", "power_isru", "Confirms extracted water is safe.",
   carried_by="base", per="mission", conf="I", sources=("hoffman_ez",), tags=("ice",),
   note="NASA's zone criteria assume a deposit able to yield over 100 tonnes of water. No test-kit spec exists.")
_i("r_shielding", "Regolith shielding (excavate and pile)", "power_isru", "Extra radiation protection for a long stay.",
   carried_by="base", per="mission", conf="P", sources=("gakis_shield",),
   note="10 g/cm2 of regolith cut galactic dose about 28 percent. About 0.8 to 2.5 m is cited for a 100 mSv per year target.")

# ---------------------------------------------------------------- shelter, radiation, habitat
_i("h_storm_shelter", "Radiation storm shelter", "shelter", "Somewhere to wait out a solar particle event.",
   carried_by="base", per="mission", conf="V", sources=("std3001_v1_s4",),
   rate="10 g/cm2 water-equivalent around the crew member on the surface, any duration",
   note="The 15 and 20 g/cm2 values in the same table appear to apply to vehicles in space, not the surface.")
_i("h_spe_alarm", "Radiation alarm independent of Earth comms", "shelter", "Warns of a solar particle event while people are outside.",
   carried_by="base", per="mission", conf="V", sources=("lowe2025", "srag"),
   rate="trigger at 25 percent above the 5-day background; gives at least about 30 minutes",
   note="The 30 minute figure is one 2025 paper's finding, not a NASA requirement.")
_i("h_portable_shelter", "Shelter at the remote work site", "shelter", "Cover close to where the team is working.",
   carried_by="rover", per="mission", conf="I", sources=("lowe2025",),
   note="Inference from the 30 minute finding. No portable shelter spec is published.")
_i("h_hepa", "Habitat HEPA filtration", "shelter", "Remove fine dust from cabin air.",
   carried_by="base", per="mission", conf="P", sources=("nasa_dust_pel", "wang_dust"), tags=("dust",),
   note="Mars dust averages about 3 micrometres; particles under 5 micrometres are not cleared by the lungs.")
_i("b_habitat", "Surface habitat", "shelter", "Living and working space for a long stay.",
   carried_by="base", per="mission", conf="E", sources=("dra5",),
   note="DRA 5.0 surface habitat supports the crew for up to about 550 days. Not needed on a 30 sol stay where the rover is the habitat.")
_i("b_exercise", "Exercise hardware", "medical", "Resistive device, cycle ergometer and treadmill against bone and muscle loss.",
   carried_by="base", per="mission", conf="P", sources=("std3001_v1_s4",),
   note="The standard asks for at least 95 percent of baseline bone density at hip and spine.")

# ---------------------------------------------------------------- medical
_i("med_core", "Medical kit (prime, secondary, accessory)", "medical", "Medications, wound care and procedures for first response.",
   carried_by="base", per="mission", conf="P", sources=("orion_crew", "std3001_s3"),
   note="Orion's kit covers 128 medical conditions with 139 resources and is the best published model.")
_i("med_pill_tool", "In-suit pill delivery tool", "medical", "Medication through the helmet drink port.",
   carried_by="worn", per="astronaut", conf="P", sources=("orion_crew",))
_i("med_oxygen", "Medical oxygen", "medical", "Treatment gas for illness or decompression sickness.",
   carried_by="base", per="mission", conf="P", sources=("orion_crew", "std3001_s3"))
_i("med_diagnostics", "Vital-sign, ECG, oximetry and ultrasound set", "medical", "Diagnose without a doctor on site.",
   carried_by="base", per="mission", conf="P", sources=("orion_crew", "std3001_s3"),
   note="Autonomous care is required: one-way delay to Earth is 3 to 22 minutes and can black out for days.")
_i("med_iv", "IV fluid generation", "medical", "Make intravenous fluid on site for long missions.",
   carried_by="base", per="mission", conf="P", sources=("std3001_s3",))
_i("med_dental", "Limited dental care", "medical", "Treat tooth and mouth emergencies.",
   carried_by="base", per="mission", conf="P", sources=("orion_crew",))
_i("med_ki", "Potassium iodide", "medical", "Protects the thyroid from perchlorate exposure.",
   carried_by="base", per="mission", conf="P", sources=("wang_dust", "hecht_perchlorate"), tags=("dust",),
   note="Proposed in the literature, not a NASA requirement. Perchlorate is about 0.5 to 1 percent of soil.")
_i("med_advanced", "Advanced life support and autonomous care capability", "medical",
   "Definitive care on site, because return to Earth is not an option.",
   carried_by="base", per="mission", conf="P", sources=("std3001_s3",))

# ---------------------------------------------------------------- communications and navigation
_i("n_relay_link", "Link to the Mars Relay Network", "comms_nav", "Reaches Earth through orbiters.",
   carried_by="base", per="mission", conf="P", sources=("mars_relay",),
   note="Four orbiters; rover data up to 2 Mbps. Rovers lack Earth line of sight about 12 hours a day.")
_i("n_suit_radio", "Suit radio", "comms_nav", "Voice and data between suits, vehicles and base.",
   carried_by="worn", per="astronaut", conf="N", note="No suit radio range was published.")
_i("n_relay_beacon", "Relay beacons dropped on a traverse", "comms_nav", "Keep line of sight over hills and crater walls.",
   carried_by="rover", per="mission", conf="N", sources=("mars_relay",), tags=("terrain",),
   note="No published beacon spec. A 1.5 m antenna sees about 3.2 km on a smooth sphere, so about 6.4 km between "
        "two such antennas, and far less behind terrain.")
_i("n_nav_aid", "Surface navigation aid (no GPS)", "comms_nav", "Position and heading without satellites.",
   carried_by="rover", per="mission", conf="N", sources=("costes_lrv",),
   note="The Apollo rover used a gyro, an odometer and a sun-shadow heading device. No Mars crew system is published.")
_i("n_beacon", "Personal locator beacon", "comms_nav", "Lets a base find a crew member who cannot call.",
   carried_by="worn", per="astronaut", conf="N", note="No Mars beacon specification was found.")

# ---------------------------------------------------------------- safety and rescue
_i("f_icr", "Incapacitated-crew rescue hardware", "safety", "Move a crew member who cannot move themselves.",
   carried_by="rover", per="mission", conf="P", sources=("std3001_v2_s11",),
   note="The suit standard requires a rescue capability. Hardware is not specified for Mars.")
_i("f_fire", "Fire extinguishers", "safety", "Put out a cabin or vehicle fire.",
   carried_by="base", per="mission", conf="N", sources=("std6001",),
   note="A materials-flammability standard exists. No Mars-specific suppression system was found.")

# ---------------------------------------------------------------- repair and construction
_i("x_eva_tools", "EVA tool set (power driver, foot restraint, tethers)", "maintenance", "General repair on suits, vehicles and equipment.",
   carried_by="base", per="mission", conf="P", sources=("iss_tools",),
   note="ISS heritage: pistol grip tool, manipulator foot restraint, safety tether, grease gun.")
_i("x_spares", "Spares and replaceable units", "maintenance", "Replace parts when nothing can be resupplied.",
   carried_by="base", per="mission", conf="P", sources=("nasa_podcast_spares",),
   note="ISS can get parts in about six weeks. Mars has none in transit, and NASA notes a third of mission mass cannot be spares.")
_i("x_printer", "3D printer for repair parts", "maintenance", "Make small parts and tools on site.",
   carried_by="base", per="mission", conf="P", sources=("iss_tools",),
   note="A 3D-printed multi-purpose precision tool is aboard the ISS.")
_i("x_diagnostics", "Diagnostics and repair kit", "maintenance", "Find and fix faults in life-support and power systems.",
   carried_by="base", per="mission", conf="N", note="No contents published.")
_i("x_construct", "Construction kit (fasteners, torque tools, cable and pipe)", "maintenance", "Assemble habitat and plant.",
   carried_by="base", per="mission", conf="N", sources=("nasa_3d_habitat",),
   note="Prefabricated frames need a lot of EVA time to assemble. No tool list has been published.")
_i("x_hab_printer", "Habitat 3D-printing system", "maintenance", "Build shelter from regolith-based material.",
   carried_by="base", per="mission", conf="P", sources=("nasa_3d_habitat",),
   note="NASA's challenge awarded about $2.06 million. ICON's Mars Dune Alpha analog used a concrete-like material.")


ITEMS = {i.id: i for i in _ITEMS}
assert len(ITEMS) == len(_ITEMS), "duplicate item id"


def get(item_id):
    return ITEMS[item_id]


def search(query=None, category=None, carried_by=None, min_confidence=None, planner_vehicle=None):
    q = (query or "").lower().split()
    floor = CONFIDENCE[min_confidence]["rank"] if min_confidence else 0
    out = []
    for it in _ITEMS:
        hay = " ".join([it.id, it.name, it.summary, it.note, " ".join(it.tags), it.category]).lower()
        if q and not all(w in hay for w in q):
            continue
        if category and it.category != category:
            continue
        if carried_by and it.carried_by != carried_by:
            continue
        if planner_vehicle and it.planner_vehicle != planner_vehicle:
            continue
        if CONFIDENCE[it.conf]["rank"] < floor:
            continue
        out.append(it)
    return out
