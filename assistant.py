"""The map assistant: a chat box where the astronaut types a sentence and the planner answers, asks what it needs
(time of day, how they travel) and drives the map (plan a mission, play the route, Walker's view, layers, the moons,
the overview, the tour, the game, the badges). In the page it speaks as Helmut, the pixel astronaut beside the chat.

reply(messages, state, memo) -> {"reply", "chips", "actions", "memo", "source"}
  messages: the chat so far, [{"role": "user"|"assistant", "text": ...}] (the last one is the user's new message)
  state:    what the page shows now: region, hour, vehicle, has_mission, candidates, places (names it can fly to)
  memo:     what this chat has settled so far (goal, hour, vehicle...); returned updated, sent back next turn

Built-in rules understand the common requests without any AI service, so the demo works offline. When the rules
don't recognise a message and OPENROUTER_API_KEY is set, a free AI model is asked instead and its JSON answer is
checked against the same list of actions (it can never do anything the buttons can't).
"""
import json
import re

from config import MISSION_VEHICLES, PRIORITIES

ACTIONS = {
    "set_goal": "goal (text): the science goal to plan for",
    "set_time": "hour (0-24): local solar time the walk starts",
    "set_season": "ls (0-360): season",
    "set_vehicle": f"vehicle: one of {', '.join(MISSION_VEHICLES)}",
    "set_priority": f"priority: one of {', '.join(PRIORITIES)}",
    "go_to": "place (text): fly to and select a place by name",
    "plan_mission": "plan with the current goal, time and vehicle",
    "walker_view": "stand on the ground at eye height along the selected route",
    "play_route": "animate the traveller along the selected route",
    "select_option": "n (1-3): show route option n",
    "show_layer": "layer: map layer id ('' to clear)",
    "whole_mars": "zoom out to the whole planet",
    "open_help": "open the how-to manual",
    "show_moons": "view: 'system' (Mars with both moons), 'phobos' or 'deimos'",
    "show_tracks": "show the real tracks driven by the Perseverance and Curiosity rovers",
    "play_overview": "play the animated overview (Mars turning, its moons on their orbits)",
    "start_tour": "kind: 'tour' (autoplay tour of every feature, with captions) or 'flythrough' (10 seconds)",
    "play_game": "open the selected route as a first-person survival game with a leaderboard (new tab)",
    "show_badges": "open the explorer badges and XP the user has earned",
}
MOON_VIEWS = ("system", "phobos", "deimos")
TOUR_KINDS = ("tour", "flythrough")
LAYERS = {   # words -> layer id the page understands (regional data layers and global weather / map views)
    "radiation": "radiation_dose", "dose": "radiation_dose", "cosmic": "radiation_dose",
    "temperature": "global_temperature", "temp": "global_temperature", "cold": "global_temperature",
    "hot": "global_temperature", "warm": "global_temperature",
    "wind": "wind_direction", "dust": "dust_opacity", "pressure": "surface_pressure",
    "slope": "slope", "steep": "slope", "mineral": "science", "minerals": "science", "clay map": "science",
    "elevation": "elevation", "height": "elevation", "topography": "elevation",
    "shelter": "shelter", "firm": "firmness", "firmness": "firmness", "sand": "firmness",
    "sunlight": "illumination", "shadow": "illumination", "suitability": "suitability", "best places": "suitability",
    "albedo": "albedo", "photo": "map:ctx", "photos": "map:ctx", "imagery": "map:ctx",
    "topographic": "map:terrain", "topo": "map:terrain", "terrain map": "map:terrain", "relief": "map:terrain",
}
LAYER_NAMES = {"radiation_dose": "radiation dose", "global_temperature": "ground temperature",
               "wind_direction": "wind", "dust_opacity": "dust in the air", "surface_pressure": "air pressure",
               "slope": "slope", "science": "minerals and science targets", "elevation": "elevation",
               "shelter": "minutes to shelter", "firmness": "ground firmness", "illumination": "sunlight on slopes",
               "suitability": "mission suitability", "albedo": "albedo", "map:ctx": "detailed photos", "map:terrain": "the topographic map", "": "no layer"}

SCIENCE = r"clay|carbonate|olivine|sulfate|sulphate|hydrat|silica|opal|serpentin|mineral|water|ice|delta|sediment|" \
          r"rock|sample|fossil|life|biosignature|lava|volcan|dune|layer|outcrop|crater rim|landing spot|flat spot|" \
          r"explore|study|investigate|look for|find|search for|collect|visit|survey"
TIME_WORDS = [(r"\bsunrise|\bdawn", 7.0), (r"\bearly morning", 7.5), (r"\bmorning", 9.0),
              (r"\bnoon|\bmidday|\blunch", 12.0), (r"\bafternoon", 15.0), (r"\bsunset|\bdusk|\bevening", 17.5),
              (r"\bnight|\bmidnight", 22.0)]
VEHICLE_WORDS = [(r"pressuri[sz]ed|\bbuggy|\bcabin|closed rover", "buggy"),
                 (r"\bbike|scout|two[- ]wheel", "two_wheel"),
                 (r"\blrv|open rover|crew rover|\brover\b|\bdrive|\bcar\b|four[- ]wheel", "four_wheel"),
                 (r"on foot|\bwalk(ing)?\b|\bhike|\bsuit\b|by foot|\bfoot\b", "on_foot")]
PRIORITY_WORDS = [(r"safe", "safety"), (r"fast|quick|speed", "speed"), (r"energy|battery|power", "energy")]
SEASON_WORDS = [(r"dust storm season|storm season", 250.0), (r"spring", 0.0), (r"summer", 90.0),
                (r"autumn|\bfall\b", 180.0), (r"winter", 270.0)]
TIME_CHIPS = ["Morning (09:00)", "Midday (12:00)", "Afternoon (15:00)", "Keep 11:00"]
VEHICLE_CHIPS = ["On foot", "Open rover", "Pressurized rover", "Scout bike"]
AFTER_PLAN_CHIPS = ["Walker's view", "Play route", "Play the game", "Show radiation"]


def _hhmm(h):
    return f"{int(h):02d}:{int(round((h % 1) * 60)) % 60:02d}"


def _find(table, text):
    for pattern, value in table:
        if re.search(pattern, text):
            return value
    return None


def _hour(text):
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b(?!\s*(?:km|m\b|%|°|deg|sol))", text)
    if m and (m.group(2) or m.group(3) or re.search(r"\b(at|by|around|time)\s+\d", text)):
        h = int(m.group(1)) + int(m.group(2) or 0) / 60
        if m.group(3) and m.group(3).startswith("p") and h < 12:
            h += 12
        if m.group(3) and m.group(3).startswith("a") and int(m.group(1)) == 12:
            h -= 12
        if 0 <= h <= 24:
            return round(h, 2)
    if re.search(r"keep 11|\bdefault\b|doesn.t matter|don.t care|any ?time|whenever", text):
        return 11.0
    return _find(TIME_WORDS, text)


def _place(text, places):
    t = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    best = None
    for name in places or []:
        key = re.sub(r"\(.*?\)", "", name.lower()).strip()
        words = [w for w in re.sub(r"[^a-z0-9 ]", " ", key).split() if w not in ("crater", "the", "of")]
        if words and all(re.search(rf"\b{re.escape(w)}", t) for w in words[:2]):
            if best is None or len(key) > len(best[1]):
                best = (name, key)
    return best[0] if best else None


def _goal_text(text):
    g = re.sub(r"^(hi|hey|hello|ok|okay|so|please|can you|could you|i('d| would)? (want|like|need) to|"
               r"i('m| am) (looking|trying) to|let'?s|help me|plan a mission to|plan a walk to|plan)\s+", "",
               text.strip(), flags=re.I)
    g = re.sub(r"\b(in|at) the (morning|afternoon|evening)|\bat (sunrise|dawn|noon|midday|sunset|night)|"
               r"\bon foot|\bby (rover|bike|foot)|\bin (a|the) (pressuri[sz]ed )?rover", "", g, flags=re.I)
    return re.sub(r"\s+", " ", g).strip(" .,!?") or text.strip()


def _vehicle_label(k):
    return MISSION_VEHICLES.get(k, {}).get("label", k).split(" (")[0].lower()


def _features(low, has_mission, memo):
    """Requests for the newer parts of the planner: moons, rover tracks, overview, tour, game, badges, who I am."""
    def out(reply, actions=(), chips=()):
        return dict(reply=reply, chips=list(chips), actions=list(actions), memo=memo, source="rules")
    # "find olivine near the rover tracks" or "explore the delta on a tour" are goals, not tracks / tour requests
    goal = re.search(r"\b(find|sample|collect|study|investigate|look for|search for|plan|explore|visit|survey)\b", low)
    if re.search(r"who are you|what('?s| is) your name|are you (helmut|a robot|an ai)", low):
        return out("I'm Helmut, the little astronaut beside this chat. Tell me what you want to find on Mars and "
                   "I'll plan a safe walk, or ask me to show the moons, a layer or a tour.",
                   chips=["Find clay where water once flowed", "Show the moons", "Give me a tour"])
    if re.search(r"\bgame\b|survival|play (it|this|the (route|mission|walk)) as|let me play|first[- ]person", low):
        return out("Opening your route as a first-person survival game in a new tab: keep your oxygen up and get "
                   "back safely." if has_mission else "Opening the Marswalk game in a new tab. Plan a route first "
                   "and it will play your own mission.", [{"type": "play_game"}],
                   chips=[] if has_mission else ["Find clay where water once flowed"])
    if re.search(r"\bbadges?\b|\bxp\b|achievements?|my level\b|what level", low):
        return out("Here are your explorer badges. Trying new parts of the map earns more.", [{"type": "show_badges"}])
    if re.search(r"\bflythrough|fly-through|fly through every", low):
        return out("Here's the 10-second flythrough of every feature.", [{"type": "start_tour", "kind": "flythrough"}])
    if not goal and re.search(r"\btour\b|show me around|walk me through|demo mode", low):
        return out("Starting the autoplay tour. Click anywhere to stop it.", [{"type": "start_tour", "kind": "tour"}])
    if re.search(r"\boverview\b|spin(ning)? (the )?(planet|globe|mars)|rotate (the )?(planet|globe|mars)", low):
        return out("Playing the overview: Mars turning with Phobos and Deimos on their real orbits.",
                   [{"type": "play_overview"}], chips=["Show the moons", "Find clay where water once flowed"])
    moon = re.search(r"\b(phobos|deimos)\b", low)
    if moon or re.search(r"\bmoons\b|\bmoon system|mars'?s? moons?", low):
        view = moon.group(1) if moon else "system"
        text = {"phobos": "Here's Phobos, the bigger moon: it circles Mars three times a day, about 6,000 km up.",
                "deimos": "Here's Deimos, the small outer moon, about 20,000 km up.",
                "system": "Here are Mars and its two moons, Phobos and Deimos, at their real JPL positions."}[view]
        return out(text, [{"type": "show_moons", "view": view}],
                   chips=[c for c in ("Show Phobos", "Show Deimos") if view not in c.lower()] + ["Back to Mars"])
    if re.search(r"back to mars", low):
        return out("Back to Mars.", [{"type": "whole_mars"}])
    if not goal and re.search(r"rover tracks|tracks? of|(perseverance|curiosity)('?s)? (tracks|route|path|drive)|"
                 r"where (did|has) (perseverance|curiosity|the rover) (go|gone|drive|driven)", low):
        return out("Showing where Perseverance and Curiosity really drove.", [{"type": "show_tracks"}])
    return None


def rules(messages, state, memo):
    """Built-in understanding. Returns a reply dict, or None if the message isn't understood."""
    text = (messages[-1]["text"] if messages else "").strip()
    low = text.lower()
    memo = dict(memo or {})
    state = state or {}
    actions, chips, said = [], [], []
    has_mission = bool(state.get("has_mission"))

    hour = _hour(low)
    vehicle = _find(VEHICLE_WORDS, low)
    priority = _find(PRIORITY_WORDS, low) if re.search(r"safe|fast|quick|speed|energy|battery|priorit", low) else None
    ls = _find(SEASON_WORDS, low)
    place = _place(low, state.get("places")) if not re.search(SCIENCE, low) or re.search(
        r"\b(go|fly|take me|show me|jump|zoom)\b.*\bto\b|\bgo to\b", low) else None
    wants_walk = re.search(r"walker|eye[- ]?(level|height)|ground view|first[- ]person|\bpov\b|point of view|"
                           r"what (would i|i would|i'?d|will i|the astronaut would) see|stand on|from the ground|"
                           r"walk (it|the route|along)|on the ground|street view", low)
    wants_play = re.search(r"\bplay\b|animat|watch the route|show me the trip", low)
    option = re.search(r"\b(option|route|choice|plan)\s*#?\s*([123])\b|\b(first|second|third)\b (option|route)", low)
    layer = next((LAYERS[k] for k in sorted(LAYERS, key=len, reverse=True)
                  if re.search(rf"\b{re.escape(k)}", low)), None) if re.search(
        r"\bshow|\bmap|\blayer|\bturn on|\bsee|\bview|\bdisplay|\bwhere is it|\bhow (cold|hot|windy)", low) else None
    if re.search(r"\b(hide|clear|remove|turn off)\b.*\b(layer|colou?rs?|overlay|map)\b", low):
        layer = ""
    just_plan = re.search(r"just plan|go ahead|plan it|plan now|skip|use defaults?|whatever|sounds good|^yes\b|"
                          r"^ok\b|^okay\b|^sure\b|do it", low)
    science = re.search(SCIENCE, low) and not wants_walk and layer is None
    asked = memo.get("asked")

    if re.search(r"^(hi|hey|hello|help|what can you do|how does this work)\b", low) and not science:
        return dict(reply="Hi! Tell me what you want to do on Mars, like \"find clay where water once flowed\", and "
                          "I'll plan a safe Marswalk. I can also fly somewhere, show layers like radiation, or play "
                          "your route.",
                    chips=["Find clay where water once flowed", "Go to Gale crater", "Show radiation", "How to use this map"],
                    actions=[], memo=memo, source="rules")
    if re.search(r"how to use|manual|instructions", low):
        return dict(reply="Opening the manual.", chips=[], actions=[{"type": "open_help"}], memo=memo, source="rules")
    extra = _features(low, has_mission, memo)
    if extra:
        return extra
    if re.search(r"whole (mars|planet)|zoom (all the way )?out|see (all of )?mars", low):
        return dict(reply="Here's the whole planet. Tell me a place or a goal to zoom back in.", chips=[],
                    actions=[{"type": "whole_mars"}], memo=memo, source="rules")

    # answers to the question asked last turn, and settings mentioned anywhere in the sentence
    if hour is not None:
        memo["hour"] = hour
        actions.append({"type": "set_time", "hour": hour})
        said.append(f"start at {_hhmm(hour)}" + (" (dark: it's night on Mars, so plan with lights and less "
                                                  "solar power)" if hour < 6 or hour > 19 else ""))
    if vehicle:
        memo["vehicle"] = vehicle
        actions.append({"type": "set_vehicle", "vehicle": vehicle})
        said.append(f"travel by {_vehicle_label(vehicle)}" if vehicle != "on_foot" else "go on foot")
    if priority:
        actions.append({"type": "set_priority", "priority": priority})
        said.append(f"put {PRIORITIES[priority]['label'].lower()} first")
    if ls is not None:
        actions.append({"type": "set_season", "ls": ls})
        said.append(f"use the season Ls {ls:.0f}°")
    if place:
        actions.append({"type": "go_to", "place": place})
        said.append(f"go to {place}")
    if science and not (asked and len(low.split()) <= 3):
        memo["goal"] = _goal_text(text)
        memo["planned"] = False
        actions.append({"type": "set_goal", "goal": memo["goal"]})
    if asked == "hour" and hour is None and just_plan:
        memo["hour"] = state.get("hour", 11.0)
    if asked == "vehicle" and vehicle is None and just_plan:
        memo["vehicle"] = state.get("vehicle", "on_foot")

    settled = "Okay, I'll " + ", ".join(said) + "." if said else ""

    # a goal waiting to be planned: ask what's missing (one question at a time), then plan
    if memo.get("goal") and not memo.get("planned"):
        if memo.get("hour") is None and not just_plan:
            memo["asked"] = "hour"
            return dict(reply=(settled + " " if settled else "") +
                        f"Got it: {memo['goal']}. What time of day will you head out? The sun angle changes the "
                        "ground temperature, the light and the solar power.",
                        chips=TIME_CHIPS, actions=actions, memo=memo, source="rules")
        if memo.get("vehicle") is None and not just_plan:
            memo["asked"] = "vehicle"
            return dict(reply=(settled + " " if settled else "") +
                        "And how will you travel? On foot you can climb steeper ground; a rover goes farther "
                        "but needs gentler slopes.", chips=VEHICLE_CHIPS, actions=actions, memo=memo, source="rules")
        memo.update(planned=True, asked=None)
        actions.append({"type": "plan_mission"})
        return dict(reply=(settled + " " if settled else "") + "Planning now: I'll find a safe landing spot, the best "
                    "matching places and up to three routes, and check oxygen, storm shelter and the walk back.",
                    chips=[], actions=actions, memo=memo, source="rules", wait_for_mission=True)

    if option:
        n = int(option.group(2)) if option.group(2) else {"first": 1, "second": 2, "third": 3}[option.group(3)]
        actions.append({"type": "select_option", "n": n})
        said.append(f"show option {n}")
    if wants_walk:
        if has_mission:
            actions.append({"type": "walker_view"})
            said.append("put you on the ground at eye height at the start; use Next to walk along")
        else:
            said.append("need a route first for Walker's view: tell me what you want to find")
    if wants_play and has_mission:
        actions.append({"type": "play_route"})
        said.append("play the route")
    if layer is not None:
        actions.append({"type": "show_layer", "layer": layer})
        said.append(f"show {LAYER_NAMES.get(layer, layer)}" if layer else "clear the map layer")

    # changed the time / vehicle / priority / season after a plan: plan again so the routes match
    replan = has_mission and memo.get("goal") and any(a["type"] in ("set_time", "set_vehicle", "set_priority",
                                                                    "set_season") for a in actions)
    if replan:
        actions.append({"type": "plan_mission"})
        said.append("re-plan with that")
    if not actions:
        if asked == "hour":
            return dict(reply="Sorry, what time? For example \"morning\", \"3 pm\" or \"keep 11:00\".",
                        chips=TIME_CHIPS, actions=[], memo=memo, source="rules")
        if asked == "vehicle":
            return dict(reply="On foot, or which rover?", chips=VEHICLE_CHIPS, actions=[], memo=memo, source="rules")
        return None
    memo["asked"] = None
    chips = AFTER_PLAN_CHIPS if has_mission or replan else ["Find clay where water once flowed", "Go to Gale crater"]
    reply = "Okay, I'll " + ", ".join(said) + "." if said else "Done."
    return dict(reply=reply, chips=chips, actions=actions, memo=memo, source="rules", wait_for_mission=bool(replan))


_SYSTEM = """You are Helmut, the small pixel astronaut who floats beside the chat in the Marswalk Planner and speaks for
it. The planner is a map of Mars that plans safe walks and drives for astronauts from real NASA data.

How to answer
- One to three short, friendly sentences in plain words, no markdown. A little warmth is good; don't overdo the persona.
- When the user wants something the map can do, do it with actions rather than describing buttons.
- To plan you need a goal, a start time and how they travel. Ask ONE short question for whatever is missing. If they
  say "just plan" or don't mind, plan with the current settings.
- Never invent numbers (distances, oxygen, doses, temperatures): the planner computes them and shows them after a plan.
- If something isn't possible, say so in a few words and offer the closest thing that is.
- Questions (is it safe, what is clay, how much oxygen, why this route) get an answer in words. Change settings
  or the map only when the user asks for it, or when it plainly helps (then say what you changed).
- Several requests in one message ("show the moons, then start a tour"): include every action, in order.

What the planner can do
- Plan anywhere on Mars: a plan uses the place in the middle of the map (the region reads "Anywhere on Mars").
  To plan somewhere specific, go_to the place first. A new area loads in seconds with a progress bar at the top;
  its mineral maps keep loading in the background.
- A plan gives up to three routes from a safe landing spot. Each is checked for oxygen and battery to spare, the walk
  back if the vehicle breaks, minutes to storm shelter, and radiation. They appear under Results and in a
  "routes ready" card.
- Travel: on foot (steepest ground, shortest range), open rover, pressurized rover, scout bike. Priorities: safety,
  speed or energy.
- After a plan: Walker's view (stand at eye height and step along the route), play the route as an animation, or play
  it as a first-person survival game with a leaderboard (play_game; it opens a new tab). play_game also works
  before any plan: it opens the game's menu of real, ready-made missions. Suggest the game to first-time visitors.
- Map layers: radiation dose, ground temperature, wind, dust, air pressure, slope, minerals and science targets,
  elevation, minutes to shelter, ground firmness, sunlight on slopes, mission suitability, albedo, sharp CTX photos,
  the topographic map (id map:terrain), and the real Perseverance and Curiosity rover tracks (show_tracks).
- Time of day and season change light, temperature and solar power. Night needs lights. Ls 180-330 is dust storm season.
- Mars's moons Phobos and Deimos at their real JPL positions (show_moons), and an animated overview of Mars turning
  with its moons (play_overview).
- An autoplay tour of every feature, or a 10-second flythrough (start_tour). A how-to manual (open_help).
- Explorer badges and XP for trying features (show_badges).

Reply with JSON only: {{"reply": "...", "chips": ["up to 4 short suggested replies"], "actions": [{{"type": ...}}]}}
Actions you may use (fields after the colon):
{actions}
Current page: {state}
Settled in this chat: {memo}"""


def ai(messages, state, memo):
    """Ask the free AI model (search.ai_write); None if unavailable or its answer can't be used."""
    import search
    convo = "\n".join(f"{m.get('role', 'user')}: {m.get('text', '')}" for m in messages[-8:])
    system = _SYSTEM.format(actions="\n".join(f"- {k}: {v}" for k, v in ACTIONS.items()),
                            state=json.dumps({k: v for k, v in (state or {}).items() if k != "places"})[:1000],
                            memo=json.dumps(memo or {}))
    text = search.ai_write(system, convo + "\nassistant (JSON):", max_tokens=500)
    if not text:
        return None
    try:
        data = search._json_object(text)
        reply = str(data.get("reply", "")).strip()
    except (ValueError, AttributeError, TypeError):
        return None
    if not reply:
        return None
    actions = []
    for a in data.get("actions") or []:
        if not isinstance(a, dict) or a.get("type") not in ACTIONS:
            continue
        if a["type"] == "set_vehicle" and a.get("vehicle") not in MISSION_VEHICLES:
            continue
        if a["type"] == "set_priority" and a.get("priority") not in PRIORITIES:
            continue
        if a["type"] == "show_moons" and a.get("view", "system") not in MOON_VIEWS:
            continue
        if a["type"] == "start_tour" and a.get("kind", "tour") not in TOUR_KINDS:
            continue
        actions.append({k: v for k, v in a.items() if isinstance(v, (str, int, float))})
    memo = dict(memo or {})
    for a in actions:
        if a["type"] == "set_goal":
            memo.update(goal=str(a.get("goal", ""))[:300], planned=False)
        if a["type"] == "set_time":
            memo["hour"] = a.get("hour")
        if a["type"] == "set_vehicle":
            memo["vehicle"] = a["vehicle"]
        if a["type"] == "plan_mission":
            memo["planned"] = True
    chips = [str(c)[:40] for c in (data.get("chips") or [])][:4]
    return dict(reply=reply[:600], chips=chips, actions=actions, memo=memo, source="ai",
                wait_for_mission=any(a["type"] == "plan_mission" for a in actions))


def reply(messages, state=None, memo=None):
    """The AI decides: what to say, which suggestions to offer and which actions to take (validated in ai()).
    The keyword rules only stand in when no AI is configured or reachable, or its answer can't be used, so the
    chat still works offline."""
    out = ai(messages, state, memo)
    if out is None:
        out = rules(messages, state, memo)
    if out is None:
        out = dict(reply="I didn't catch that. Try a goal (\"find carbonates near the crater rim\"), a place "
                         "(\"go to Olympus Mons\"), or \"show radiation\".",
                   chips=["Find clay where water once flowed", "Go to Gale crater", "Show radiation",
                          "How to use this map"],
                   actions=[], memo=dict(memo or {}), source="rules")
    out.setdefault("wait_for_mission", False)
    return out
