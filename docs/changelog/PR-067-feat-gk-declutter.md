## Summary

The planner's drawers open on their controls instead of paragraphs of explanation. Visible explanatory text across
the panels goes from about 374 to 107 words (`frontend/declutter.js`, one `<script>` line in `index.html`):

- **Hidden for good:** five lines that only repeat their heading, label or the goal placeholder.
- **Behind a small ⓘ** on the label or heading they belong to: region and plan-anywhere help, the lighting note,
  the moon-clock rules and size note, the dust-haze caveat, the photo-grid coverage, how sharp-photo boxes work, and
  the game description. In Results, the "mineral maps cover N%" notes fold behind "N data notes".
- **Status lines** that double as notes (moon status, box tool) fold only while showing their default text;
  errors and step instructions stay visible.

Nothing is deleted from `index.html`: the script only adds classes and ⓘ buttons, so removing its one line undoes it.

**Try it:** open Time, Layers or Area data from the left rail and click an ⓘ; plan a mission and open
"2 data notes" in Results.

No merge conflicts.
