## Summary

A crisp two-part click for the planner (`frontend/juice.js`): a "tk" on press (a ~1 ms high-passed noise snap,
a short falling resonant body, a light low thump) and a lighter, higher "tik" on release. Slider detents get
tiny ticks pitched by the slider's position. Pitch varies a few percent per click, it pans toward where you
clicked, and Enter/Space on a focused button click too. Synthesized with Web Audio; the 🔊/🔇 toggle in the badge
panel still applies.

**Try it:** open the planner and click any button, hold a click to hear press and release separately, or drag
the time slider.

Also adds the hand-written summary to `PR-061-feat-gk-juice.md`.

## Merge conflicts

- `docs/changelog/PR-061-feat-gk-juice.md` (merging main into the branch): main had only the generated block,
  the branch had a summary on top of the identical block. **Combined**: summary kept, main's block kept unchanged.
