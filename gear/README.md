# Gear system

Decides which tools, resources and equipment a Mars crew should bring, and says why. The planning agent
calls it as a set of tools. The result is shown on `frontend/kit.html`.

Everything in the catalog and every rule comes from `MISSION_EQUIPMENT_RESEARCH.md`. Read its section 0
first: each number carries a tag (V verified, P published, E excerpt, I inferred, N none) and the page
shows the same tags.

```
gear/sources.py   evidence registry: source ids -> title and URL, plus the V/P/E/I/N tags
gear/catalog.py   about 100 items: what it is, mass, power, rate, who carries it, source, caveats
gear/context.py   MissionContext (the one input), mission archetypes and their defaults
gear/rules.py     the IF/THEN rules and every numeric threshold, each with its evidence
gear/budget.py    consumables and radiation dose, every line with its formula
gear/signals.py   runs the route planner and reads the terrain along the route
gear/engine.py    rules -> manifest: merge, who carries what, carry-load check, totals
gear/tools.py     the tools the agent calls, typed, with generated JSON schemas
gear/api.py       HTTP routes
frontend/kit.*    the page
tests/test_gear.py
```

## Run it

```bash
uvicorn gear_server:server --reload --port 8000     # planner + gear, no change to app.py needed
open http://localhost:8000/kit.html
python -m unittest discover -s tests -v
```

`gear_server.py` mounts the existing app underneath the gear routes. Once these two lines are added to
`app.py` (before the `app.mount("/", ...)` line), `uvicorn app:app` serves everything and the wrapper can go:

```python
from gear.api import router as gear_router
app.include_router(gear_router)
```

## For the planning agent

```python
import gear.tools as gt

tools = gt.tool_specs("anthropic")        # or "openai"; pass these to the model
...
for block in response.content:
    if block.type == "tool_use":
        result = gt.call_tool(block.name, block.input)   # always returns JSON-safe data, never raises
```

Over HTTP: `GET /api/gear/tools?format=anthropic` for the definitions and
`POST /api/gear/tools/{name}` with the arguments as the body.

| Tool | Use it to |
|---|---|
| `list_mission_archetypes` | Get valid mission types, goals, hazards and vehicles. Call first. |
| `get_route_context` | Run the planner for a base and target; get route stats and the terrain along it. |
| `recommend_gear` | The main tool. Returns the kit. `publish=true` shows it on the page. |
| `size_consumables` | Suit and cabin consumables with formulas; surface dose; check of the planner's O2 numbers. |
| `search_gear_catalog` | Look an item up by word, category, carrier or minimum evidence. |
| `get_gear_item` | Full record for one item, with sources and the rules that add it. |
| `list_gear_rules` | Every rule, its evidence, and every threshold. |
| `check_carry_load` | Check a hand-carried set against the per-person limit. |

Typical sequence:

1. `list_mission_archetypes`
2. `get_route_context` for the traverse being planned, to see slope, loose ground, hours and oxygen
3. `recommend_gear` with the mission and `route_request` (or the route and terrain it just got).
   Read `warnings`, `thin_evidence` and `assumptions`.
4. Optionally call again with `adjustments` to add or drop items. Every adjustment needs a reason, which the
   page shows next to the item. Removing a critical item is allowed but is flagged as a warning.
5. `recommend_gear` with `publish=true` and a one-line `note`. The page's "Planner's kit" tab shows it and
   updates itself. Link the user to `/kit.html?tab=published`.

`recommend_gear` returns a compact form by default (`detail: "summary"`) so it stays cheap for the model;
`detail: "full"` is what the page renders.

### MissionContext

Everything is optional except it defaults sensibly from `archetype`. Anything defaulted is listed in
`assumptions` in the result, so the agent can see what it did not specify.

| Field | Meaning |
|---|---|
| `archetype` | `short_stay`, `long_stay`, `traverse`, `drilling`, `isru`, `construction`, `rescue`, `cave` |
| `crew`, `stay_sols` | Crew on the surface; stay in sols |
| `goals` | `biosignatures`, `geology`, `subsurface`, `water_ice`, `atmosphere`, `seismic`, `radiation`, `isru`, `construction` |
| `hazards` | `pit`, `cliff`, `dunes`, `canyon_walls`, `night_ops`, `dust_storm_season` |
| `vehicle` | The traveller for the route, any key in `config.VEHICLES` (`list_mission_archetypes` returns them). Crewed: `astronaut`, `pressurized_rover`, `unpressurized_rover`. Robotic: `sojourner`, `mer`, `small_rover`, `zhurong`, `perseverance`, `rosalind_franklin` |
| `eva_hours`, `eva_days` | Typical EVA length; EVA days over the stay |
| `power` | `battery`, `solar`, `fission` |
| `route`, `terrain` | The `stats` block from `/api/plan` and the terrain signals; or give `route_request` and they are filled in |
| `base_has_shelter` | Rule S2 assumes the base is the storm shelter |

## What the output contains

`items` (and `groups` by category): each with `qty`, `priority` (critical, recommended, optional), `carried_by`
(worn, astronaut, cart, rover, base, deployed, vehicle), mass, `confidence`, and `reasons`, the rules that asked
for it and why. Also `rules` triggered, with the value that tripped each and its threshold; `carry` (load against
the limit and what was moved to a vehicle); `budget`; `warnings`; `assumptions`; `thin_evidence` (items whose
specification is inferred or unsourced); and `adjustments`.

Priority comes from the rule's group: core and safety rules give critical, terrain, science and mission rules give
recommended, and a rule can mark an add as optional.

## Extending it

**Add an item**: one `_i(...)` call in `catalog.py`. Only write a mass, power or rate you can point at a source for;
leave it `None` otherwise and the totals will say "no published mass". Add the source to `sources.py` first.

**Add a rule**: a function in `rules.py` decorated with `@rule(...)`. It returns `None` or a `Hit` with the items it
adds. Put any number it uses in `THRESHOLDS` with an evidence tag; tag your own numbers `I` so the page marks them
tunable. The tests fail if a rule names an item that does not exist.

**Change an archetype's defaults**: `ARCHETYPES` in `context.py`. `basis` is `published` only if the figure is in a
NASA document; otherwise it is `assumed` and the page says so.

## Things to know

- Vehicles are listed in a kit but their mass is not added to the totals. Consumables are sized in the budget, not
  weighed as items.
- The hand-carry limit is 22.7 kg per person (the 50 lbm tool and sample allowance in NASA's Mars suit study,
  excerpt-level source). When a team's load goes over it, items move to a rover if one is in the kit, otherwise a
  hand cart is added.
- Suit oxygen follows NASA's Mars design basis (0.114 kg/h, 0.912 kg). On a planned route the planner adjusts it
  for slope and holds back a 15-20 % reserve. Rule S1 fires when the round trip needs more than what is usable
  after the reserve. The budget then adds the kit's hand-carried load, and a separate warning fires if that load
  pushes the trip past the reserve.
- `published` is held in memory, one kit, and is lost on restart.
