# What Astronauts Need on Mars, by Mission Type

Research for the Marswalk Planner "tool picker": the step after the ML mission planner, where the model
chooses which tools and equipment the crew should bring and shows why.

Compiled 2026-11-14 on branch `feat/Gk`. Nothing in the code was changed.

**How to use this file.** Section 5 is the part to build from. It is a set of IF/THEN rules, each tied to a
planner output (slope, firmness, round-trip hours, O2 %, and so on) with a source and a confidence tag.
Sections 1 to 4 are the evidence behind those rules. Section 6 proposes the data layout for the picker,
and section 7 lists things in the existing project that this research calls into question.

---

## 0. Read this first: confidence tags and honest limits

Every claim carries one of these tags.

| Tag | Meaning |
|---|---|
| **[V]** | **Verified.** I re-opened the source page myself and found the number or wording. |
| **[P]** | **Published.** A research agent opened the page and read it. I did not re-check it. |
| **[E]** | **Excerpt only.** Seen only as a search-result excerpt, usually of a PDF that the agents' tools could not open. Check against the original before hard-coding it. |
| **[I]** | **Inferred.** Arithmetic or synthesis. The inputs are shown, but the conclusion is not itself a published fact. |
| **[N]** | **No source found.** Searched for and not found. Do not treat as fact. |

**How it was produced.** Eight research agents on Claude Haiku 5.5 each covered one topic. One hung while
trying to decode a PDF by hand and was replaced. I spot-checked the figures this file leans on most against
their original pages. Those are tagged **[V]**.

**Limits you should know about:**

- The agents' tools could not open PDFs. Many NASA numbers therefore come from search excerpts **[E]**.
- Most of what exists for Mars is concept-stage. No crewed Mars mission has a flight-qualified design, so
  "published" often means "a NASA study assumed this."
- NASA's own Mars crew-surface decisions are still open. The agents could not retrieve the 2025 decision
  on maximum Mars surface stay duration. NASA says no decisions have been made on Mars mission durations
  or architectures **[P]**.
- Equipment recommendations are mostly **[I]**: a sourced hazard or constraint, plus my reasoning about
  what answers it. They are meant as defaults for a model to start from, not as flight rules.

---

## 1. Headline findings

1. **Mission length is the biggest driver.** NASA's current baseline is a short stay of about 30 sols, with
   two crew landing and living in a pressurized rover, no surface habitat, and minimal power **[E]**. The
   older long-stay baseline is about 500 sols with 4 to 6 crew **[E]**. Spares, medical, exercise, power and
   shielding scale with stay length. The science kit and drilling matter more the longer you stay.
2. **EVA hours drive suit and consumable needs.** NASA studies assume up to 24 EVA hours per crew member per
   week on long missions, against 3 to 4 EVAs in six months on the ISS **[P]**.
3. **Mars suits are mass-limited.** The current xEMU is just under 400 lbm. NASA's 2026 paper recommends
   about 230 lbm as a starting maximum Mars suit mass and says the xEMU "would not be feasible to operate on
   the surface on Mars" **[V]**. That limits both what the suit can carry and how many tools you can assign
   to one person.
4. **The planner's O2 rate looks low for Mars.** NASA's Mars suit design basis is 1.9 g/min averaged over
   8 h, or **0.114 kg/h** **[V]**. Your config uses 0.085 kg/h. NASA's baseline document gives 0.076 kg/h for
   current EVA **[E]**. See section 7.
5. **Radiation sets a shelter rule.** One 2025 paper concludes an astronaut should stay within 30 minutes of
   shelter to avoid most of a solar particle event **[V]**. Combined with a 15 km walk-back, that needs
   about 30 km/h to cover, which is a vehicle requirement, not a walking one **[I]**.
6. **Terrain thresholds exist for rovers, not for crew on foot.** Slope limits of about 15° on loose ground
   and about 30° on rock come from rover experience **[E]**. There is no published equivalent for suited
   walkers. Climbing and recovery gear for crew is almost entirely **[N]** or **[I]**.
7. **Several categories have no published numbers.** These are batteries and regenerative fuel cells,
   regolith bricks, excavator power, crew-portable ground-penetrating radar, suit radio range, beacons,
   fire suppression and Mars crew rescue procedures. They are listed in section 9.

---

## 2. Mission archetypes

"Which tools" depends on which mission. These archetypes are my grouping of what NASA, ESA and others
describe. The names are mine.

| # | Archetype | Surface time | Crew on surface | EVA pattern | Basis |
|---|---|---|---|---|---|
| A | **Short-stay first landing / scouting** | About 30 sols | 2 land, 2 stay in orbit | Small number of EVAs, rover-based living | NASA 2023 architecture, SAC21 **[E]** |
| B | **Long-stay base science** | About 500 sols | 4 to 6 | Teams of 2 to 4, at least 2 stay in the habitat | DRA 5.0, NASA 2025 **[E]** |
| C | **Long traverse / geology sortie** | 1 to 2 weeks per sortie | 2 per pressurized rover (4 in contingency) | About 5 h/day driving at 3 km/h, EVAs from the rover | DRA 5.0 **[E]** |
| D | **Subsurface drilling / ice campaign** | Inside a long stay | As B | Rover-towed drill at the end of traverses | DRA 5.0 **[E]** |
| E | **ISRU / water prospecting** | Robots first, crew later | As A or B | Mining mostly automated, "likely when no crew are present" | NASA EZ study **[E]** |
| F | **Construction / outpost build-up** | Repeat visits to one site | 4 per visit | Construction zone within 5 km of landing site | NASA EZ study **[E]** |
| G | **Rescue / contingency** | Bounded by abort options | Rover seats 4 in contingency | EVA kept within rescue range of base | DRA 5.0 **[E]** |
| H | **Cave / lava-tube / pit exploration** | None published | None published | None published | **[N]** for any crewed architecture |
| I | **Orbit-only Mars vicinity** | None | None | No surface EVA | NASA 2025 white paper **[P]** |

**Not covered:** polar-ice expeditions. NASA's exploration-zone rules cap latitude at ±50° **[P]**, and
the agents found no crewed polar architecture.

### 2.1 Numbers that differ between sources

- **Short-stay length:** 30 sols (NASA 2023 and SAC21) **[E]**, 30 days (Mars Society) **[P]**, 60 days (DRA 5.0
  Addendum 2) **[E]**, 30 to 90 days (Addendum 1) **[E]**. Use the 2023 to 2025 NASA baseline (30 sols).
- **Long-stay length:** about 500 sols (DRA 5.0), 550 days (Mars Society), 500 to 600 days (NASA 1998) **[E]**.
  They agree within a normal range.
- **EVA arithmetic is inconsistent in the source.** A NASA slide states "8-hour EVA × 20 EVA sols = 190 EVA
  hours" **[E]**, but 8 × 20 = 160. Another NASA memo footnote gives "2 crew × 8-hour EVA × 20 EVA days" **[E]**,
  which is 320 crew-hours. Do not use 190.
- **Crew size:** 6 (DRA 5.0) versus "no fewer than four, with considerations for up to six" (NASA 2025) **[E]**.
  Prefer the 2025 statement.

### 2.2 What mission type changes

| Change | Effect on equipment | Basis |
|---|---|---|
| Longer stay (about 500 sols) | More spares, repair tooling, medical stock, exercise hardware, shielding, power. Productivity for science rises "many fold" | DRA 5.0 **[E]**; no resupply during transit **[P]** |
| Short stay (about 30 sols) | Habitat and mobility merged into the rover, smaller consumable kit, heavier reliance on rover spares | SAC21 **[E]**; **[I]** for kit size |
| More EVA hours | Suit wear, cooling water, battery, PLSS spares scale with the EVA-hour budget. About 1,760 hours per person at the 24 h/week ceiling over 500 sols | **[I]** from the 24 h/week rule **[E]** |
| Pre-deployed cargo waiting for crew | Kit must survive unattended storage, dust and temperature cycling | DRA 5.0, NASA 2023 **[E]** |
| Crew of 4 versus 6 | Suit count, EVA pairing | **[I]** |
| Orbit-only | No surface kit; more telerobotics and lab | **[I]** |

---

## 3. Equipment by class

### 3.1 Suits and EVA life support

| Item | Value | Tag | Source |
|---|---|---|---|
| xEMU suit mass | "just under 400 lbm" (391 lbm in the paper text) | **[V]** abstract, **[E]** 391 | [ICES-2026-127](https://ntrs.nasa.gov/citations/20260003038) |
| Mars suit starting maximum | 230 lbm (about 104 kg), split between garment and PLSS | **[V]** | same |
| Mars PLSS mass trade range | 47.9 kg (2 h, liquid O2) to 152.6 kg (8 h, open loop) | **[E]** | [ICES 2026 Mars PLSS](https://ntrs.nasa.gov/api/citations/20260005204/downloads/ICES_Mars_PLSS_Presentation_2026_1.pdf) |
| Mobility problems | PLSS of about 70 kg and about 100 kg both caused problems for larger subjects | **[E]** | ICES-2026-127 |
| Design EVA length | 8 h minimum (xEVA requirements); a Mars PLSS study treats 4 h as a mass lever | **[E]** | xEVAS requirements; ICES Mars PLSS plan |
| Early Mars suit duty | Designed for up to 25 EVAs on the initial short-stay mission | **[E]** | ICES-2026-126 |
| Suit O2, NASA Mars design basis | 1.9 g/min average over 8 h = **0.114 kg/h**; nominal range 0.4 to 4 g/min; purge 7 to 15 g/min | **[V]** | [NASA SBIR EVA.2.S26B](https://www.sbir.gov/topics/1012257) |
| Suit O2, NASA baseline document (Rev 2) | 0.076 kg/h (0.3 kg per 4 h sortie); leakage 0.005 kg/h | **[E]** | [BVAD Rev 2](https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf) |
| Suit O2, Apollo | Nominal 0.068 kg/h; walk-back 0.181 kg/h | **[E]** | [Norcross walk-back](https://ntrs.nasa.gov/citations/20080014853) |
| CO2 removal, Mars design | Average 2.2 g/min over 8 h (0.132 kg/h); range 0.5 to 4.35 g/min; venting to the atmosphere is impractical in 95% CO2 | **[V]** | SBIR EVA.2.S26B |
| Drinking water | At least 240 mL per EVA hour | **[V]** | [NASA-STD-3001 Vol 2 s11](https://www.nasa.gov/reference/11-0-spacesuits-vol-2) |
| Contingency CO2 limit | Inspired CO2 partial pressure at most 20 mmHg, for at most 1 hour | **[V]** | same |
| Urine capacity | 0.5 + 2.24 × hours/24 litres (1.25 L for 8 h) | **[P]** + **[I]** | same, s11.1.5.2 |
| Cooling water, Apollo | 0.44 kg/h nominal, 1.41 kg/h walk-back | **[E]** | [Chappell et al.](https://www.lpi.usra.edu/lunar/artemis/ChappellEtAl_NASA-JSC-CN-39092_EVA-Ops-Injuries-And-Compromised-Performance.pdf) |
| ISS EMU battery | At least 26.6 Ah at 16.8 V for a 7 h EVA (about 447 Wh); 3.8 A peak draw (about 64 W) | **[E]** + **[I]** | [EMU Data Book](https://www.lpi.usra.edu/lunar/artemis/NASA-EMU-Data-Book-JSC-E-DAA-TN55224.pdf) |
| xEMU battery and cooling water mass | Not public | **[N]** | |
| ISS EMU backup life support | 30 minutes | **[P]** | [Wikipedia EMU](https://en.wikipedia.org/wiki/Extravehicular_Mobility_Unit) |
| Prebreathe | About 4 h (ISS); 0 to 15 min at 8.2 psia / 34% O2 | **[P]** | [Kluis 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8594431) |
| Mars environment vs suit | Pressure 0.09 to 0.17 psia; air about 95% CO2; to about −220 °F; ordinary multilayer insulation is not enough | **[V]** | SBIR EVA.2.S26B |
| Carry limit | NIOSH 51 lbf lift limit used as a carry proxy (about 23 kg); pressure offload about 48 lbf; tool/sample allowance assumed 50 lbm (22.7 kg) | **[E]** | ICES-2026-127 |
| Suit spares, repair kit counts for Mars | Not found | **[N]** | |
| Personal locator beacon | Not found | **[N]** | |

**What walking on Mars costs a suited person**

| Activity | Value | Tag | Source |
|---|---|---|---|
| Lunar traverse (suited, treadmill) | 24.0 mL/kg/min, 13% failure | **[P]** | [Strock et al. 2026](https://www.nature.com/articles/s41526-026-00619-8) |
| Mars traverse (same method) | 28.7 mL/kg/min, 38.5% failure (about 2× lunar) | **[P]** | same |
| Hill climb, lunar versus Mars | 20 versus 26.0 mL/kg/min; failure 13% versus 25% | **[P]** | same |
| Suited walking at 3/8 g | 27.6 to 35.7 mL/kg/min | **[P]** | same |
| Unsuited walking in Mars gravity | About 32% lower oxygen use than on Earth | **[P]** | [Brown et al. 2018](https://kclpure.kcl.ac.uk/portal/en/publications/the-metabolic-cost-of-walking-in-simulated-martian-gravity-and-it) |
| Apollo EVA average | 979 kJ/h (928 Btu/h); range 780 to 1,200 Btu/h | **[E]** | [NASA Apollo EVA energy](https://ntrs.nasa.gov/api/citations/20120003917/downloads/20120003917.pdf) |
| Heaviest Apollo tasks | Hatch ingress, equipment offload and setup, drilling, sample stowage | **[E]** | Chappell et al. |
| Cooling ceiling (Apollo-era) | About 2,000 Btu/h | **[E]** | same |

Unsuited Mars walking is cheaper than Earth. Suited Mars walking is more expensive than lunar. Both are
true. The suited figures come from offload and treadmill simulations, and the authors note the extrapolation
to Mars is limited **[P]**.

### 3.2 Mobility, traverse and terrain gear

**Vehicles.** Almost all numbers are lunar or concept-stage.

| Vehicle | Crew | Speed | Range / endurance | Slope | Tag | Source |
|---|---|---|---|---|---|---|
| Apollo rover (flown) | 2 | Design 9 to 13 km/h; comfortable 6 to 7 | Longest actual traverses 20 km; max 7.6 km from the lander | 18 to 23° tested, 25° spec | **[E]** | [Costes, NASA TR R-401](https://ntrs.nasa.gov/api/citations/19730008090/downloads/19730008090.pdf) |
| NASA Space Exploration Vehicle (2008 concept) | 2 (4 in emergency) | 10 km/h | 125 km, up to 14 days | Not stated | **[P]** | [Wikipedia SEV](https://en.wikipedia.org/wiki/Space_Exploration_Vehicle) |
| NASA lunar terrain vehicle requirements | Up to 2 | Up to 10 km/h | 100+ km crewed | 20° | **[P]** | [NASA Moon Base Systems](https://www.nasa.gov/moonbase-systems/) |
| JAXA/Toyota Lunar Cruiser | 2 | About 3.5 km/h (NASA page); 15 km/h max (JAXA appendix) | 28 to 45 days depending on source | 15° (NASA page) | **[P]** / **[E]** | [NASA Moon Base Systems](https://www.nasa.gov/moonbase-systems/), JAXA appendix |
| NASA Mars pressurized concepts | 2 to 4 | 10 km/h | 14 days, 80 to 1,000 km depending on concept | Not stated | **[E]** | [GRC rover concepts](https://www.nasa.gov/wp-content/uploads/2015/06/exploration_rover_concepts_grc.pdf) |
| Perseverance (flying) | Robot | About 150 m/h top speed | Longest single drive 411.7 m | Avoids over 30° tilt | **[P]** / **[E]** | [NASA rover page](https://mars.nasa.gov/mars2020/spacecraft/rover/) |

**Hazard to equipment**

| Hazard | Evidence | Equipment response | Tag |
|---|---|---|---|
| Soft sand ripples | Opportunity dug more than 10 cm into a ripple at Purgatory Dune and was stuck about 5.5 weeks | Wide-wheel vehicles; keep-out zones; recovery gear for crew is **[N]** | **[P]**, [JPL](https://mars.nasa.gov/resources/5855/looking-back-at-purgatory-dune/) |
| Crust over soft sand | Spirit broke through a crust at "Troy" in 2009 and never got free | Probe the crust before crossing (the Apollo equipment cart carried a penetrometer) | **[P]**, [JPL](https://www.jpl.nasa.gov/news/nasa-to-begin-attempts-to-free-sand-trapped-mars-rover/) |
| Steep slope | Opportunity at 32° moved 9 cm while its wheels turned about 20 m | Avoid, or climbing gear (**[N]** for Mars crew) | **[P]**, [Space.com](https://space.com/32439-mars-rover-opportunity-steepest-slope.html) |
| Loose sand on a slope | Perseverance on the Jezero rim climb at about 20° covered only 20 to 50% of planned distance on bad days | Backward driving and switchbacks | **[E]** |
| Boulder fields | Neretva Vallis drives fell from over 100 m to tens of m per sol | Schedule buffers | **[P]**, [NASA](https://nasa.gov/solar-system/nasas-perseverance-fords-an-ancient-river-to-reach-science-target) |
| Sharp rocks | Curiosity wheel damage; three broken grousers is about 60% of useful life | Spare wheels, abrasion-resistant boots and gloves | **[P]**, [JPL](https://jpl.nasa.gov/news/breaks-observed-in-rover-wheel-treads) |
| Pits and lava-tube skylights | Candidate skylights 100 to 225 m wide, 68 to 130 m deep | Tethered descent, lighting, robotic scouting first; crewed gear is concept only | **[E]**, [Cushing 2007](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2007GL030709) |
| Canyon walls (Valles Marineris) | About 30° slopes; over 16,000 boulder-fall events | Rockfall exclusion zones | **[E]** |
| Hidden voids | RIMFAX radar on the rover: 3 kg, 5 to 10 W, at least 10 m depth | A crew-portable radar is **[N]** | **[P]**, [NASA](https://mars.nasa.gov/mars2020/spacecraft/instruments/rimfax/) |

**Walk-back and traverse limits**

- DRA 5.0 nominal traverse: about 15 km out, "or EVA walk-back distance" **[E]**.
- Apollo rover sorties were limited to walking distance from the lander in case the rover failed **[E]**.
- A simulated 10 km suited walk-back took 61 to 95 minutes and used about 944 kcal **[P]**.
- Tobler hiking function, unsuited hiker: 5° 3.71 km/h, 10° 2.72, 15° 1.97, 20° 1.41, 25° 0.98, 30° 0.67
  **[P]**, [Wikipedia](https://en.wikipedia.org/wiki/Tobler%27s_hiking_function). A 2025 paper found slope alone
  does not predict suited EVA speed, so treat this only as a baseline **[E]**.
- No usable Apollo walking-speed-on-slope table was found. Cliff and rope gear for Mars crew is **[N]**.

### 3.3 Science fieldwork, sampling and instruments

**Hand tools.** Apollo is the only flown precedent. Artemis redesigned the kit from the Apollo 17 baseline.

| Tool | Mass | Use | Tag |
|---|---|---|---|
| Geology hammer | 860 g (Apollo 11 to 12) or 1,300 g (14 to 17) | Chip rock, drive core tubes | **[E]** |
| Tongs | 230 g (Apollo 15 to 17); one flight list shows 454 g | Pick up small rocks without bending in the suit | **[E]** (masses disagree) |
| Large scoop | 590 g | Soil | **[E]** |
| Rake | 1,500 g | Collect pebbles over 1 cm | **[E]** |
| 4 cm drive tube | 300 g tube plus 110 g caps | Soil core | **[E]** |
| Extension handle | 590 to 820 g | Shared shaft | **[E]** |
| Gnomon | 272 g | Scale and orientation in photos | **[E]** |
| Sample scale | 227 g | Weigh samples | **[E]** |
| Large tool carrier | 8,029 g | Carry tools on the rover | **[E]** |
| Apollo drill | Depth to about 3 m | Deep core | **[E]**; drill mass and power **[N]** |
| Full Apollo 16 kit | About 53 kg | | **[E]** (from a flight list) |

Artemis added a tool cart, powered core drill, vacuum-sealed containers, a chisel and a utility belt to
its proposed set **[E]**. Artemis III's candidate sample program is 83 kg against a 64 kg Apollo average **[E]**.

**Perseverance sampling hardware (the best Mars hardware numbers)**

| Item | Value | Tag |
|---|---|---|
| Sample tube | Titanium, under 57 g, under 15.2 cm; 43 tubes, 38 for samples and 5 witness blanks | **[P]** / **[E]** |
| Core | About 1 cm wide, upper 5 cm of rock, about 15 g, kept under 60 °C, hermetically sealed | **[E]** |
| Contamination limits | Under 150 ng total Earth organics per sample; under 10 ppb total organic carbon; under 1 viable organism per sample | **[E]** |
| Tube internal volume | About 12.5 cm³ in the 2024 peer-reviewed paper. A JPL page says 147 cm³, which is about 12× larger and is probably a press error | **[E]**, conflict |
| ExoMars 2 m drill | 2 m depth, 21 kg, 80 W | **[E]** |
| Human-scale drill study | 700 to 1,000 kg for a dedicated drill; about 2,200 kg for a deep drill | **[E]** |
| Human drill depth | 100 to 1,000 m (DRA 5.0 excerpts) or about 10 m to reach the water table (another study) | **[E]**, conflict |

**Instruments an astronaut could carry or deploy**

| Instrument | Mass / power | What it does | Tag |
|---|---|---|---|
| ASD TerraSpec Halo (handheld near-infrared) | 2.5 kg with battery, 16.5 W | About 15 s per scan; reliable for mineral groups, less so for specific minerals | **[E]** |
| Bruker TRACER IV-SD (handheld X-ray fluorescence) | 2 kg | 3 mm spot, 30 s per analysis; sodium and magnesium weak | **[E]** |
| PHOENIX (ESA handheld Raman, LIBS and XRF) | Not published | Built for astronaut training | **[E]**, mass **[N]** |
| Weather station (MEDA-class) | About 5.5 kg | Wind, pressure, humidity, temperature at several heights, dust, radiation | **[P]** |
| Radiation detector (RAD-class) | 1.56 kg, 4.2 W | Dose and dose equivalent | **[P]** |
| Ground-penetrating radar (RIMFAX-class) | 3 kg, 5 to 10 W | At least 10 m depth, 15 to 30 cm resolution | **[P]**; crew-portable **[N]** |
| Seismometer (SEIS-class) | Reported anywhere from 3 kg to 29.5 kg | Interior structure | **[E]**, conflict |

**What analog missions taught** (BASALT, Desert RATS, NEEMO, Mars Desert Research Station):

- Handheld spectrometer data was "critical" to deciding things mid-EVA. X-ray quality dropped with gaps over
  4 mm, and the infrared instrument was contaminated by sunlight at 10 mm gaps **[P]**.
- Rough, dusty surfaces need flattening and cleaning first. Crews read results aloud because the instruments
  could not stream to the science team **[P]**.
- Large hard rocks did not fit the standard bag. A claw tool was "not particularly useful." No hand lens was
  carried and crews wanted one **[E]**.
- Instruments that were easy on Earth were hard to operate in suit gloves. Temporary sample markers were
  essential for crew to science-team communication **[E]**.
- Low gravity limits how hard a crew member can press down while sampling. A breakaway core bit worked **[E]**.
- Sterile sampling took longer, and crews avoided touching candidate sites before sampling **[P]**.

**Contamination and planetary protection.** COSPAR's special-region rules require restricting contact
hardware to 30 spores or sterilizing it. Subsurface below 5 m is treated as potentially special **[E]**.
Crewed-Mars guidelines call for quarantine capability and robotic precursors before crew reach an
uncharacterized site **[E]**. NASA's crewed-Mars planetary protection directive expired 30 September 2025,
and its replacement status is unknown **[E]**. The NASA handbook prints the special-region temperature as
"> 28 °C." JAXA prints "at least −28 °C," which is almost certainly correct **[E]**.

### 3.4 Power, ISRU, excavation, construction and repair

| Item | Value | Tag | Source |
|---|---|---|---|
| Fission surface power | 40 kWe class, reactor under 6 tonnes, 10 years unattended | **[P]** | [NASA FSP](https://www.nasa.gov/exploration-systems-development-mission-directorate/fission-surface-power/) |
| Newer power requirement | One NASA directive says "at least 100 kWe" for long-term operations including ISRU. The agent could not open it | **[E]**, conflict | [NASA directive](https://www.nasa.gov/wp-content/uploads/2025/08/nasa-fsp-directive-aug42.pdf) |
| 10 kWe Kilopower-class | 1,500 kg; 40 kWe supports 4 to 6 crew | **[P]** secondary | [Wikipedia Kilopower](https://en.wikipedia.org/wiki/Kilopower) |
| Solar arrays and dust | Typical dust loss about 0.2% per sol (observed 0.05 to 2%); InSight output fell about 30% after landing. About 26% of output would remain after 668 sols with no cleaning | **[E]** / **[P]** / **[I]** | [JPL](https://www.jpl.nasa.gov/news/for-insight-dust-cleanings-will-yield-new-science/) |
| MOXIE oxygen | Peak 12 g/h at 98% purity or better; 122 g total over 16 runs; original goal 6 g/h | **[V]** | [NASA](https://www.nasa.gov/missions/mars-2020-perseverance/perseverance-rover/nasas-oxygen-generating-experiment-moxie-completes-mars-mission/) |
| MOXIE scale-up | A system 2 to 3 kg/h (several hundred times MOXIE) could produce enough oxygen to launch a crew ascent vehicle after one 26-month cycle | **[V]** | [Hoffman et al. 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9432831/) |
| Scaled MOXIE power | 18 to 30 kW for about 2 kg/h, depending on source | **[I]** / **[P]** | conflict, see section 8 |
| MOXIE mass and power | 15 to 17 kg, 300 W | **[P]** secondary | [Wikipedia](https://en.wikipedia.org/wiki/Mars_Oxygen_ISRU_Experiment) |
| Ascent propellant plant | 1.7 t system could make a full ascent load, avoiding about 30 t of propellant from Earth | **[P]** | [NTRS 20170001421](https://ntrs.nasa.gov/citations/20170001421) |
| Ice near the surface | Mid-latitude ice within about 1 m | **[P]** | [JPL](https://www.jpl.nasa.gov/news/nasa-is-locating-ice-on-mars-with-this-new-map/) |
| Regolith as shielding | 10 g/cm² of regolith cut galactic dose about 28%; about 80 cm to 2.5 m needed for a 100 mSv/yr target | **[P]** / **[E]** | [Gakis and Atri](https://arxiv.org/html/2205.13786v3) |
| Mars dust limit | 0.1 mg/m³, 24-hour average, up to 30 days (lunar limit of 0.4 divided by 3) | **[V]** | [NASA](https://www.nasa.gov/general/establishing-crew-exposure-limits-of-martian-dust/) |
| Spares | ISS can get parts in about 6 weeks. There is no resupply in Mars transit. NASA noted a third of Mars mission mass cannot be spares | **[P]** / **[E]** | [NASA podcast](https://www.nasa.gov/johnson/HWHAP/hazard-5-environments) |
| ISS tool heritage | Pistol grip tool, manipulator foot restraint, safety tether, maintenance work area, grease guns | **[P]** | [ISS National Lab](https://issnationallab.org/iss360/innovation-in-focus-tools-in-space/) |
| 3D-printed habitat | NASA challenge awarded $2.06 million; ICON's Mars Dune Alpha analog used a concrete-like material | **[P]** | [NASA](https://www.nasa.gov/prizes-challenges-and-crowdsourcing/centennial-challenges/3d-printed-habitat-challenge/) |

**Not found:** batteries and regenerative fuel cells, regolith bricks and sintering, excavator mass and
power, ice-drilling power, power cable reels and connectors, perchlorate handling tools, inflatable habitat
masses, torque wrench and fastener kits, and EVA hours to set up a habitat or power plant. All **[N]**.
Setup-hour estimates in the source material were **[I]** and are left out here.

### 3.5 Medical, radiation, dust and emergency

| Item | Value | Tag | Source |
|---|---|---|---|
| Career radiation limit | Less than 600 mSv, all ages and sexes | **[V]** | [NASA-STD-3001 s4](https://www.nasa.gov/reference/4-0-human-performance/) |
| Solar storm limit | Design reference event under 250 mSv effective dose | **[V]** | same |
| Surface habitat dose cap | Under 0.9 mSv/day for systems on planetary surfaces (1.3 in free space) | **[V]** | same |
| Storm shelter shielding | **10 g/cm² water equivalent around the crew member, surface, any duration** | **[V]** | same, Table 4.8-4 |
| In-space shielding | 15 g/cm² (under 6 months) and 20 g/cm² (over 6 months) beyond low Earth orbit. My reading is that these are for vehicles in space, not the Mars surface | **[E]** + **[I]** | same |
| Measured surface dose | 0.67 mSv/day (Aug 2012 to Jun 2013); 1.8 mSv/day in cruise | **[V]** | [SwRI](https://www.swri.org/newsroom/press-releases/swri-scientists-publish-first-radiation-measurements-the-surface-of-mars) |
| Solar storm warning | Nowcast trigger: dose rate 25% above the 5-day background. Gives at least about 30 minutes. The authors conclude an astronaut "should not move more than 30 minutes away from a shelter" to avoid over 90% of storm dose. One paper's finding, not a NASA rule | **[V]** | [Löwe et al. 2025](https://arxiv.org/html/2502.02469v1) |
| Warning independent of Earth | Radiation alarm important "if communication is ever lost" | **[P]** | [NASA SRAG](https://srag.jsc.nasa.gov/spaceradiation/how/how.cfm) |
| Suit radiation monitor | Suit must provide or accommodate monitors | **[P]** | NASA-STD-3001 Vol 2 s11 |
| Dust symptoms | Apollo 17 crew reported "lunar hay fever" | **[P]** | [NASA](https://www.nasa.gov/technology/tech-transfer-spinoffs/measuring-moon-dust-to-fight-air-pollution/) |
| Dust particle size | Mars dust averages about 3 µm; particles under 5 µm cannot be cleared by lung mucus | **[P]** | [Wang et al. 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC11815326/) |
| Fine dust on suits | Ultrafine (about 100 nm) dust sticks to suit-like fabric. NASA recommends suitports and dual-chamber airlocks | **[P]** | [NASA](https://www.nasa.gov/missions/mars-2020-perseverance/nasas-perseverance-offers-clues-to-protect-crews-from-mars-dust) |
| Perchlorate | About 0.4 to 0.6% (Phoenix) up to 0.5 to 1% of soil; reference dose about 0.0007 mg/kg/day; potassium iodide proposed | **[E]** / **[P]** | [Hecht 2009](https://pubmed.ncbi.nlm.nih.gov/19574385/), Wang et al. |
| Bone density target | At least 95% of baseline at hip and spine | **[P]** | NASA-STD-3001 s4 |
| Exercise hardware | Resistive device, cycle ergometer and treadmill required | **[P]** | same |
| Medical kit exemplar (Orion) | 128 medical conditions and 139 medical resources; prime, secondary and accessory kits; in-suit pill tool; medical oxygen | **[P]** | [NASA Orion](https://www.nasa.gov/reference/crew-systems-2) |
| Autonomous care | Required: "means of providing autonomous medical care and advanced life support" | **[P]** | [NASA-STD-3001 s3](https://www.nasa.gov/reference/3-0-health-and-medical-care/) |
| Defibrillator, surgical kit, dental detail, shelf-life | Not found | **[N]** | |
| Fire suppression for Mars | Materials flammability standard exists; suppression not found | **[N]** | [NASA-STD-6001](https://standards.nasa.gov/standard/NASA/NASA-STD-6001) |
| Mars rescue procedure and beacon | Standard requires an incapacitated-crew rescue capability. No Mars-specific beacon or procedure found | **[P]** / **[N]** | NASA-STD-3001 Vol 2 s11.5 |

**Other published human-factors numbers** (all **[P]**, from [NASA-STD-3001 s4 and s6](https://www.nasa.gov/reference/6-0-medical-operations/)):

- Surface EVA fitness: VO2max at least 36.5 mL/min/kg.
- A medical clearance is required before each EVA.
- Avoid critical tasks between 1 and 7 AM relative to the sleep schedule.
- Mars sol is 24 h 39.6 min, so work and EVA windows drift about 40 minutes per sol **[I]**.

### 3.6 Communications and navigation

| Item | Value | Tag | Source |
|---|---|---|---|
| One-way Earth to Mars light time | About 3 to 22.4 minutes; round trip up to 44 | **[P]** | [NASA Mars Relay Network](https://science.nasa.gov/mars/mars-relay-network/) |
| Blackouts | Several days up to several months, depending on band | **[P]** | [ASCEND 2022](https://ntrs.nasa.gov/citations/20220013418) |
| Mars relay | 4 orbiters; rover data up to 2 Mbps; rovers lack Earth line of sight about 12 h/day | **[P]** | NASA Mars Relay Network |
| Ground-level line of sight | One antenna at 1.5 m sees about 3.2 km on a smooth sphere; two antennas about 6.4 km. Hills and crater walls cut this sharply | **[I]** | geometry, Mars radius 3,389.5 km |
| Suit radio range, relay beacons on a traverse, surface navigation without GPS | Not found | **[N]** | |

---

## 4. Sites and terrain

### 4.1 Exploration Zone framework

An Exploration Zone is a collection of regions of interest within about 100 km of a central landing site **[P]**.

| Criterion | Value | Tag | Source |
|---|---|---|---|
| Latitude | ±50° | **[P]** | [Hoffman and Bussey 2016](https://ntrs.nasa.gov/citations/20160001040) |
| Elevation | Within ±2 km of the datum (workshop) versus below −1 km (older landing-site practice) | **[P]**, conflict | [Mashal et al. 2025](https://iopscience.iop.org/article/10.3847/PSJ/ade30e) |
| Thermal inertia | "Low but not dominated by dust." Masked below 100; a second mask below 140 | **[P]** / **[E]** | Mashal et al. 2025 |
| Ice resource | At least one location able to yield over 100 tonnes of water, as shallow as possible | **[E]** | Hoffman and Bussey |
| Mining terrain | Flatter than about 10° | **[E]** | same |
| Construction zone | Flat and stable, within 5 km of the landing site | **[E]** | same |
| Rover traverse paths | At most 30° | **[E]** | [NASA 2024 site study](https://www.nasa.gov/wp-content/uploads/2024/09/dsl-analyzing-proposed-mars-landing-sites-final-8-23-24-508.pdf) |

The framework gives no published slope, rock-abundance or dust threshold for the zone itself. Those come
from landing-site engineering for rovers. A 2025 screening score put Jezero at 90 and Gale at 88 out of 100,
as an unweighted overlay of public data, not a validated assessment **[P]**.

### 4.2 Jezero

- Crater about 45 km wide. Crater floor holds the boulder-forming Máaz formation and the olivine-rich Séítah
  formation, whose margin is "partly defined by large, mostly nontraversable aeolian bedforms" **[P]**,
  [Bell et al. 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9683734).
- Delta scarp rises 70 to 90 m above the landing site. Crater rim walls rise 800 to 1,200 m **[P]**.
- Landing-site rocks are typically under 30 cm, with some boulders 30 to 50 cm. Ripples are 15 to 20 cm tall **[P]**.
- Dust optical depth about 0.4 to 0.5 early, falling to about 0.25. Less dusty than other landing sites **[P]**.
- Dust devils are "more abundant at Jezero than elsewhere on Mars" and can exceed 100 m across **[P]**.
- Mean air temperature about −55 °C with a 50 to 60 K day-night swing **[P]**.
- Surface pressure about 718 Pa **[E]**.
- Perseverance has driven 45.22 km, over 90% under autonomous navigation **[P]**,
  [NASA](https://science.nasa.gov/blogs/perseverance-mars-rover/2026/10/12/nasas-perseverance-sets-off-world-record-for-total-distance-driven).

### 4.3 Data signals and what they mean

| Signal in your planner | What the evidence says | Threshold | Tag |
|---|---|---|---|
| Slope on loose ground | Rovers fail above about 15° at a 3 m baseline on unconsolidated material | 15° | **[E]**, [Golombek et al.](https://mars.asu.edu/christensen/docs/golombek_mersites_jgr.pdf) |
| Slope on rock | Rover limit about 30°; Opportunity made almost no progress at 32° | 30° | **[E]** / **[P]** |
| Landing slope | Under 2° at 1 km, under 5° at 100 m, under 15° at 3 to 10 m | | **[E]** |
| Loose-ground proxy | Thermal inertia under 100 to 140 flags dust. Your `firmness` band is night-time infrared rescaled 0 to 1, so these thresholds do not map to it directly | 100 to 140 | **[P]**, **[I]** for the caveat |
| Roughness | Your band is local elevation scatter in metres. The rover record uses rock abundance (about 7% typical, 15% design basis), which your cube does not contain | 7%, 15% | **[E]** |
| Sand and ripples | Avoid traverses where all wheels are in sand | | **[E]** |
| Surface temperature | Jezero mean about −55 °C; Gale nights about −90 to −100 °C | | **[P]** / **[E]** |
| Dust storm | The 2018 global storm halted Opportunity. No published threshold at which to stop EVA | | **[P]** |

### 4.4 Site type to equipment

These pair sourced hazards with equipment that answers them. The pairing is **[I]**.

| Site type | Sourced hazard | Equipment |
|---|---|---|
| Ice-rich plains (Arcadia, Deuteronilus) | Phoenix found ice 2 to 6 cm down; Arcadia matches the most criteria for accessible ice | Hand tools for shallow ice; powered drill for ice at 1 to 5 m; insulation; keep samples frozen |
| Volcanic plains and pits | Skylights 100 to 225 m wide, 68 to 130 m deep; pits are shielded from UV | Descent gear, lighting, robotic scouting first, UV-shielded storage |
| Canyon walls | About 30° walls, over 16,000 boulder-fall events | Rockfall exclusion zones, helmets, rope for slopes over 15 to 30° |
| Dune fields | Opportunity trapped, Séítah bedforms nontraversable | Traction aids, recovery gear, dune-free routes |
| Cratered highlands | Sharp rock wears wheels | Hammer, heavy bags, tough boots and gloves |
| Hydrated mineral sites | Hydrothermal systems targeted | Sealed sample containers, contamination control |

---

## 5. Decision rules for the tool picker

Each rule has a trigger the planner already computes or could compute, a consequence, and a confidence tag.
"Evidence" says whether the threshold is published or my own number. Treat **[I]** thresholds as tunable.

**Planner signals available today:** `distance_km`, `one_way_h`, `round_trip_h`, `max_slope_deg`,
`mean_slope_deg`, `within_budget`, `o2_pct`, `energy_pct`, `max_range_km`, `limiting_factor`, sun
elevation, `warnings`, and the per-pixel bands (slope, roughness, firmness, illumination, temperature,
shelter minutes). Mission-level inputs such as stay length, crew size and science goals would need to come
from the mission planner.

### 5.1 Safety and consumables (hard constraints)

| ID | IF | THEN require or add | Evidence | Tag |
|---|---|---|---|---|
| S1 | `o2_pct` over 100 | Rover support or shorter route. For margin use the NASA Mars design rate of 0.114 kg/h and, for contingency, 0.18 kg/h | Design rate **[V]**; walk-back rate **[E]** | |
| S2 | `one_way_h` over 0.5 (30 min) from the nearest storm shelter | Shielded vehicle, forecast gating, or shelter at the work site | 30-minute finding **[V]**; applying it as a rule is **[I]** | |
| S3 | Planned walk-back over 1 hour | Extra CO2 capacity or a cap on duration | 20 mmHg for 1 hour **[V]** | |
| S4 | Any EVA over 4 hours | Food, 240 mL/h drinking water, urine capacity | **[V]** | |
| S5 | Any EVA | Radiation monitor in the suit, alarm that works without comms | **[P]** | |
| S6 | Any surface stay | Storm shelter with 10 g/cm² water-equivalent shielding | **[V]** | |
| S7 | Any EVA | Buddy pair, medical clearance, incapacitated-crew rescue capability | **[P]** | |
| S8 | Suit pressure above cabin pressure | Prebreathe time or a matched cabin pressure | **[P]** | |
| S9 | Projected career dose reaching 600 mSv | Do not assign the crew member | **[V]** | |
| S10 | Surface habitat dose rate over 0.9 mSv/day | More shielding | **[V]** | |

### 5.2 Terrain-driven gear

| ID | IF | THEN consider | Evidence | Tag |
|---|---|---|---|---|
| T1 | `max_slope_deg` over 15 on loose ground | Rover support or route change; tether and climbing gear for crew | 15° **[E]**; gear **[I]** | |
| T2 | `max_slope_deg` over 20 | Exclude the unpressurized rover class; pressurized rover capped at 15° on the NASA lunar page | **[P]**, lunar spec | |
| T3 | `max_slope_deg` over 30 | Exclude vehicles; walking route only with climbing gear, or avoid | **[E]** | |
| T4 | Low firmness band on route | Probe for crust, avoid sand where all wheels would sink, carry recovery gear | Spirit and Opportunity **[P]**; gear **[I]** | |
| T5 | High roughness, sharp rocks | Spare wheels (vehicles), abrasion-resistant boots and gloves | **[P]** / **[I]** | |
| T6 | Pit, skylight or cliff in the zone | Robotic scouting first, tethered descent and lighting, no unsupervised entry | Concept studies **[E]**; rule **[I]** | |
| T7 | Surface temperature layer very cold, or long EVA at night | Heaters, extra battery, insulation | Mean −55 °C **[P]**; no published suit threshold | **[I]** |
| T8 | Sun elevation under the minimum | Cancel or reschedule (already a warning in the planner) | | |
| T9 | Planned distance over about 15 km from base | Field cache or a second vehicle | DRA 5.0 **[E]** | |

### 5.3 Science and mission-driven gear

| ID | IF | THEN add | Evidence | Tag |
|---|---|---|---|---|
| M1 | Goal includes biosignatures | Sterile sealed sample tubes, witness blanks, glove swabs, survey before touching candidate sites, two independent handheld analysers | **[P]** / **[E]** | |
| M2 | Subsurface or present-life objective | Drill to at least 2 m; subsurface below 5 m triggers special-region rules | **[E]** | |
| M3 | Deep subsurface or ice (over 10 m) | Budget a 700 to 2,200 kg class drill | **[E]** | |
| M4 | Measuring on rough or dusty rock | Flatten and clean first; X-ray gap under 4 mm; shield sunlight | **[P]** | |
| M5 | Remote science team | Instruments that stream, with photo fallback | **[P]** | |
| M6 | Gloved crew | Large tethered tools | **[E]** | |
| M7 | Sampling in low gravity | Stabilisation (boom or foot restraint) | **[E]** | |
| M8 | Sample mass is capped | Plan a sample suite per site and weigh each EVA | **[P]** | |
| M9 | Crew must point out targets | Markers, scale bars, hand lens | **[E]** | |
| M10 | Atmosphere science | Four or more weather stations | **[P]** | |
| M11 | Stay of about 30 sols | Handheld instruments and one drill over fixed labs | **[I]** | |
| M12 | Stay of 300 to 500 sols | Drill, pressurized rover with geology gear, return lab, exercise hardware, full medical kit | **[E]** / **[I]** | |
| M13 | Crew lack geology training | Field and classroom training before flight | **[P]** | |
| M14 | Long stay with ISRU for ascent propellant | Fission power at 40 kWe or more, excavators, water extraction, spares | **[P]** / **[I]** | |
| M15 | Solar power only, long stay | Oversize arrays or plan dust cleaning; storm-season battery | **[P]** / **[I]** | |
| M16 | Mission length with no resupply | Spares and repair tooling in proportion to length | **[P]** | |

### 5.4 Weight cap per person

Cap carried tools and samples at about **22 kg per astronaut per EVA** (the 50 lbm allowance NASA used) and
assign anything heavier to a rover **[E]** + **[I]**. The ceiling is higher on a rover-supported mission and
lower for a long, suited walk.

### 5.5 How to combine rules with the ML model

A suggested split, not something the research proves: treat section 5.1 as non-negotiable guardrails, and
let the model rank and choose within the options that satisfy them. Every item it picks should carry the
rule IDs and sources that justify it, so the UI can show why.

---

## 6. Proposed data layout for the picker

One row per candidate item. Fields marked "required" should exist for every row. Leave a field empty rather
than guessing, and always record where each number came from.

| Field | Type | Notes |
|---|---|---|
| `id` | string | Required, stable |
| `category` | enum | suit, consumable, vehicle, hand_tool, instrument, drill, power, medical, comms, shelter, safety |
| `mass_kg` | number | Required for carry-cap checks |
| `volume_l` | number | Often missing |
| `power_w` | number or range | |
| `consumable_rate` | text with units | e.g. `O2 0.114 kg/h` |
| `mission_types` | list | Archetype letters from section 2 |
| `terrain_triggers` | text or rule IDs | Link to section 5 |
| `min_crew` | integer | |
| `substitute_for` | id | |
| `redundancy_required` | boolean | |
| `carried_by` | enum | astronaut, rover, base, deployed |
| `source_url` | url | Required |
| `confidence` | enum | V, P, E, I, N, matching section 0 |

**Example rows** (numbers are only ones found in this research):

| id | category | mass_kg | power / rate | mission_types | terrain_triggers | confidence | source |
|---|---|---|---|---|---|---|---|
| suit_o2_design | consumable | | 0.114 kg/h | A, B, C | S1 | V | [SBIR](https://www.sbir.gov/topics/1012257) |
| suit_o2_contingency | consumable | | 0.181 kg/h | C | S1, S3 | E | [Norcross](https://ntrs.nasa.gov/citations/20080014853) |
| drinking_water | consumable | | 0.24 kg/h | all | S4 | V | [NASA-STD-3001](https://www.nasa.gov/reference/11-0-spacesuits-vol-2) |
| rad_monitor_suit | safety | | | all | S5 | P | [NASA-STD-3001](https://www.nasa.gov/reference/11-0-spacesuits-vol-2) |
| storm_shelter | shelter | | 10 g/cm² water | all | S2, S6 | V | [NASA-STD-3001](https://www.nasa.gov/reference/4-0-human-performance/) |
| hand_xrf | instrument | 2 | | A, B, C | M1, M4 | E | [Bruker](https://www.bergeng.com/mm5/downloads/bruker/Bruker_TRACER_Specifications_Comparison.pdf) |
| hand_nir | instrument | 2.5 | 16.5 W | A, B, C | M1, M4 | E | [ASD](https://www.geopool.fi/wp-content/uploads/2022/01/asd-terraspec-halo-mineral-identifier.pdf) |
| geology_hammer | hand_tool | 0.86 to 1.3 | | A, B, C | M6 | E | [Allton](https://repository-dev.hou.usra.edu/server/api/core/bitstreams/f74b6eee-9954-4c4b-9b3f-17f87af32348/content) |
| rake | hand_tool | 1.5 | | A, B, C | | E | same |
| sample_tube | hand_tool | 0.057 | | A, B, C | M1 | P | [JPL](https://www.jpl.nasa.gov/news/a-martian-roundtrip-nasas-perseverance-rover-sample-tubes/) |
| drill_2m | drill | 21 | 80 W | B, D | M2 | E | [Leonardo](https://space.leonardo.com/documents/16277711/19573930/ExoMars_LQ_mm07795_.pdf?t=1538987564303) |
| drill_deep | drill | 700 to 2,200 | | B, D | M3 | E | [NTRS 20140006398](https://ntrs.nasa.gov/api/citations/20140006398/downloads/20140006398.pdf) |
| gpr | instrument | 3 | 5 to 10 W | B, D | T6 | P | [NASA](https://mars.nasa.gov/mars2020/spacecraft/instruments/rimfax/) (rover unit, not crew-portable) |
| fission_power | power | 6,000 (reactor) | 40 kWe | B, E | M14 | P | [NASA FSP](https://www.nasa.gov/exploration-systems-development-mission-directorate/fission-surface-power/) |
| moxie_scaled | power | | 18 to 30 kW for 2 kg/h O2 | B, E | M14 | I / P | [Hoffman et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC9432831/) |
| medical_kit_core | medical | | | all | | P | [NASA Orion](https://www.nasa.gov/reference/crew-systems-2) |

**Showing it clearly in the UI** (suggestions, not research findings):

- Group the kit by category and show a bar of carried mass against the 22 kg cap.
- Next to each item, show short "why" chips naming the rule (for example `S2 shelter 30 min` or
  `T1 slope over 15°`) that link to the source.
- Show the confidence tag as a small badge, so a judge can see which items rest on a NASA document and which
  are the model's judgement.
- Flag items with no published basis, so they read as proposals.

---

## 7. What this means for the existing project

Nothing here has been changed in code. These are things to decide.

> **Update, 2026-11-14:** items 1 and 2 are resolved. The planner now uses NASA's Mars design basis
> (0.114 kg/h, 0.912 kg) and adjusts it for slope and carried load; see the README's consumables section.

1. **Suit O2 rate.** NASA's Mars design basis is 0.114 kg/h **[V]**, current EVA is 0.076 kg/h **[E]**, and your
   config is 0.085 kg/h. 0.085 is between the two and is not unreasonable for a planning default. The
   0.114 figure is a sizing requirement for the supply system and may include margin, so it is not a
   measured rate. It is worth exposing both rather than choosing silently.
2. **The 0.68 kg capacity attribution.** `config.py`, the README and `CHANGELOG.md` describe 0.68 kg as the
   xEMU's 8 h design endurance. The agents found no public xEMU oxygen mass. The nearest public figure is the
   ISS suit's roughly 0.55 kg usable **[E]**. 0.085 × 8 = 0.68 holds, so the number is self-consistent. It
   would be more accurate to say it was chosen to match an 8 h rating at 0.085 kg/h.
3. **Pressurized rover energy numbers remain unsourced.** No published battery size, idle power or energy
   per km turned up. A garbled NASA concept table suggests 5 to 20 kW power demand for a pressurized rover
   **[E]**, but its column alignment could not be verified. If that figure applies, a 20 kWh battery and
   0.12 kWh/km look small. This is low confidence. It argues for keeping the "estimate" label, and for
   treating the three constants as a range with sensitivity, not for swapping in a new number.
4. **Vehicle slope limits.** Your `VEHICLES` caps are 18° (astronaut), 20° (crew rover) and 25° (small
   rover). Published lunar vehicle limits are 15 to 20° for pressurized rovers **[P]**. Nothing published
   gives a Mars limit for suited walkers.
5. **Cabin oxygen is not modelled.** NASA's baseline gives about 0.818 kg per crew member per day **[P]**
   (secondary source, older revision). A crewed rover needs it for any multi-hour trip.
6. **The firmness band.** NASA's thermal-inertia cut-offs (100 to 140) cannot be applied to your normalised
   night-infrared band without a conversion.
7. **Roughness versus rock abundance.** Traverse literature uses rock abundance. The cube holds elevation
   scatter. A rock-abundance layer, or a documented mapping, would make the tool rules more defensible.

---

## 8. Conflicts and open questions

| Topic | Values | Which to trust |
|---|---|---|
| Suit O2 rate | 0.068 (Apollo), 0.076 (baseline Rev 2), 0.085 (project), 0.114 (Mars design), 0.181 (walk-back) kg/h | Use design for sizing, walk-back for contingency |
| Suit O2 capacity | 0.472 (Apollo), 0.552 (ISS EMU), 0.68 (project) kg | xEMU figure is **[N]** |
| EVA duration | 7 h (data book), 8 h (rating), about 10 h (standard), 4 h (Mars trade) | Requirements over data book |
| Reactor size | 40 kWe vs "at least 100 kWe" | 40 kWe demonstrated, 100 kWe unverified |
| Scaled MOXIE power | 18, about 25, 25 to 30 kW for 2 kg/h | Plan 18 to 30 |
| Surface GCR dose | 0.67 mSv/day measured, 0.64 ± 0.12 quoted elsewhere, about 0.5 in the standard's rationale | Use 0.67 measured, 0.9 as design cap |
| Elevation limit | ±2 km (workshop) vs −1 km (landing practice) | Different purposes |
| Dust limit | 0.1 mg/m³ is a draft; authors question the extrapolation from lunar data | Draft, subject to change |
| Pressurized rover duration | 28, 30, 30 to 45, "up to six weeks" days | All concept-stage |
| Sample tube volume | 12.5 cm³ vs 147 cm³ | 12.5 |
| Human drill depth | 100 to 1,000 m vs about 10 m | Old reference architecture |
| EVA hours for 30 sols | 190, 160 or 320 | None; source arithmetic is inconsistent |
| SEIS mass | 3, 11 or 29.5 kg | Unresolved |
| Special-region temperature | −28 °C vs "> 28 °C" | −28 °C; handbook sign is likely a typo |
| Radiation shielding table | In-space 15 and 20 g/cm² vs surface 10 g/cm² | Surface row applies on Mars |

**Open questions:** NASA's actual 2025 decision on maximum Mars surface stay; whether NASA has replaced the
expired crewed-Mars planetary-protection directive; and the xEMU and AxEMU battery and oxygen figures.

---

## 9. Gaps: searched for and not found

- Pressurized rover battery capacity, idle power and energy per km.
- xEMU and AxEMU battery capacity, power draw, cooling water mass and oxygen storage mass.
- Load-specific metabolic cost of carrying tools in Mars gravity.
- DRA 5.0 surface mass breakdown.
- Crew rope, anchor and ascender gear for Mars cliffs; ladders and stairs in a suit; trekking poles; crew
  recovery winches and sand mats.
- Crew-portable ground-penetrating radar, magnetometer and seismometer.
- Handheld Raman and PHOENIX mass and power.
- Suit radio range; beacons dropped on a traverse; surface navigation without GPS.
- Fire suppression for a Mars habitat; emergency beacons and rescue procedures specific to Mars.
- Defibrillator, surgical and dental kit detail; drug shelf-life.
- Batteries, regenerative fuel cells, regolith bricks and sintering, excavator specs, ice-drilling power,
  habitat assembly tools, EVA hours for setup.
- A crewed cave or lava-tube mission architecture.
- UV dose at the surface; a dust-opacity level at which to stop EVA.
- Perseverance wheel-damage statistics.
- Exploration-zone slope, rock and radar criteria tables (the criteria exist; the agents could not read them).

---

## 10. Key sources

All links are as given by the research agents. Anything tagged **[E]** above came from a search excerpt of a
PDF that could not be opened, so open the PDF before relying on a number.

**Mission architecture**
- [DRA 5.0 (NASA SP-2009-566)](https://www.nasa.gov/wp-content/uploads/2015/09/373665main_nasa-sp-2009-566.pdf)
- [DRA 5.0 Addendum 2](https://www.nasa.gov/wp-content/uploads/2015/09/nasa-sp-2009-566-add2.pdf)
- [NASA Moon-to-Mars architecture 2023](https://ntrs.nasa.gov/api/citations/20230002706/downloads/M2MADD_ESDMD-001(TP-20230002706).pdf)
- [NASA 2025 architecture update](https://www.nasa.gov/wp-content/uploads/2025/12/2025-architecture-update-for-publication.pdf)
- [Cannon and Sapp 2025, Mars vicinity crew](https://ntrs.nasa.gov/citations/20250007638)
- [Hoffman et al., reference surface activities](https://ntrs.nasa.gov/citations/20220001816)
- [Mars Destination Operations Team report](https://www.lpi.usra.edu/lunar/strategies/HAT_Mars-DOT-2013-Final-Report.pdf)
- [Mars Surface Reference Mission 2001](https://nss.org/wp-content/uploads/2001-NASA-Mars-Surface-Reference-Mission.pdf)
- [HEO-DM-1002 Mars mission duration](https://ntrs.nasa.gov/citations/20210025427)

**Suits and EVA**
- [NASA SBIR topic EVA.2.S26B (Mars suit PLSS)](https://www.sbir.gov/topics/1012257) **[V]**
- [ICES-2026-127, Mars suit mass](https://ntrs.nasa.gov/citations/20260003038) **[V]**
- [BVAD Rev 2](https://ntrs.nasa.gov/api/citations/20210024855/downloads/BVAD_2.15.22-final.pdf)
- [NASA-STD-3001 Vol 2, spacesuits](https://www.nasa.gov/reference/11-0-spacesuits-vol-2) **[V]**
- [EMU Data Book](https://www.lpi.usra.edu/lunar/artemis/NASA-EMU-Data-Book-JSC-E-DAA-TN55224.pdf)
- [Strock et al. 2026, EVA fitness review](https://www.nature.com/articles/s41526-026-00619-8)
- [Norcross et al., 10 km walk-back](https://ntrs.nasa.gov/citations/20080014853)
- [Chappell et al., EVA injuries](https://www.lpi.usra.edu/lunar/artemis/ChappellEtAl_NASA-JSC-CN-39092_EVA-Ops-Injuries-And-Compromised-Performance.pdf)
- [Kluis and Diaz-Artiles 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8594431)
- [Belobrajdic et al. 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8115028)

**Mobility and terrain**
- [Costes, Apollo rover mobility](https://ntrs.nasa.gov/api/citations/19730008090/downloads/19730008090.pdf)
- [NASA Moon Base Systems](https://www.nasa.gov/moonbase-systems/)
- [GRC exploration rover concepts](https://www.nasa.gov/wp-content/uploads/2015/06/exploration_rover_concepts_grc.pdf)
- [MSL engineering user guide](https://marsoweb.nas.nasa.gov/landingsites/msl/memoranda/MSL_Eng_User_Guide_v3.pdf)
- [Golombek et al. MER site characterization](https://mars.asu.edu/christensen/docs/golombek_mersites_jgr.pdf)
- [JPL, Spirit sand trap](https://www.jpl.nasa.gov/news/nasa-to-begin-attempts-to-free-sand-trapped-mars-rover/)
- [NASA Photojournal, Purgatory Dune](https://mars.nasa.gov/resources/5855/looking-back-at-purgatory-dune/)
- [Space.com, Opportunity steepest slope](https://space.com/32439-mars-rover-opportunity-steepest-slope.html)
- [JPL, Curiosity wheel damage](https://jpl.nasa.gov/news/breaks-observed-in-rover-wheel-treads)
- [NASA, Perseverance fords river](https://nasa.gov/solar-system/nasas-perseverance-fords-an-ancient-river-to-reach-science-target)
- [Cushing et al., cave skylights](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2007GL030709)

**Science and sampling**
- [Allton, Apollo tool catalog](https://repository-dev.hou.usra.edu/server/api/core/bitstreams/f74b6eee-9954-4c4b-9b3f-17f87af32348/content)
- [Kring, geologic tools](https://www.lpi.usra.edu/science/kring/lunar_exploration/geologicTools.pdf)
- [Naids et al., Artemis geology tools](https://ntrs.nasa.gov/api/citations/20210000242/downloads/Developing%20Geology%20Sampling%20Tools_Lunar%20Surface%20Science%20Workshop_FINAL_2021.pdf)
- [Artemis III science definition report](https://science.nasa.gov/wp-content/uploads/2023/07/artemis-iii-science-definition-report-12042020c.pdf)
- [MEPAG human mission science objectives](https://www.lpi.usra.edu/mepag/reports/reports/MHMSOTT-report-final.pdf)
- [JPL, Perseverance sample tubes](https://www.jpl.nasa.gov/news/a-martian-roundtrip-nasas-perseverance-rover-sample-tubes/)
- [Leonardo, ExoMars drill](https://space.leonardo.com/documents/16277711/19573930/ExoMars_LQ_mm07795_.pdf?t=1538987564303)
- [Sehlke et al. 2019, portable instrument suites](https://pmc.ncbi.nlm.nih.gov/articles/PMC6442242)
- [Beaton et al. 2019, analog science operations](https://pmc.ncbi.nlm.nih.gov/articles/PMC6442237)
- [COSPAR planetary protection policy](https://cosparhq.cnes.fr/assets/uploads/2024/07/PP-Policy_SRT_220-July-2024.pdf)
- [NASA planetary protection handbook](https://ntrs.nasa.gov/api/citations/20240016475/downloads/PlanetaryProtection_Hdbk_2024_Final_For508ing_comp.pdf)

**Power, ISRU and construction**
- [NASA, MOXIE completes mission](https://www.nasa.gov/missions/mars-2020-perseverance/perseverance-rover/nasas-oxygen-generating-experiment-moxie-completes-mars-mission/) **[V]**
- [Hoffman et al. 2022, MOXIE](https://pmc.ncbi.nlm.nih.gov/articles/PMC9432831/) **[V]**
- [NASA Fission Surface Power](https://www.nasa.gov/exploration-systems-development-mission-directorate/fission-surface-power/)
- [NASA FSP directive 2025](https://www.nasa.gov/wp-content/uploads/2025/08/nasa-fsp-directive-aug42.pdf)
- [Kleinhenz and Paz, ascent propellant plant](https://ntrs.nasa.gov/citations/20170001421)
- [JPL, InSight dust cleaning](https://www.jpl.nasa.gov/news/for-insight-dust-cleanings-will-yield-new-science/)
- [JPL, SWIM ice map](https://www.jpl.nasa.gov/news/nasa-is-locating-ice-on-mars-with-this-new-map/)
- [Gakis and Atri, shielding](https://arxiv.org/html/2205.13786v3)
- [NASA, Martian dust exposure limits](https://www.nasa.gov/general/establishing-crew-exposure-limits-of-martian-dust/) **[V]**
- [NASA, Perseverance dust findings](https://www.nasa.gov/missions/mars-2020-perseverance/nasas-perseverance-offers-clues-to-protect-crews-from-mars-dust)
- [NASA podcast, environments hazard](https://www.nasa.gov/johnson/HWHAP/hazard-5-environments)
- [ISS National Lab, tools in space](https://issnationallab.org/iss360/innovation-in-focus-tools-in-space/)
- [NASA 3D-printed habitat challenge](https://www.nasa.gov/prizes-challenges-and-crowdsourcing/centennial-challenges/3d-printed-habitat-challenge/)

**Medical, radiation and comms**
- [NASA-STD-3001 Vol 1, s4 human performance](https://www.nasa.gov/reference/4-0-human-performance/) **[V]**
- [NASA-STD-3001 s3 health and medical care](https://www.nasa.gov/reference/3-0-health-and-medical-care/)
- [NASA-STD-3001 s6 medical operations](https://www.nasa.gov/reference/6-0-medical-operations/)
- [SwRI, first surface radiation measurements](https://www.swri.org/newsroom/press-releases/swri-scientists-publish-first-radiation-measurements-the-surface-of-mars) **[V]**
- [Löwe et al. 2025, solar storm nowcasting](https://arxiv.org/html/2502.02469v1) **[V]**
- [NASA SRAG](https://srag.jsc.nasa.gov/spaceradiation/how/how.cfm)
- [NASA Orion crew systems](https://www.nasa.gov/reference/crew-systems-2)
- [Wang et al. 2025, Martian dust health](https://pmc.ncbi.nlm.nih.gov/articles/PMC11815326/)
- [Hecht et al. 2009, perchlorate](https://pubmed.ncbi.nlm.nih.gov/19574385/)
- [NASA Mars Relay Network](https://science.nasa.gov/mars/mars-relay-network/)
- [ASCEND 2022, delays and blackouts](https://ntrs.nasa.gov/citations/20220013418)

**Sites**
- [Hoffman and Bussey 2016, landing sites](https://ntrs.nasa.gov/citations/20160001040)
- [Mashal et al. 2025, exploration-zone screening](https://iopscience.iop.org/article/10.3847/PSJ/ade30e)
- [Bell et al. 2022, Jezero results](https://pmc.ncbi.nlm.nih.gov/articles/PMC9683734)
- [NASA, Perseverance distance record](https://science.nasa.gov/blogs/perseverance-mars-rover/2026/10/12/nasas-perseverance-sets-off-world-record-for-total-distance-driven)
- [NASA 2024 landing site study](https://www.nasa.gov/wp-content/uploads/2024/09/dsl-analyzing-proposed-mars-landing-sites-final-8-23-24-508.pdf)

**Consumables**
- [Ichimura and Yamashiki 2025, BVAD values](https://www.frontiersin.org/journals/space-technologies/articles/10.3389/frspt.2024.1461389/full)
- [Lynch et al., logistics rates beyond LEO](https://ntrs.nasa.gov/api/citations/20230012635/downloads/Logistics%20Rates%20and%20Assumptions%20Beyond%20LEO%20V5.pdf)
- [NASA SEV fact sheet](https://www.nasa.gov/wp-content/uploads/2015/08/464826main_sev_factsheet_508.pdf?emrc=0855ca)
- [JAXA pressurized rover appendix](https://humans-in-space.jaxa.jp/en/biz-lab/news/item/004354/Appendix.pdf)
