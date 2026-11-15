---
title: Marswalk Planner
emoji: 🪐
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Plan walks and rover trips on Mars with real NASA data
---

# Marswalk Planner

Plan a walk or a rover trip anywhere on Mars. Type a goal ("sample clay where water once flowed"), pick how you
travel, and the planner finds the best places, a safe landing spot and a route on real NASA data: elevation, slope,
ground firmness (thermal inertia), CRISM mineral maps, sunlight, temperature and radiation. An AI (Claude) reads
your goal, explains the choice and labels cliffs, soft sand and minerals along the route.

Built for the NASA Space Apps Challenge 2026.

**Using it:** press *Start exploring*, then *Plan* on the left, or type into the search bar. Press **?** for the
manual and **A** for technical details.

**Note:** areas away from Jezero crater load on demand in a few seconds; their mineral maps follow a few minutes
later. This Space restarts from scratch after a period without visitors, so the first visit can take a minute.
