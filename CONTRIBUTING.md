# Contributing

Thanks for your interest in improving Lab Organizer! Bug reports, fixes, tests,
and docs are all welcome.

## Getting started

```bash
git clone https://github.com/Vin124/lab-organizer.git
cd lab-organizer
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                # point LAB_ROOT at a scratch dir
uvicorn backend.main:app --port 8000                # open http://127.0.0.1:8000
```

Use a **throwaway directory** as `LAB_ROOT` while developing — this tool moves
real files.

## Before you open a PR

```bash
ruff check backend/ tests/ scripts/    # lint — must be clean
python -m pytest tests/ -q             # unit + integration
```

The optional Playwright end-to-end test:

```bash
pip install pytest-playwright && playwright install chromium
pytest -m e2e -q
```

CI runs all of the above on every push and PR.

## Ground rules (non-negotiable)

These are the safety invariants of the project. PRs that weaken them will not
be merged:

1. **Nothing moves or is deleted without explicit confirmation.** The execute
   endpoint requires `confirmed: true`.
2. **The client only proposes `{src, dst}` pairs.** The server builds and runs
   commands — never the client.
3. **Every client-supplied path goes through `backend/safety.py`** (symlink +
   `..` resolution, `LAB_ROOT` allowlist) before any filesystem access.
4. **Never overwrite or merge.** An occupied destination is an error, not a
   warning.
5. **Fail loud.** A batch stops on the first failure and reports exactly what
   happened; every executed move goes to the append-only audit log.
6. **The tool must fully work without an AI key.** AI is advisory only.

If your change touches moves, execution, or path handling, add or extend tests
in `tests/test_safety.py`, `tests/test_moves.py`, or `tests/test_undo.py`.

## Conventions

- Python 3.11+, type hints everywhere, `ruff` clean.
- Prefer `pathlib.Path`; if shelling out, `shlex.quote` every component.
- Frontend is vanilla JS ES modules, zero build step — keep it that way.
- Keep `backend/deps.py` pure (no filesystem writes, no network).
- Commit messages follow conventional commits: `feat:`, `fix:`, `docs:`,
  `test:`, `refactor:`, `chore:`, `perf:`, `ci:`.

## Reporting bugs / requesting features

Use the [issue templates](https://github.com/Vin124/lab-organizer/issues/new/choose).
For security vulnerabilities, **do not open a public issue** — see
[SECURITY.md](SECURITY.md).
