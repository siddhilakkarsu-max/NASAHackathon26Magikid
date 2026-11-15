## Summary (Siddhi)

PR #35, branch `feat/siddhi`.

**More regions, not just Jezero**
- Region menu: "More places (load in about a minute)" lists all 22 named sites not built yet; choosing one flies
  there, builds its data cube with a progress message and switches to it.
- `config.SITES` adds the Murray Lab places that weren't sites yet: Olympus Mons, Capri Chasma, Coloe Fossae,
  Shalbatana Vallis, Valles Marineris, Cavi Angusti, Medusae Fossae, Nicholson, Zunil, Milankovič, Terra Sirenum.

**Try it:** run the app, open the Region menu, pick e.g. "Gale crater (Curiosity)" and wait about a minute.

Also: `tools/pr_changelog.py` keeps a summary written before the merge (no AUTO markers yet) on top of the
generated section; changelog file for PR #34.

**Merge conflicts:** none; the branch merges cleanly into main.
