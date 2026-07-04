# CLAUDE.md — working agreement for this project

This file gives Claude Code the conventions and guardrails for building the Lab Server File Organizer. Read `goal.md` for *what* to build; this file is *how* to build it.

## START HERE every session
**Before doing anything else, read `PROGRESS.md`.** It is the living state of the project — what's built, what's verified, what's deferred, the key design decisions, and a dated log. It tells you where things actually stand so you don't re-derive or undo prior work. After you finish a task, edit code, or discover something non-obvious, **append a dated entry to the log in `PROGRESS.md`** (and update its status/deferred sections when they change).

## Project shape
```
labfiles/
  backend/
    main.py            FastAPI app + routes
    tree.py            directory scanning
    deps.py            dependency detection (the careful part)
    moves.py           command generation + execution + audit log
    safety.py          path allowlist / escape prevention
    config.py          env-based config
  frontend/
    index.html         single-page app (zero-build preferred)
    app.js
    styles.css
  tests/
    test_safety.py
    test_deps.py
    test_moves.py
  README.md
```

## Golden rules
1. **Never move or delete anything without explicit confirmation.** The execute endpoint requires `confirmed: true`. Default the whole app to a safe state.
2. **The client never sends commands — only proposed moves.** The server builds and runs the commands. This is a hard boundary.
3. **Re-validate on the server at execute time.** Never trust that the tree the client saw still matches the filesystem.
4. **Path safety is not optional.** Every path from the client goes through `safety.py` resolution + allowlist check before any FS access. Resolve symlinks and `..` first. Reject anything escaping `LAB_ROOT`.
5. **Fail loud, never half-finish silently.** If a batch of moves fails partway, stop, report exactly what succeeded and what didn't.
6. **The tool must fully work with no AI key.** AI is an enhancement; degrade gracefully when `ANTHROPIC_API_KEY` is unset.

## Code conventions
- Python 3.11+, type hints everywhere, `ruff` clean.
- Prefer `pathlib.Path` over string path munging.
- Prefer `shutil.move` for execution; if shelling out, escape with `shlex.quote` on every component — no f-string command building with raw paths.
- Keep `deps.py` pure and testable: input = file paths + move plan, output = warnings. No FS writes, no network.
- Frontend: vanilla JS, no framework unless there's a real reason. No build step so it deploys by copying files. Keep state in plain JS objects.
- No secrets in code. Read from env / config only.

## Testing priorities (write these first, they catch the dangerous bugs)
- `test_safety.py`: `../../etc/passwd`, symlink escapes, absolute paths outside root — all must be rejected.
- `test_deps.py`: known import graphs produce the expected warnings; no false negatives on the obvious cases (a `.py` importing a sibling that stays behind).
- `test_moves.py`: command generation quotes paths with spaces; collision detection fires; execute is a no-op without `confirmed: true`.

## What "done" looks like for each PR
- New endpoint? It has a test and is wired into the frontend or explicitly stubbed.
- Touches moves/execution? It cannot run without confirmation, and it writes to the audit log.
- Touches paths? It goes through `safety.py`.

## Things to deliberately NOT do
- Don't add a database. The filesystem is the source of truth; the only persistent file we write is the append-only audit log.
- Don't add user accounts / heavy auth in v1. Document the SSH-tunnel + localhost default and leave a clear seam for adding auth later.
- Don't optimize the scanner prematurely. Get correctness + path safety first, then add lazy expansion and caching for big trees.
- Don't let the AI feature become load-bearing. It explains and advises; it never executes moves on its own.

## When unsure
Ask before doing anything destructive. For everything else, prefer the simplest thing that satisfies `goal.md` and the golden rules above.
