# goal.md — Lab Server File Organizer

## What we're building

A self-hosted web tool that lets a research lab **see** and **reorganize** files scattered across many users' home directories on a shared server. Two modes:

1. **Browse (read-only)** — a nested, zoomable rectangle view of the server's directory tree. Rectangles inside rectangles: server → projects → user folders → subfolders → files. You click into any box to expand it *in place* and see what's inside, without zooming the whole screen.
2. **Organize (edit)** — drag files **and entire folders** to new locations. Nothing actually moves until you hit "Preview commands" and confirm. The tool generates the exact shell (`mv`) commands, shows them for review, then executes them on the server. Bad moves (broken dependencies) raise warnings the user can dismiss or ask an AI about.

The core problem this solves: in a lab, every person dumps files in their own `/home/<user>/` directory, and when you need to combine work it's painful to find where everything is. This gives one visual map of the whole server plus a safe way to reorganize.

---

## Who runs it

- Deployed on the lab server itself (or a machine that can read the target filesystem).
- Accessed via browser by lab members on the same network, or over an SSH tunnel.
- Read access to the directories it shows; write access only for the move operations, gated behind confirmation.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Browser (frontend)                              │
│  - Nested rectangle explorer (zoom in place)     │
│  - Drag-and-drop organizer (files + folders)     │
│  - Dependency warnings + "Ask AI" panel          │
│  - Command preview modal                          │
└───────────────────────┬─────────────────────────┘
                        │ HTTP / JSON
┌───────────────────────┴─────────────────────────┐
│  Backend (FastAPI, Python)                        │
│  - GET  /api/tree?path=...   directory scan       │
│  - POST /api/analyze-moves   dependency check     │
│  - POST /api/preview-moves   build mv commands    │
│  - POST /api/execute-moves   run after confirm    │
│  - POST /api/ask-ai          forward to Claude API│
└───────────────────────┬─────────────────────────┘
                        │ filesystem + subprocess
                  ┌─────┴──────┐
                  │  Server FS  │
                  └─────────────┘
```

Tech choices (keep it boring and robust):
- Backend: **Python 3.11+, FastAPI, uvicorn**.
- Frontend: **plain HTML/CSS/JS** (no build step) OR **React + Vite** if Claude Code prefers — but a zero-build single-page app is preferred for ease of deployment on a server.
- AI: **Anthropic API** (`anthropic` Python SDK), key from env var `ANTHROPIC_API_KEY`. AI is optional — the tool must fully work without it.

---

## Backend API spec

### `GET /api/tree`
Query params: `path` (absolute path under an allowlisted root), `depth` (default 3, how many levels to pre-load).

Returns the directory tree as nested JSON. Lazy-loadable: the frontend may request deeper levels on demand for big folders.

```json
{
  "name": "home",
  "path": "/home",
  "type": "dir",
  "size": 5284900000,
  "item_count": 1240,
  "children": [
    {
      "name": "cftr",
      "path": "/home/cftr",
      "type": "dir",
      "size": 2100000000,
      "item_count": 320,
      "children": [
        {
          "name": "vin",
          "path": "/home/cftr/vin",
          "type": "dir",
          "children": [
            { "name": "code", "path": "/home/cftr/vin/code", "type": "dir",
              "children": [
                { "name": "train.py", "path": "/home/cftr/vin/code/train.py", "type": "file", "size": 4200, "ext": "py" }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

Requirements:
- Use `os.scandir` / `pathlib` for speed. Cache aggressively; a full deep scan of a big server is slow, so support a `depth` cutoff and a `GET /api/tree/expand?path=...` for on-demand single-level expansion.
- Never follow symlinks outside the allowlisted root (security).
- Report `size` (bytes) and `item_count` per directory so the UI can show context.
- Include a `truncated: true` flag if a directory has more children than a configured cap (e.g. >500), so the UI can say "+N more".

### `POST /api/analyze-moves`
Body: a list of proposed moves.
```json
{ "moves": [
  { "src": "/home/cftr/vin/code/train.py", "dst": "/home/cftr/shared", "type": "file" },
  { "src": "/home/cftr/vin/results",       "dst": "/home/shared/results", "type": "dir" }
]}
```
Returns warnings:
```json
{ "warnings": [
  { "file": "train.py", "kind": "dependency",
    "message": "train.py references resnet50.py which is not being moved with it",
    "severity": "warning" },
  { "file": "results", "kind": "collision",
    "message": "/home/shared/results already exists; contents would merge",
    "severity": "warning" },
  { "file": "output.csv", "kind": "name_clash",
    "message": "A file named output.csv already exists at the destination",
    "severity": "error" }
]}
```

**Dependency detection** (this is the novel, valuable part — do it well):
- For Python files: scan for `import X`, `from X import`, and relative path string literals (`open("../data/foo.csv")`, `pd.read_csv("foo.csv")`).
- For shell scripts: scan for `source ./x.sh`, `. ./x.sh`, and referenced paths.
- For config files (yaml/json/toml): scan string values that look like relative paths to sibling files.
- A dependency is a *warning* when: file A is moved but a file B it references is (a) staying put, or (b) going to a different destination than A.
- Collisions / name clashes at the destination are *errors* (block until resolved or user overrides).
- Keep this heuristic and conservative — false positives the user can dismiss are fine; silent breakage is not.

### `POST /api/preview-moves`
Same body as analyze. Returns the literal shell commands that *would* run, in order, without executing:
```json
{ "commands": [
  "mkdir -p /home/cftr/shared",
  "mv /home/cftr/vin/code/train.py /home/cftr/shared/train.py",
  "mv /home/cftr/vin/results /home/shared/results"
]}
```
- Create destination dirs with `mkdir -p` when they don't exist.
- Moving a folder moves it whole (recursive by nature of `mv`).
- Quote/escape all paths properly (paths may contain spaces).

### `POST /api/execute-moves`
Body: the confirmed move list **plus** a `confirmed: true` flag and an optional `force: true` to override non-fatal warnings.
- Re-validate everything server-side (never trust the client). Re-run collision checks immediately before moving — the filesystem may have changed.
- Execute moves transactionally where possible: if a move fails midway, stop and return what succeeded + what failed; do **not** half-destroy state silently.
- Prefer `shutil.move` over shelling out, OR shell out with fully escaped args — pick one, be consistent, log every operation.
- Return a per-move result list with success/failure and any error message.
- Write an **audit log** (append-only file, e.g. `moves.log`) recording who/what/when for every executed move. This matters in a shared lab.

### `POST /api/ask-ai`
Body: `{ "context": "...warnings or move plan...", "question": "..." }`
- Forwards to the Anthropic API with a system prompt explaining it's helping reorganize lab files safely.
- Returns the model's text answer.
- If `ANTHROPIC_API_KEY` is unset, return a clear "AI not configured" response; the UI degrades gracefully.

---

## Frontend spec

### Browse mode (read-only)
- Render the tree as **nested rounded rectangles**. Outer = server root. Inside it, project folders. Inside those, user folders. Inside those, subfolders. Inside those, files as small chips.
- **Zoom in place**: clicking a folder box expands *that box* to reveal its children inline — the rest of the layout stays put (it reflows around it). It does NOT navigate to a new full-screen page. This is the key behavior from the user's sketch.
- A breadcrumb bar at top reflects the deepest open path and lets you collapse back up.
- File chips are color-coded by type (py / sh / csv / txt / yaml / etc.) via a small icon, not loud background colors.
- Show folder size and item count subtly so users get context on where the bulk lives.
- Large directories: show first N children + "+M more" that loads on click.

### Organize mode (edit)
- Toggle between Browse and Organize (tab or switch at top).
- **Drag files AND whole folders.** A folder is draggable as a single unit; dropping it moves the entire subtree. Visually distinguish a folder-drag (e.g. show "folder + N items" on the drag ghost).
- Drop targets are any folder box. Highlight valid drop targets on drag-over.
- Queued moves are shown but not executed. A move can be undone/removed before commit.
- Moved items show a pending badge in their new location and a ghost/struck-through marker in the old one.
- **Warnings panel**: as moves are queued, call `/api/analyze-moves`. Show a count pill; expand to a list. Each warning has Dismiss and "Ask AI" actions. Errors (collisions) are visually distinct from warnings and block commit unless force-overridden.
- **Commit flow**: "Preview commands" → modal shows the exact `mv`/`mkdir` commands → user confirms → `/api/execute-moves` → show per-move success/failure results.

### Design direction (hand this section to Claude Design if refining visuals)
- Clean, flat, minimal. Thin borders, generous whitespace, rounded corners. No heavy shadows or gradients.
- The nesting itself is the main visual metaphor — boxes within boxes, like the user's hand sketch. Keep borders light so deep nesting doesn't get noisy.
- Neutral palette for structure; reserve color for: file-type icons, valid drop-target highlight (green), and warnings (amber) / errors (red).
- Light and dark mode both supported.
- Interaction should feel like a spatial map you explore, not a list you scroll. Smooth expand/collapse, no jarring full-page transitions.

---

## Security & safety (non-negotiable)
- **Path allowlist**: a configured root (e.g. `/home`). Reject any request whose resolved real path escapes it. Resolve symlinks and `..` before checking.
- Never execute arbitrary client-supplied commands — the client proposes *moves* (src/dst pairs), and the server builds the commands itself.
- Re-validate every move server-side at execute time.
- Confirmation required before any write. Optional dry-run mode for the whole app.
- Audit log of all executed moves.
- Auth: at minimum, bind to localhost + SSH tunnel by default; document how to add real auth (e.g. a shared password or reverse-proxy auth) before exposing on a network.
- Configurable read-only deployment mode that disables all write endpoints entirely.

---

## Config
Environment variables / config file:
- `LAB_ROOT` — allowlisted root path (default `/home`).
- `ANTHROPIC_API_KEY` — optional, enables AI.
- `READ_ONLY` — if true, disable all move/execute endpoints.
- `MAX_CHILDREN` — per-dir cap before truncation (default 500).
- `BIND_HOST` / `BIND_PORT` — default `127.0.0.1:8000`.

---

## Deliverables (what Claude Code should produce)
1. `backend/` — FastAPI app implementing all endpoints above, with the dependency-detection module as its own well-tested file.
2. `frontend/` — the single-page explorer + organizer (zero-build preferred).
3. `tests/` — unit tests for path-safety, dependency detection, and command generation (these three are where bugs are dangerous).
4. `README.md` — install, configure, run, and security notes.
5. A `--dry-run` / `READ_ONLY` mode demonstrated to work.

## Build order (suggested)
1. Backend `/api/tree` + path safety + tests. Verify against a real directory.
2. Frontend Browse mode (nested zoom). Get the read-only explorer feeling right first.
3. Organize mode: drag files, then drag folders. Queue moves client-side.
4. `/api/analyze-moves` + dependency detection + warnings UI.
5. `/api/preview-moves` + command modal.
6. `/api/execute-moves` + audit log + server-side revalidation.
7. `/api/ask-ai` + AI panel (last, optional).

## Definition of done
- I can point it at a directory, see the whole tree as nested boxes, zoom into any folder in place, drag a file or a whole folder to a new home, see a dependency warning when I split a file from something it needs, preview the exact commands, confirm, and have the files actually move — with a log of what happened and nothing ever moving without my confirmation.
