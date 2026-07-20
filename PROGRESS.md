# PROGRESS.md — Lab Server File Organizer

> **Read this first at the start of every session.** It is the living state of the
> project: what's built, what's verified, what's deferred, and a dated log. Append
> to the log whenever you finish, edit, or discover something. Keep it honest —
> if something is untested or broken, say so.

---

## Current status: **v3 usefulness & shipping complete** (2026-06-24)

All five v3 items done: **undo last batch**, a **useful AI advisor**, **tree-wide
search**, **network-exposure hardening** (opt-in `RATE_LIMIT` + `PATH_PRIVACY`), and
**shipping** (Dockerfile, GitHub Actions CI, Playwright E2E, v3 changelog). Two
security-review rounds on the undo + search/privacy/rate-limit code; all HIGH/MEDIUM
findings fixed. **86 passed, 2 skipped (default); +1 Playwright E2E passes; ruff
clean.** Undo + search + privacy mode verified live in-browser. See the v3 log below.

## Earlier: **v2 hardening complete** (2026-06-24)

All five v2 items done: click-to-load truncated dirs, optional `AUTH_TOKEN` gate,
lazy/non-blocking large-tree sizing (+ benchmark), real-directory deploy with
screenshots + README Deploy section, and expanded tests. v1 baseline (still true):

## v1: **complete and verified end-to-end** (2026-06-24)

Every item in `GOAL.md`'s Definition of Done works and has been exercised against a
real directory through the browser: nested-box tree → zoom in place → drag a file
*and* a whole folder → dependency warning on split → preview exact commands →
confirm → files actually move → audit log written → nothing moves without
confirmation.

- **Tests:** 28 passed, 1 skipped (symlink test, needs privilege on Windows). `ruff` clean.
- **Two code reviews done** (read-only slice, then write/execute path); all CRITICAL/HIGH findings fixed.

---

## Architecture (as built)

```
backend/
  config.py   env config (frozen dataclass, lru_cached)
  safety.py   path allowlist — safe_resolve(): anchors relative paths under LAB_ROOT,
              resolves symlinks/.., rejects escapes. SECURITY CRITICAL.
  tree.py     os.scandir scanner -> nested JSON; recursive size/count (mtime-cached);
              depth cutoff + lazy expand; truncation flag; ext sanitized to [a-z0-9].
  deps.py     PURE dependency detection: py imports, relative path literals, shell
              `source`; warns when a moved file is split from a file it references.
  moves.py    collision detection, mv/mkdir command preview (shlex-quoted),
              execute_moves (re-validates, never overwrites/merges, audit log),
              undo_last_batch (reverse last batch; _enc/_dec audit escaping; _MOVE_LOCK).
  ai.py       optional Anthropic advisor; graceful "not configured" without key.
  ratelimit.py  optional fixed-window per-IP limiter (RATE_LIMIT; off by default).
  privacy.py    optional path relativization for clients (PATH_PRIVACY; off by default).
  main.py     FastAPI routes + pydantic models + gate middleware + serves frontend.
frontend/     zero-build ES modules in a paper-notebook design (Caveat/Nunito/JetBrains
              Mono, dotted cream paper, depth-palette nested boxes, free-drag/resize project
              cards via localStorage 'labOrganizer.layout.v1'): index.html, styles.css
              (palettes via inherited CSS custom props --a-*), app.js, api.js, util.js
              (typeMeta), browse.js (tree view + free layout), organize.js (drag/queue/
              preview/execute/toast/undo/AI), search.js (search box + jump-to-hit).
tests/        test_safety/tree/deps/moves/auth/integration + test_undo, test_search,
              test_ai, test_hardening; tests/e2e/ (Playwright, marked `e2e`).
```

### Endpoints
`GET /api/config` · `GET /api/tree` · `GET /api/tree/expand` · `GET /api/dir-stats` ·
`GET /api/search` · `POST /api/analyze-moves` · `POST /api/preview-moves` ·
`POST /api/execute-moves` · `GET /api/undo-info` · `POST /api/undo` ·
`POST /api/ask-ai` · `GET /healthz`

### How to run / test
```bash
LAB_ROOT=/some/dir uvicorn backend.main:app --port 8000   # then open http://127.0.0.1:8000
python -m pytest tests/ -q
python -m ruff check backend/ tests/
```

---

## Key design decisions (don't silently reverse these)

1. **Never overwrite or merge.** If anything already exists at a destination, that
   move fails loud — `force` only skips the all-or-nothing pre-flight gate so a user
   can retry a plan whose conflicts they cleared on disk; it can NEVER clobber a file
   or merge a folder. This intentionally overrides GOAL.md's softer "warning/override"
   wording, because CLAUDE.md golden rules (#1 no move/delete without confirmation,
   #5 fail loud) take precedence. Existing-destination is therefore an **error**, not
   a warning, in both analyze and execute.
2. **Client only proposes {src,dst}; server builds + runs commands.** Hard boundary.
3. **Re-validate at execute time** against the live FS; never trust the client's view.
4. **Every client path goes through `safety.safe_resolve`** before any FS access,
   including `deps.py` (defense-in-depth) and `moves.py`.
5. **AI is never load-bearing** — the tool is fully functional with no key.
6. **Auth is an optional thin seam, not a system.** `AUTH_TOKEN` enables HTTP Basic
   (off by default). Chosen over a bearer token because it needs zero frontend changes.
   Real multi-user/network exposure should still terminate auth at a reverse proxy.
7. **Undo is driven by the audit log alone** (no DB). Forward batches are delimited by
   `BATCH\t<uuid>` markers; undo reverses the most recent batch lacking a matching
   `UNDO\t<id>` marker. Same never-overwrite/confirm/re-validate rules as execute; its
   own audit entries; `UNDO` marker written only on full success. Path fields in the log
   are reversibly escaped (`_enc`/`_dec`) so a filename can't forge a record.
8. **Hardening knobs are opt-in and off by default** (`RATE_LIMIT`, `PATH_PRIVACY`) —
   localhost contract preserved. Path-privacy relativizes at the API boundary;
   `safe_resolve` already re-anchors relative paths inbound, so the contract is
   unchanged. Neither replaces a reverse proxy; out-of-root fallbacks return basenames,
   never absolute paths.

---

## Deferred / known limitations (next-phase candidates)

- ~~**Truncated dirs ("+N more")** are shown as an info note, not click-to-load.~~
  **RESOLVED (v2 task 1):** `offset` paging in `scan_tree` + `/api/tree/expand`; the
  "+N more" button now pages in the rest.
- ~~**No auth** (v1, by design).~~ **RESOLVED (v2 task 2):** optional `AUTH_TOKEN`
  HTTP-Basic gate, off by default; localhost + SSH tunnel still the default posture.
  Reverse-proxy auth remains the recommendation for real multi-user/network exposure.
- ~~**Absolute server paths are returned to the client** by design.~~ **RESOLVED
  (v3 task 4):** opt-in `PATH_PRIVACY` returns paths relative to `LAB_ROOT`. Off by
  default (UI still uses absolute paths in the localhost posture).
- ~~**No rate limiting** (localhost default).~~ **RESOLVED (v3 task 4):** opt-in
  `RATE_LIMIT` (fixed-window per-IP), off by default; not distributed — proxy for that.
  `_dir_stats` is lazy via `/api/dir-stats` (v2). Remaining edge: a single root with an
  enormous subtree still pays one full walk for its own size (off the render path + cached).
- **Junction/reparse-point escapes:** `search` guards against them (`_escapes` real-path
  check); `scan_tree`/`_dir_stats` still rely on symlink-skipping (POSIX target). Low
  risk on Linux; revisit if Windows hosting becomes a real target.
- **Audit parsing assumes one record per line:** filenames are tab/newline-escaped on
  write so this holds; truly pathological names are escaped, not rejected.
- **Scanner structure scan** is now non-blocking; recursive sizing is on-demand. Further
  optimization (e.g. incremental/streamed size aggregation) deferred — not needed yet.
- **`/setup-pm`** slash command references a Node script that doesn't exist here — N/A
  for this Python project; ignore unless a JS toolchain is added.

---

## Log

### 2026-07-19 (project-card collision resolution)
- **Project cards on the root canvas no longer overlap.** Two causes: the default
  grid in `defaultPos` assumes a 392px row while card height is content-driven, and
  free-drag allowed dropping a card on top of another. Added `resolveCollisions()`
  in `frontend/browse.js`: cards are measured (`offset*`), sorted pinned-first then
  top-to-bottom, and any card intersecting an already-placed one is pushed below it
  (+12px gap, cascading; y only grows so it terminates). The pinned card — the one
  the user just moved/resized — never moves, so others yield to it. Runs via a new
  `settle()` wrapper after initial render, expand/collapse, "+N more" paging, and
  drag/resize pointerup — deliberately NOT during pointermove, so nothing fights the
  cursor mid-drag. Pushed positions are persisted to the layout localStorage.
  Verified: `node --check` clean; Playwright e2e green (1 passed, 8.9s).

### 2026-07-04 (CI caught a Browse regression — fixed)
- First CI run on the new repo: ruff + 86 unit/integration tests green, but the
  **Playwright e2e failed** (timeout waiting for `.chip[data-name="train.py"]`).
  Root cause: `loadRoot` in `frontend/browse.js` requested `api.tree(path, 1)` —
  server semantics are depth=1 → root + children only — so project-card children
  (the file chips) were never in the payload, and cards rendered collapsed+empty
  until clicked. This contradicted the verified redesign behavior ("projects open
  by default since their children are in the depth-2 payload"); the depth had
  evidently been dropped to 1 after the last green e2e. Fix: `api.tree(path, 2)`
  + project cards (depth 1) start open when their children arrived. Reproduced
  the failure locally first (after `playwright install chromium` — local browser
  cache was stale), then verified: **e2e passes in 4.3s**; CI re-run green.
- **Repo is live: https://github.com/Vin124/lab-organizer** (public). The local
  `.git` was an empty dir, so `git init -b main` → single initial commit (61 files;
  `moves.log`, caches, and `.claude/.agents/.codex` gitignored) → `gh repo create
  --public --source . --push`. Topics added; **private vulnerability reporting
  enabled** (SECURITY.md links to it). Secret scan before push: clean (only the
  commented `sk-ant-...` placeholder in `.env.example`).
- **Open-source packaging added:** MIT `LICENSE`; `CONTRIBUTING.md` (setup, test/lint
  commands, the six safety invariants as non-negotiable ground rules, conventional
  commits); `SECURITY.md` (private reporting + in/out-of-scope tied to the threat
  model); `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1); `.github/` issue templates
  (bug/feature YAML forms + security contact link) and PR template (checklist mirrors
  CI + invariants). README: banner + CI/license/python/ruff badges on top,
  Contributing/License sections at the bottom.
- **Pixel-art banner (user request, styled after the Claude Code logo screenshot):**
  `docs/banner.svg` — "LAB ORGANIZER" in chunky block letters built from orange tiles
  (#e88a63) with grid strokes + dark offset echo on black; generated by a one-off
  script (5×5 pixel font upscaled 2×), rendered to PNG via headless Chrome to verify
  the look. The SVG is self-contained (own black bg → works in light/dark GitHub).
- **Imported the user's Claude Design project** (`/design/p/fa305182…`, "Notebook organizer
  UI design") via the DesignSync MCP and **implemented `Lab Organizer.dc.html`** as the real
  frontend. The design is a warm paper-notebook aesthetic: Caveat/Nunito/JetBrains-Mono fonts,
  dotted cream paper bg, depth-palette nested boxes (server → project cards in rose/sky/mint/
  butter/lavender → user → folder → file chips with type diamonds + tags), segmented Browse/
  Organize toggle, pill breadcrumb, Organize rail (empty state + Checks with Ask AI/Dismiss +
  Queued moves), dark terminal command modal, success toast, ghost/strikethrough for queued-away
  items, green drop highlight, and **free-drag/resize project cards** with a Reset-layout button
  (localStorage-persisted).
- **Wired entirely to the real backend** — the design's in-memory mock move was NOT adopted;
  the implementation uses the real `/api/tree`, `/api/dir-stats`, `/api/analyze-moves`,
  `/api/preview-moves`, `/api/execute-moves`, `/api/search`, `/api/undo*`, `/api/ask-ai`. Golden
  rules intact (client proposes {src,dst}; server builds/runs; never overwrites). Search, undo,
  and the AI advisor are preserved and restyled into the new look.
- **Files:** rewrote `index.html`, `styles.css`, `app.js`, `browse.js`, `organize.js`, `util.js`
  (added `typeMeta`); `search.js`/`api.js` unchanged. Palettes flow down via **inherited CSS
  custom props** (`--a-soft/-bg/-mid/-border/-ink`) set per project card. Depth→kind mapping:
  0 server, 1 project (free-positioned), 2 user, ≥3 folder; degrades for arbitrary real depth.
  Lazy expand + lazy dir-stats kept (projects open by default since their children are in the
  depth-2 payload; deeper levels load on click).
- **Bug caught + fixed live:** class rules with explicit `display:flex` (`.force-row`,
  `.queue-head`) overrode the `[hidden]` attribute, leaking the override row on a mere warning
  and "0 queued" into Browse mode. Fixed with a global `[hidden]{display:none!important}`.
- **Verified live in-browser** (real `labdemo3` tree): Browse renders the positioned palette
  cards with real sizes; Organize drag → real dependency warning → terminal preview → execute →
  file moved on disk → "Moved 1 item · logged" toast. Screenshots 07–09 in `docs/screenshots/`.
  Updated the Playwright E2E to assert the success **toast** (the redesign closes the modal +
  toasts instead of leaving `.ok` rows); **E2E green 3×** (stable), **86 Python passed**, ruff clean.

### 2026-06-24 (v3 usefulness & shipping)

- **Task 1 — Undo last batch (done, live-verified).** The append-only audit log is
  the only state. `execute_moves` now writes a `BATCH\t<uuid>` marker; `undo_last_batch`
  finds the most recent batch with no matching `UNDO\t<id>` marker and moves each OK'd
  file back in reverse order. Same golden rules: `confirmed:true` required, every path
  re-validated via `safe_resolve`, **never overwrites/merges** (occupied original →
  whole undo refused), fail-loud stop on first failure, own `UNDO`/`UNDO-OK`/`UNDO-FAIL`
  audit entries. Endpoints `GET /api/undo-info` + `POST /api/undo`; frontend "↩ Undo
  last move" button + confirm modal (organize panel; hidden in read-only). **Design
  call (made directly, not via council):** disambiguate the batch with explicit uuid
  `BATCH` markers + `UNDO` "already-undone" markers — a write-ahead-log pattern, the
  obvious correct approach; documented instead of spending a 5-advisor council.
  - **Security + code review (2 agents) → fixes applied:** (CRITICAL) audit-log
    injection via tab/newline in filenames — added reversible `_enc`/`_dec` escaping of
    path fields + `split("\t", 5)` cap so a crafted name can't forge a `BATCH` boundary
    or redirect undo; (HIGH) `UNDO` marker now written **only after full success** so a
    partial/crashed undo stays retryable, not falsely "undone"; (MEDIUM) `_MOVE_LOCK`
    serializes execute+undo against concurrent/double-undo; (MEDIUM) `undo-info` returns
    `read_only`; defense-in-depth path filter in `_reverse_moves`. Tests in
    `test_undo.py` (incl. injection-resistance, fallback-to-older-batch, all-FAIL batch)
    + HTTP round-trip in `test_integration.py`. Live: moved a file, Undo button showed
    "(1)", confirm reversed it on disk, audit showed `BATCH`→`OK`→`UNDO-OK`→`UNDO`.
- **Task 2 — Useful AI advisor (done).** Replaced the generic system prompt in `ai.py`
  with one that explains the tool's contract (server builds/runs moves, never
  overwrites) and turns a dependency/collision warning + move plan into concrete,
  least-disruptive advice; never implies it can execute. No-key degrade kept. New
  `test_ai.py` injects a **fake `anthropic` module** so the import→client→text path is
  covered without a key/network (also tests missing-package + API-error degrade).
- **Task 3 — Tree-wide search (done, live-verified).** `tree.search()` — case-insensitive
  substring on entry names, symlink-skipping, bounded by `max_results=200`/`max_depth=12`,
  returns `{hits, truncated}`. `GET /api/search?q=&path=` (start dir via `safe_resolve`).
  Frontend `search.js`: debounced box in the topbar, results dropdown, click a hit →
  switch to Browse, root at the hit (or its parent), highlight + scroll. Verified live:
  "train" found `train.py` + `old_train_checkpoint.pt` across the tree; jump+highlight worked.
  - **Security fix (S1, HIGH):** Windows junctions/reparse points aren't caught by
    `is_symlink()`; added `_escapes()` real-path containment check before descending in
    `search`. Residual: `scan_tree`/`_dir_stats` still rely on symlink-skipping for the
    same gap — left as-is (POSIX target where symlinks are already handled; the lazy
    `_dir_stats` full-subtree walk is the hot path and shouldn't pay a per-entry resolve).
    Documented here rather than refactoring v1 signatures.
- **Task 4 — Network-exposure hardening (done, live-verified).** Both **off by default**.
  `backend/ratelimit.py` (`RATE_LIMIT`=req/60s/IP, fixed-window, `_MAX_KEYS` sweep to
  bound memory) wired into the `gate` middleware **before** auth; client IP from the
  socket (not spoofable `X-Forwarded-For`). `backend/privacy.py` (`PATH_PRIVACY`):
  API returns paths relative to `LAB_ROOT`; `safe_resolve` already re-anchors relative
  paths inbound so the move/undo contract is unchanged. Applied at every boundary
  (config label, tree/expand, search hits, preview commands via `build_commands
  display_root=`, execute/undo result echoes). README threat-model section + `.env.example`
  updated. **Design call made directly** (relativize-at-boundary; narrow space, keep-it-minimal).
  - **Security fixes (P1/P2/P3, R1/R2):** `rel()`/`disp()` out-of-root fallback now
    returns the **basename**, never an absolute path (no layout leak); `_client_moves`
    scrubs the absolute root out of `error` strings; rate-limiter `_hits` bounded by a
    sweep; proxy/XFF caveat documented in code + README. `test_hardening.py` (10 tests).
  - Live (PATH_PRIVACY=1): `/api/config` lab_root → `labdemo3` (name only); tree root
    path `""`, children relative (`cftr`); lazy expand + search returned relative paths;
    frontend browsed fine with relative paths.
- **Task 5 — Ship it (done).** `Dockerfile` (python:3.11-slim, static frontend, non-root
  user, healthcheck, `LAB_ROOT=/data`) + `.dockerignore`; **note:** image build not run
  live (Docker daemon/Desktop not running here) — Dockerfile is conventional and the app
  runs identically under uvicorn (verified live). `.github/workflows/ci.yml`: `test` job
  (ruff + `pytest -m "not e2e"`) and `e2e` job (playwright). `tests/e2e/test_move_flow_e2e.py`:
  Playwright drives Browse→Organize→drag (dispatched HTML5 DnD)→dependency warning→
  preview→confirm→execute→verify moved + audit. `pytest.ini` registers the `e2e` marker
  and excludes it by default (`pytest -m e2e` to run). **E2E verified passing locally**
  (installed pytest-playwright + chromium). README: undo/search/Docker sections, API
  table rows, screenshots (05-undo, 06-search), Changelog with v3/v2/v1.

### 2026-06-24 (v2 hardening)
- **Code review pass (done).** Ran parallel code-reviewer + security-reviewer on the
  v2 diff. **Zero CRITICAL; auth gate + path safety confirmed structurally sound**
  (constant-time compare, /healthz-only exempt, every new endpoint goes through
  `safe_resolve`). Applied the worthwhile findings: (1) bounded `offset` with
  `le=10_000_000` so a huge offset can't force needless full scandir+sort;
  (2) `_stats_cache` → bounded **LRU** (`OrderedDict`, evict oldest) + public
  `clear_stats_cache()` — fixes the fill-then-stop "perf cliff"; (3) frontend
  defense-in-depth: escape `item_count`/`size` in meta, re-validate `ext` against
  `^[a-z0-9]+$` before class interpolation; (4) `check_basic_auth` now rejects an
  empty token outright; config warns when `AUTH_TOKEN=""`; (5) `scan_tree` no longer
  does an unguarded top-level `path.stat()` (only the file branch, guarded);
  (6) `fillStats` now runs through a 5-way concurrency limiter so a wide tree doesn't
  fan out one subtree-walk request per folder. Added tests (empty-token reject,
  absurd-offset 422). Re-verified live: `/api/dir-stats` works, path escape → 403,
  Browse renders with lazy stats. **46 passed, 1 skipped; ruff clean.**
- **Task 5 — round out tests (done).** deps.py edge cases: parametrized
  yaml/json/toml **quoted** path-literal detection + warning on split; a test
  documenting the deliberate gap that *unquoted* YAML scalars are not flagged;
  nested package imports (`import pkg.util` -> pkg/util.py, `from pkg import x` ->
  pkg/__init__.py, stdlib not flagged) + a no-warning-when-moved-together case.
  New `tests/test_integration.py`: full analyze→preview→execute over the HTTP API
  (warning surfaces, preview doesn't touch FS, execute no-op without `confirmed`,
  confirmed run moves file + writes audit log), plus READ_ONLY 403 and name-clash
  blocks-without-overwrite. Note: `AUDIT_LOG` binds at import, so the test patches
  `backend.moves.AUDIT_LOG`. Suite now **44 passed, 1 skipped; ruff clean**.
  (Caught + fixed a test-design bug: moving a config to a same-depth sibling does
  NOT break a `../`-relative ref — restructured so referenced data lives under the
  moved file's dir, the real split case.)
- **Task 4 — deploy for real (done).** Built a realistic lab tree (cftr/{vin,amir},
  shared/...) under `%TEMP%/labdemo` (not the demo), ran `uvicorn` against it, and
  drove the real browser end-to-end: Browse (nested zoom-in-place, lazy sizes filled
  in live) → switched to Organize → dragged `train.py` to `shared` → got the
  dependency warning (references `resnet50.py`, left behind) → previewed the exact
  shlex-quoted `mv` → confirmed → **file actually moved on disk** (verified: now in
  `shared/`, gone from `code/`) → **audit log line written**. 4 screenshots saved to
  `docs/screenshots/` and embedded in README. Added a **Deploy** section (quick
  uvicorn+SSH-tunnel and a systemd unit with `LAB_ROOT`/`READ_ONLY`/`AUTH_TOKEN`/
  `ANTHROPIC_API_KEY` env, `journalctl`, healthz check) and a Performance section.
- **Task 3 — large-tree performance (done).** Root cause: `scan_tree` called
  `_dir_stats` on *every* node, and `_dir_stats` walks the whole subtree — so even a
  shallow `depth=2` request did a full-depth walk of everything. Fix: `scan_tree`
  gained `with_stats` (default True for direct callers/tests); the HTTP endpoints now
  pass `with_stats=False` → structure only. New `GET /api/dir-stats?path=` +
  `tree.dir_stats()` serve recursive size/count on demand (mtime-cached). Frontend
  shows "…" then `fillStats()` fetches per visible dir node and fills the meta line.
  Added `scripts/bench_tree.py` (cold-cache lazy vs eager comparison on a real dir).
  **Measured on real ~/Documents (3,283 nodes, depth 3): lazy 0.49s vs eager 36.5s =
  75x faster** on the render path. Tradeoff (honest): the *root's* own dir-stats is
  still a full walk, but it now streams in after the tree is interactive instead of
  blocking it, and per-node caching means net server work ≈ one walk. Suite: 35 passed,
  1 skipped; ruff clean (backend+tests+scripts).
- **Task 2 — optional auth seam (done).** Added `AUTH_TOKEN` config (`auth_enabled`),
  new `backend/auth.py` (HTTP Basic check, constant-time `secrets.compare_digest`,
  `/healthz` exempt), and an `@app.middleware("http")` gate in `main.py`. **Off by
  default** (unset = no auth, localhost contract intact). Chose Basic auth over a
  bearer token specifically because it needs ZERO frontend changes — the browser
  prompts and caches creds natively (enter any username, token as password).
  Documented in README (env table + Authentication section with `openssl rand`
  example) and `.env.example`. New `tests/test_auth.py` (unit + endpoint: 401 w/o
  creds, WWW-Authenticate header, 200 with creds, healthz open, disabled-by-default).
  Suite: 35 passed, 1 skipped; ruff clean. **Design note:** goal suggested
  `/llm-council` for the auth model; the design space was tightly constrained by
  CLAUDE.md (no heavy auth, localhost default, leave a seam), so I made the call
  directly rather than spend a 5-advisor council against the keep-it-minimal directive.
- **Task 1 — click-to-load truncated dirs (done).** Added `offset` param to `scan_tree`
  (pages the sorted child list; returns `offset`/`next_offset`/`remaining` when more
  remain; offset applies only to the expanded node, recursion always starts at 0) and
  to `GET /api/tree/expand`. Frontend `appendChildren()` now renders a real
  "+N more — click to load" button that pages in the rest via `api.expand(path, offset)`
  and re-renders the button for the next page. Existing `.more` CSS already button-styled.
  Tests: added `test_offset_pages_remaining_children` + `test_expand_endpoint_accepts_offset`.
  Suite: 30 passed, 1 skipped; ruff clean. Updated Deferred list (truncation item resolved).

### 2026-06-24
- Built backend `config/safety/tree` + `test_safety.py`, `test_tree.py`. Verified tree
  scan (recursive sizes, depth cutoff, truncation) and 403 on path escape.
- Built frontend Browse mode (nested zoom, breadcrumb, lazy expand, file-type icons);
  verified zoom-in-place reflow and lazy load in-browser. Fixed `.organize-panel[hidden]`
  CSS bug (panel was showing in Browse). Silenced favicon 404.
- **Code review #1 (read-only slice):** fixed CRITICAL `safe_resolve` anchoring
  (relative paths were resolving against CWD, not LAB_ROOT); fixed HIGH stored-XSS via
  crafted file extension (sanitize `ext` to `[a-z0-9]` server-side + escape client-side);
  lowered `/api/tree` depth cap 12→6 (DoS).
- Built Organize mode (drag files + folders, client queue, pending ghost, warnings panel,
  preview/execute modals, AI panel). Built `deps.py`, `moves.py`, `ai.py` + endpoints,
  `test_deps.py`, `test_moves.py`. Verified full flow in-browser: queued a real file move
  *and* a whole-folder move, saw dependency warnings, previewed commands, confirmed,
  files moved on disk, audit log written. Verified READ_ONLY blocks writes (403) while
  reads work. Verified AI graceful degrade (no key).
- **Code review #2 (write/execute path):** fixed HIGH `force` overwrite bypass (now
  never overwrites/merges); existing-dir destination downgraded from warning → blocking
  error; `collision_warnings` now surfaces unsafe paths instead of silently skipping;
  `deps.py` now validates paths; `_audit` made fail-safe with absolute default path;
  capped `ask-ai` field lengths (8000/1000). Verified: clash blocks without force AND
  with force (original file preserved, source intact); overlong AI input → 422.
- Wrote README.md, .env.example, requirements.txt, .gitignore. Tests: 28 passed, ruff clean.
- Added PROGRESS.md (this file) and the session-start read instruction in CLAUDE.md.
