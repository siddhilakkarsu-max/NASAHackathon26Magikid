"""The assistant knows the newer parts of the planner (moons, rover tracks, overview, tour, game, badges, Helmut),
offline through the built-in rules, and the AI path only passes on valid actions for them."""
import json

import assistant

PLACES = ["Jezero crater (Perseverance)", "Gale crater (Curiosity)", "Olympus Mons"]


def say(text, memo=None, **state):
    state.setdefault("places", PLACES)
    return assistant.reply([{"role": "user", "text": text}], state, memo or {})


def first(out):
    return out["actions"][0] if out["actions"] else None


def test_moons():
    assert first(say("show me phobos")) == {"type": "show_moons", "view": "phobos"}
    assert first(say("fly to Deimos")) == {"type": "show_moons", "view": "deimos"}
    out = say("show the moons")
    assert first(out) == {"type": "show_moons", "view": "system"} and "Back to Mars" in out["chips"]
    assert first(say("back to mars")) == {"type": "whole_mars"}


def test_tour_flythrough_overview():
    assert first(say("give me a tour")) == {"type": "start_tour", "kind": "tour"}
    assert first(say("quick flythrough please")) == {"type": "start_tour", "kind": "flythrough"}
    assert first(say("play the overview")) == {"type": "play_overview"}


def test_game_badges_tracks_and_who_am_i():
    assert first(say("can I play this as a game", has_mission=True)) == {"type": "play_game"}
    assert "Plan a route first" in say("open the game")["reply"]
    assert first(say("show my badges")) == {"type": "show_badges"}
    assert first(say("where did perseverance go")) == {"type": "show_tracks"}
    who = say("who are you")
    assert "Helmut" in who["reply"] and not who["actions"]


def test_topographic_layer_and_after_plan_chip():
    assert first(say("show the topographic map")) == {"type": "show_layer", "layer": "map:terrain"}
    assert "Play the game" in assistant.AFTER_PLAN_CHIPS


def test_goals_are_not_hijacked():
    out = say("find olivine near the rover tracks")
    assert out["memo"]["goal"] and "show_tracks" not in [a["type"] for a in out["actions"]]
    assert "start_tour" not in [a["type"] for a in say("explore the delta on a tour")["actions"]]
    # the original conversation still works
    a = say("i want to find clay")
    assert a["memo"]["goal"] == "find clay" and "time of day" in a["reply"]


def test_prompt_lists_every_action_and_feature():
    text = assistant._SYSTEM.format(actions="\n".join(assistant.ACTIONS), state="{}", memo="{}")
    for name in ("show_moons", "show_tracks", "play_overview", "start_tour", "play_game", "show_badges"):
        assert name in assistant.ACTIONS and name in text
    for feature in ("Helmut", "Anywhere on Mars", "Phobos", "Walker's view", "survival game", "badges"):
        assert feature in text


def test_ai_answers_are_checked(monkeypatch):
    import search
    answer = {"reply": "Here you go.", "chips": ["Show Deimos"], "actions": [
        {"type": "show_moons", "view": "phobos"}, {"type": "show_moons", "view": "jupiter"},
        {"type": "start_tour", "kind": "flythrough"}, {"type": "start_tour", "kind": "forever"},
        {"type": "play_game"}, {"type": "delete_everything"}]}
    monkeypatch.setattr(search, "ai_write", lambda system, prompt, max_tokens=500: json.dumps(answer))
    out = assistant.ai([{"role": "user", "text": "surprise me"}], {"region": "Anywhere on Mars"}, {})
    assert out["actions"] == [{"type": "show_moons", "view": "phobos"}, {"type": "start_tour", "kind": "flythrough"},
                              {"type": "play_game"}]
