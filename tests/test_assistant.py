"""The map assistant's built-in rules: the demo conversation works without any AI service."""
import assistant

PLACES = ["Jezero crater (Perseverance)", "Gale crater (Curiosity)", "Olympus Mons"]


def say(text, memo=None, **state):
    state.setdefault("places", PLACES)
    return assistant.reply([{"role": "user", "text": text}], state, memo or {})


def types(out):
    return [a["type"] for a in out["actions"]]


def test_goal_then_time_then_vehicle_then_plan():
    a = say("i want to find clay")
    assert a["memo"]["goal"] == "find clay" and "time of day" in a["reply"] and not "plan_mission" in types(a)
    b = say("morning", a["memo"])
    assert {"type": "set_time", "hour": 9.0} in b["actions"] and b["memo"]["asked"] == "vehicle"
    c = say("on foot", b["memo"])
    assert types(c)[-1] == "plan_mission" and c["wait_for_mission"] and c["memo"]["planned"]


def test_everything_in_one_sentence_plans_straight_away():
    out = say("plan a walk to sample carbonates at 3 pm by rover")
    assert out["memo"]["hour"] == 15.0 and out["memo"]["vehicle"] == "four_wheel"
    assert types(out)[-1] == "plan_mission"


def test_follow_ups_after_a_plan():
    memo = {"goal": "find clay", "hour": 9.0, "vehicle": "on_foot", "planned": True}
    assert types(say("what would i see from the ground", memo, has_mission=True)) == ["walker_view"]
    assert say("show radiation", memo, has_mission=True)["actions"] == [{"type": "show_layer", "layer": "radiation_dose"}]
    again = say("try the afternoon", memo, has_mission=True)
    assert types(again) == ["set_time", "plan_mission"]


def test_places_help_and_unknown():
    assert say("go to gale crater")["actions"] == [{"type": "go_to", "place": "Gale crater (Curiosity)"}]
    assert say("hello")["chips"]
    assert "didn't catch" in say("purple elephants")["reply"]


def test_ground_view_phrasings():
    for t in ("show me what i would see from the ground", "walker's view", "street view please"):
        assert types(say(t, {"goal": "x", "planned": True}, has_mission=True)) == ["walker_view"], t
