"""Fixes from the full planner QA pass: point lookups reject impossible coordinates, the overview starts close on
Mars, layers without data in the current area are offered only where they exist, and the game is reachable from the
landing page and the map before any plan."""
from pathlib import Path

from fastapi.testclient import TestClient

import app

FRONT = Path(__file__).resolve().parents[1] / "frontend"
client = TestClient(app.app)


def test_point_lookups_reject_impossible_coordinates():
    for q in ("lat=nan&lon=0", "lat=999&lon=0", "lat=0&lon=inf", "lat=0&lon=721"):
        assert client.get(f"/api/point?{q}").status_code == 422, q
        assert client.get(f"/api/pixel?{q}").status_code == 422, q


def test_overview_frames_mars_not_the_whole_moon_system():
    js = (FRONT / "mars_overview.js").read_text(encoding="utf8")
    assert "27000000" not in js and "MARS_FILL" in js


def test_band_layers_follow_the_area_and_minerals_chip_falls_back():
    html = (FRONT / "index.html").read_text(encoding="utf8")
    assert "BAND_LAYERS" in html and '"science"' in html
    ui = (FRONT / "maps_ui.js").read_text(encoding="utf8")
    assert "mineralChoice" in ui and "closeMapManual" in ui
    assert (FRONT / "map_help.js").read_text(encoding="utf8").count("window.closeMapManual") == 1


def test_game_is_one_click_away():
    html = (FRONT / "index.html").read_text(encoding="utf8")
    assert 'id="landingPlay"' in html and 'window.open("game.html"' in html
    launch = (FRONT / "game-launch.js").read_text(encoding="utf8")
    assert "PLAY THE GAME" in launch and "MISSION READY" in launch


def test_map_key_names_every_regional_layer():
    js = (FRONT / "weather_display.js").read_text(encoding="utf8")
    for layer in ("suitability", "science", "minerals", "thermal_inertia", "air_column_vs_gale", "albedo"):
        assert f"{layer}:" in js.split("const titles")[1].split("};")[0], layer
