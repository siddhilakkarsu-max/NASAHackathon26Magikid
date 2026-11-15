# Git Workflow — Hackathon Rules

## 📛 Identity
DEVELOPER_NAME = your-name-here   # ← CHANGE THIS. Lowercase, no spaces. e.g. alice

## Rules — Follow These on Every Session Without Being Asked

### 🚀 Session Start

1. Run `git status` to see the current state.
2. Check which branch you are on with `git branch`.
3. If you are NOT on `feat/DEVELOPER_NAME`:
   - Branch does NOT exist yet:
     ```bash
     git checkout main
     git pull
     git checkout -b feat/DEVELOPER_NAME
     ```
   - Branch ALREADY exists:
     ```bash
     git checkout feat/DEVELOPER_NAME
     git merge main
     ```
4. **Discover the repo structure automatically:**
   - Run `find . -maxdepth 1 -type d | grep -v '^\.$' | grep -v '.git'` to list top-level folders.
   - Run `git log --all --oneline --name-only --format='' | sort | uniq` to see which files each branch has touched.
   - From this, infer which folders each developer owns based on where their branch has made changes.
   - If this is the first session and no ownership is clear yet, ask me: "I can see these folders: [list]. Which are you working in?"
   - Store the inferred ownership as a summary and mention it in your confirmation message.

5. Confirm: "Ready on branch feat/DEVELOPER_NAME. You own: [folders]. Here's what changed since last time: [summary of recent commits]"

### 🗂️ Dynamic Ownership Enforcement

6. Before editing any file, check which branch last modified it:
   ```bash
   git log --all --oneline -- path/to/file
   ```
   If a file was last modified by a different developer's branch, tell me before touching it:
   "This file was last edited by [other branch]. Do you want me to edit it anyway, or should we coordinate first?"

7. Never silently edit a file that belongs to another developer's area. Always ask first.

---

### 💾 While Working

5. After every meaningful working state, commit immediately:
   ```bash
   git add .
   git commit -m "short description of what works now"
   ```

6. **Good commit messages:** "add login form", "connect auth API", "fix crash on empty state", "agent: scaffold dashboard layout"
   **Bad commit messages:** "stuff", "wip", "aaa", "fix", "changes"

7. NEVER commit broken code. If something is unfinished, tell me before committing.

8. NEVER commit directly to main. If you notice you are on main, stop and ask me.

9. Before any large rewrite, tell me and commit the current working state first.
   This is our rollback point if the rewrite goes wrong.

---

### 🔄 Syncing With the Team

10. Every 60–90 minutes, or when a teammate says "I merged to main", pull their work in:
    ```bash
    git checkout feat/DEVELOPER_NAME
    git merge main
    ```
    If any conflicts appear, STOP and tell me — do NOT resolve them silently (see Conflicts below).

---

### 📤 Merging Your Work to Main

11. When I say "merge", "sync to main", or "my feature is done", run:
    ```bash
    git checkout main
    git pull
    git merge feat/DEVELOPER_NAME
    git push
    git checkout feat/DEVELOPER_NAME
    ```

12. If the merge fails due to conflicts, STOP and show me the conflicting files before doing anything else.

---

## 🔥 Conflict Resolution

If a merge conflict occurs:

1. **STOP.** Do not auto-resolve. Never pick a side without asking.
2. Show me the conflicting file(s) and explain what each version does in plain English.
3. Ask me: "Version A does X. Version B does Y. Which should we keep, or should we combine them?"
4. Only after I decide, resolve the conflict markers, then:
   ```bash
   git add .
   git commit -m "resolve conflict in [filename]"
   ```

### Before keeping one side of a conflict

5. Never keep one whole side of a file ("ours"/"theirs") without first checking what the other side changed:
   ```bash
   git diff $(git merge-base HEAD MERGE_HEAD) MERGE_HEAD -- path/to/file   # what main/the other branch added
   ```
   Every line it added must still be in the result, unless we decided together to drop it.
6. Write the resolution into the PR's changelog file (below): file, which version was kept or how they were
   combined, and why.

---

## 📝 Changelog: one file per merged PR (every teammate and every agent)

The shared `CHANGELOG.md` caused merge conflicts, so it is now history only: **don't add to it**.
Each pull request gets its own file in `docs/changelog/`, so two people never edit the same changelog file.

1. Open the PR first to get its number, then on your branch create
   `docs/changelog/PR-<NNN>-<branch>.md` (3-digit number, e.g. `PR-034-feat-alice.md`) with a short
   human summary: what changed, why, how to try it, and any merge conflicts you resolved and how.
2. Run the generator; it adds the facts (commits, files changed, conflicts it detects by re-running every merge)
   between its AUTO markers and keeps your summary:
   ```bash
   python tools/pr_changelog.py          # rewrites docs/changelog/ (needs a full clone, not --depth 1)
   python tools/pr_changelog.py --check  # fails if any merged PR has no changelog file
   ```
3. Commit the changelog file with the PR. After the merge, whoever merged it runs the generator on main again
   so the merge itself is recorded, and commits it in their next PR.
4. A PR without its changelog file is not ready to merge.

---

## ⛔ Never Do These

- Never `git push --force` on any branch
- Never `git reset --hard` without asking me first
- Never delete a branch without asking
- Never commit `.env` files, API keys, or passwords (even test ones)
- Never edit a file last touched by another developer's branch without asking first
- Never add entries to the shared `CHANGELOG.md`: use `docs/changelog/PR-<NNN>-<branch>.md`

---

## 📊 Useful Status Commands

Run these whenever I ask "where are we?" or "what's the current state?":

```bash
git log --oneline -10    # last 10 commits
git diff                 # unstaged changes
git diff --staged        # changes about to be committed
git branch               # all branches (* = current)
git status               # full current state
```

---

## ✅ End of Session

Before we stop, remind me to:

1. Commit any uncommitted work — even unfinished work:
   ```bash
   git add .
   git commit -m "wip: [description of what's in progress]"
   ```
2. Push the branch:
   ```bash
   git push origin feat/DEVELOPER_NAME
   ```
3. Tell teammates: what you built, what's merged, what's still on your branch.
