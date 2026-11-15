# PR #39: Claude Haiku 5.5 as the planner's AI; keep the AI thinking visible

**What changed**
- The planner's AI (reading a goal, explaining the plan, writing the map labels) now uses Claude Haiku 5.5
  through the Anthropic API (`claude_ai.py`) whenever `ANTHROPIC_API_KEY` is set. OpenRouter / the local Ollama
  model stay as the fallback. `CLAUDE_MODEL` and `CLAUDE_EFFORT` (default `medium`) change it.
- "Why this plan" and "Notes on the map" open while the AI works on them, so its thinking shows again (the new
  panel layout had them collapsed).

**Why**
The local model took ~2 minutes per mission and the thinking was hidden; with Claude a mission takes ~15 s and
the thinking streams live.

**How to try it**
Set `ANTHROPIC_API_KEY` in the server's environment (never in the repo), restart uvicorn, plan a mission with a
goal like "find an ancient shoreline with unusual minerals" and watch the thinking under the status line, then
in "Why this plan" and "Notes on the map".

**Merge conflicts**
None: main's documentation commits (#37, #38) merged automatically.
