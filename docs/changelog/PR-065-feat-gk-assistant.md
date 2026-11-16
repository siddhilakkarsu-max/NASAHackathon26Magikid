## Summary

The planner assistant is up to date with everything added since it was written:

- **System prompt** (`assistant.py`): rewritten. It covers how to answer (short, plain, never invent numbers, one
  question at a time), every current feature (plan where the camera looks, routes and their safety checks, Walker's
  view, the game, all layers, the moons, the overview, the tour, the badges) and speaks as Helmut.
- **Six new actions**, handled in `frontend/maps_ui.js` by pressing the planner's own controls: `show_moons`,
  `show_tracks`, `play_overview`, `start_tour`, `play_game` and `show_badges`. Plus "topographic" for the
  `map:terrain` layer and a "Play the game" chip after a plan.
- **Offline:** the built-in rules understand them all. Goal sentences ("find olivine near the rover tracks") are
  not hijacked.
- **Page state:** the page tells the assistant its layer, moons, overview, game and explorer level.

**Try it:** open the Assistant and type "show me phobos", "give me a tour", "show rover tracks", "show my badges"
or "who are you".

Tests: `tests/test_assistant_features.py` (7). No merge conflicts.
