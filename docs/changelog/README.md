# Changelog: one file per merged pull request

Written by `python tools/pr_changelog.py` from git history (see the rule in `AGENTS.md`).
Each file lists the PR's commits, the files it changed and any merge conflicts and how they were
resolved. Hand-written notes go outside the AUTO markers and are kept when the file is regenerated.

| PR | Title | Branch | Merged | Conflicts |
|---|---|---|---|---|
| [#1](PR-001-feat-gk.md) | Add O2/energy budgets with NASA-sourced limits to route planning | `anh-gl-nguyen1762/feat/Gk` | 2026-11-14 | none |
| [#2](PR-002-aisearch.md) | Mission planner, CRISM mineral search and text target search | `siddhilakkarsu-max/aisearch` | 2026-11-14 | 4 file(s) |
| [#3](PR-003-feat-gk.md) | Add gear system: equipment recommendations for the planning agent | `anh-gl-nguyen1762/feat/Gk` | 2026-11-14 | none |
| [#4](PR-004-feat-surface-temperature.md) | Feat/surface temperature | `siddhilakkarsu-max/feat/surface-temperature` | 2026-11-14 | 6 file(s) |
| [#5](PR-005-feat-gk.md) | Add Mars rovers past and planned, plus an Apollo-class crew rover, to the vehicle list | `anh-gl-nguyen1762/feat/Gk` | 2026-11-14 | 1 file(s) |
| [#6](PR-006-aisearch.md) | Stream the AI's reasoning and answers in the mission panel | `siddhilakkarsu-max/aisearch` | 2026-11-14 | 2 file(s) |
| [#7](PR-007-feat-jason-chen10-marsmap.md) | Import MarsMap project snapshot | `siddhilakkarsu-max/feat/jason-chen10-marsmap` | 2026-11-14 | none |
| [#8](PR-008-feat-gk.md) | Route oxygen and energy follow terrain, carried load, reserve and dust | `anh-gl-nguyen1762/feat/Gk` | 2026-11-14 | none |
| [#9](PR-009-feat-gk-persist-kit.md) | Keep the published gear kit across server restarts | `anh-gl-nguyen1762/feat/Gk-persist-kit` | 2026-11-14 | none |
| [#10](PR-010-feat-gk-gear-hookup.md) | Serve the gear system from the main app and link it from the planner | `anh-gl-nguyen1762/feat/Gk-gear-hookup` | 2026-11-14 | none |
| [#11](PR-011-feat-gk-ti-rule.md) | Judge loose ground from measured thermal inertia; add a fine-dust gear rule | `anh-gl-nguyen1762/feat/Gk-ti-rule` | 2026-11-14 | none |
| [#12](PR-012-feat-gk-run-scripts.md) | Add one-command start scripts (run.bat / run.sh) | `anh-gl-nguyen1762/feat/Gk-run-scripts` | 2026-11-14 | none |
| [#13](PR-013-feat-jason-chen10-marsmap.md) | Feat/jason chen10 marsmap | `siddhilakkarsu-max/feat/jason-chen10-marsmap` | 2026-11-14 | none |
| [#14](PR-014-feat-gk-compare.md) | Compare two kits side by side on the gear page | `anh-gl-nguyen1762/feat/Gk-compare` | 2026-11-14 | none |
| [#15](PR-015-feat-gk-checklist.md) | Packing-list mode, CSV export and copy-link on the gear page | `anh-gl-nguyen1762/feat/Gk-checklist` | 2026-11-14 | none |
| [#16](PR-016-feat-gk-presets.md) | One-click demo scenarios and a season control on the gear page | `anh-gl-nguyen1762/feat/Gk-presets` | 2026-11-14 | none |
| [#17](PR-017-aisearch.md) | Marsmap features, Murray Lab maps, route hover with vehicle models, Figma design | `siddhilakkarsu-max/aisearch` | 2026-11-14 | 1 file(s) |
| [#18](PR-018-feat-gk-docs.md) | Document the gear page features, app hookup and run scripts | `anh-gl-nguyen1762/feat/Gk-docs` | 2026-11-14 | none |
| [#19](PR-019-feat-gk-cleanup.md) | Start scripts run app:app; gear tests stop writing the real state file | `anh-gl-nguyen1762/feat/Gk-cleanup` | 2026-11-14 | none |
| [#20](PR-020-feat-gk-mer-demo.md) | Spirit and Opportunity scenarios use a realistic one-sol drive | `anh-gl-nguyen1762/feat/Gk-mer-demo` | 2026-11-14 | none |
| [#21](PR-021-feat-gk-mission-gear.md) | Gear for this mission: link from each mission card to its kit | `anh-gl-nguyen1762/feat/Gk-mission-gear` | 2026-11-14 | none |
| [#22](PR-022-feat-gk-cons-panel.md) | Consumables panel shows the reserve, slope and ground effect, climb and recharge | `anh-gl-nguyen1762/feat/Gk-cons-panel` | 2026-11-14 | none |
| [#23](PR-023-feat-gk-mission-resources.md) | Mission planner costs oxygen and battery with the terrain-aware model (no ranking changes) | `anh-gl-nguyen1762/feat/Gk-mission-resources` | 2026-11-14 | 1 file(s) |
| [#24](PR-024-feat-gk-walkback-o2.md) | Walk-back zone checks suit oxygen and battery, not only hours | `anh-gl-nguyen1762/feat/Gk-walkback-o2` | 2026-11-14 | none |
| [#25](PR-025-aisearch.md) | Plan anywhere on Mars on the 3D terrain, clearer landing errors, partial-coverage read fix | `siddhilakkarsu-max/aisearch` | 2026-11-14 | 1 file(s) |
| [#26](PR-026-feat-gk-vehicles.md) | One vehicle list: mission planner reads the route planner's sourced vehicles (no ranking changes) | `anh-gl-nguyen1762/feat/Gk-vehicles` | 2026-11-14 | none |
| [#27](PR-027-aisearch.md) | Plain language with technical details on the A key, one season slider, Murray map radios, sharp box | `siddhilakkarsu-max/aisearch` | 2026-11-14 | none |
| [#29](PR-029-feat-radiation-layer-fixes.md) | Add modeled Mars radiation layer and fix hidden-panel startup | `siddhilakkarsu-max/feat/radiation-layer-fixes` | 2026-11-14 | none |
| [#31](PR-031-feat-gk.md) | Survival game that plays the planned route, with Play buttons on the planner and gear page | `anh-gl-nguyen1762/feat/Gk` | 2026-11-14 | none |
| [#32](PR-032-feat-jason-chen10-marsmap.md) | Update planner UI, fix map controls, and integrate selected-route game | `siddhilakkarsu-max/feat/jason-chen10-marsmap` | 2026-11-14 | 4 file(s) |
| [#33](PR-033-feat-siddhi.md) | Feat/siddhi | `siddhilakkarsu-max/feat/siddhi` | 2026-11-15 | none |
| [#34](PR-034-feat-siddhi.md) | docs: one changelog file per merged PR, with merge conflicts; team ru… | `siddhilakkarsu-max/feat/siddhi` | 2026-11-15 | none |
