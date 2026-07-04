"""Move plan -> collision warnings, shell-command preview, and safe execution.

Hard rules: the server builds commands itself (never the client); execution
requires confirmed=True and re-validates every move against the live filesystem;
every executed move is appended to an audit log.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.safety import UnsafePathError, safe_resolve

# Default audit log lives next to the project, not the (unpredictable) CWD.
_DEFAULT_LOG = Path(__file__).resolve().parent.parent / "moves.log"
AUDIT_LOG = Path(os.environ.get("MOVES_LOG") or _DEFAULT_LOG)

# Serialize all FS-mutating + audit-writing work so two concurrent execute/undo
# requests (e.g. under a multi-worker server) can't interleave or double-undo.
_MOVE_LOCK = threading.Lock()


def _enc(s: str) -> str:
    """Reversibly escape audit field separators so a filename containing a tab
    or newline can't forge fields/records (audit-log injection). Reversible so
    `undo` recovers the exact real path via `_dec`."""
    return (s.replace("\\", "\\\\").replace("\t", "\\t")
             .replace("\n", "\\n").replace("\r", "\\r"))


def _dec(s: str) -> str:
    """Inverse of `_enc`."""
    out: list[str] = []
    i = 0
    table = {"\\": "\\", "t": "\t", "n": "\n", "r": "\r"}
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(table.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _dst_final(src: Path, dst_dir: Path) -> Path:
    return dst_dir / src.name


# --- collision / name-clash detection ---------------------------------------

def collision_warnings(moves: list[dict], root: Path) -> list[dict]:
    warnings: list[dict] = []
    landing: dict[str, str] = {}  # final dst path -> source name (detect queue conflicts)

    for m in moves:
        try:
            src = safe_resolve(m["src"], root)
            dst_dir = safe_resolve(m["dst"], root)
        except UnsafePathError as e:
            # Surface, never silently drop — an unsafe path must be visible.
            warnings.append({
                "file": m.get("src"), "kind": "unsafe_path", "severity": "error",
                "message": str(e),
            })
            continue
        final = _dst_final(src, dst_dir)
        fkey = str(final)

        if fkey in landing:
            warnings.append({
                "file": src.name, "kind": "name_clash", "severity": "error",
                "message": f"Two queued moves both target {final.name} in {dst_dir}.",
            })
        landing[fkey] = src.name

        if final.exists():
            # The tool never overwrites or merges (golden rule: no silent
            # destruction). Any existing destination blocks — rename or relocate.
            kind = "folder" if final.is_dir() else "file"
            warnings.append({
                "file": src.name, "kind": "name_clash", "severity": "error",
                "message": f"A {kind} named {final.name} already exists at the "
                           f"destination; the tool will not overwrite or merge it.",
            })
    return warnings


# --- command preview ---------------------------------------------------------

def build_commands(
    moves: list[dict], root: Path, display_root: Path | None = None
) -> list[str]:
    """Literal mv/mkdir commands that *would* run, fully quoted. Never executed.

    `display_root` (set in path-privacy mode) renders the shown paths relative to
    it so absolute server paths aren't leaked; the commands are illustrative only.
    """
    def disp(p: Path) -> str:
        if display_root is None:
            return str(p)
        try:
            return Path(p).relative_to(display_root).as_posix() or "."
        except ValueError:
            return Path(p).name  # never leak an absolute path in privacy mode

    cmds: list[str] = []
    made_dirs: set[str] = set()
    for m in moves:
        src = safe_resolve(m["src"], root)
        dst_dir = safe_resolve(m["dst"], root)
        if str(dst_dir) not in made_dirs and not dst_dir.exists():
            cmds.append(f"mkdir -p {shlex.quote(disp(dst_dir))}")
            made_dirs.add(str(dst_dir))
        final = _dst_final(src, dst_dir)
        cmds.append(f"mv {shlex.quote(disp(src))} {shlex.quote(disp(final))}")
    return cmds


# --- execution ---------------------------------------------------------------

def _audit(line: str) -> None:
    """Append to the audit log. Fail-safe: a log error must never abort a move
    that already happened — report to stderr and continue."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{ts}\t{line}\n")
    except OSError as exc:
        print(f"AUDIT WRITE FAILED: {exc} — {line}", file=sys.stderr)


def execute_moves(
    moves: list[dict], root: Path, confirmed: bool, force: bool = False
) -> list[dict]:
    """Re-validate and execute. No-op unless confirmed. Stops on first failure.

    `force` only skips the all-or-nothing pre-flight gate so a plan whose clashes
    the user has resolved on disk can be retried; it NEVER permits overwriting or
    merging an existing destination — that always fails loud, per-move.

    Returns a per-move result list: {src, dst, ok, error}.
    """
    if not confirmed:
        return [{"src": m.get("src"), "dst": m.get("dst"), "ok": False,
                 "error": "not confirmed"} for m in moves]

    # All-or-nothing pre-flight against the live FS: don't start a batch we know
    # will fail partway. `force` skips only this gate (clashes re-checked below).
    if not force:
        errs = [w for w in collision_warnings(moves, root) if w["severity"] == "error"]
        if errs:
            return [{"src": None, "dst": None, "ok": False,
                     "error": f"blocked by {len(errs)} error(s); resolve them first"}]

    results: list[dict] = []
    with _MOVE_LOCK:
        # Tag this run so `undo_last_batch` can later reverse exactly these moves.
        _audit(f"BATCH\t{uuid.uuid4().hex}")
        for m in moves:
            entry = {"src": m.get("src"), "dst": m.get("dst"), "ok": False, "error": None}
            try:
                src = safe_resolve(m["src"], root)
                dst_dir = safe_resolve(m["dst"], root)
                if not src.exists():
                    raise FileNotFoundError(f"source no longer exists: {src}")
                final = _dst_final(src, dst_dir)
                if final.exists():  # never overwrite or merge — fail loud
                    raise FileExistsError(f"destination already exists: {final}")
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(final))
                _audit(f"OK\t{_enc(str(src))}\t->\t{_enc(str(final))}")
                entry["ok"] = True
            except Exception as e:  # noqa: BLE001 — report, don't crash the batch
                entry["error"] = str(e)
                _audit(f"FAIL\t{_enc(str(m.get('src')))}\t->\t"
                       f"{_enc(str(m.get('dst')))}\t{_enc(str(e))}")
                results.append(entry)
                # fail loud: stop, don't half-finish silently
                break
            results.append(entry)
    return results


# --- undo: reverse the most recent executed batch ----------------------------
#
# The audit log is the only state. A forward batch is delimited by a
# `BATCH\t<id>` marker followed by `OK`/`FAIL` lines. Undo finds the most recent
# batch not already reversed (no matching `UNDO\t<id>` marker), then moves each
# OK'd file back to its original location — in reverse order, never overwriting.
# Undo writes its own `UNDO`/`UNDO-OK`/`UNDO-FAIL` audit entries.


def _read_audit_lines() -> list[str]:
    try:
        with AUDIT_LOG.open("r", encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f]
    except OSError:
        return []


def _parse_batches(lines: list[str]) -> tuple[list[dict], set[str]]:
    """Parse the audit log into forward batches + the set of already-undone ids.

    Each batch is {"id": str, "moves": [(src, dst), ...]} where the OK line said
    the file moved src -> dst. Lines before the first BATCH marker (legacy/v2
    format) are not attributable to a batch and are intentionally not undoable.
    """
    batches: list[dict] = []
    undone: set[str] = set()
    current: dict | None = None
    for ln in lines:
        # Capped split: path fields are _enc-escaped (no raw tabs), so a real
        # path can never shift these indices or smuggle extra fields.
        parts = ln.split("\t", 5)
        if len(parts) < 2:
            continue
        op = parts[1]
        if op == "BATCH" and len(parts) >= 3:
            current = {"id": parts[2], "moves": []}
            batches.append(current)
        elif op == "OK" and current is not None and len(parts) >= 5:
            # ts, OK, src, ->, dst — decode back to the real on-disk paths
            current["moves"].append((_dec(parts[2]), _dec(parts[4])))
        elif op == "UNDO" and len(parts) >= 3:
            undone.add(parts[2])
    return batches, undone


def _last_undoable_batch() -> dict | None:
    batches, undone = _parse_batches(_read_audit_lines())
    for b in reversed(batches):
        if b["id"] not in undone and b["moves"]:
            return b
    return None


def _reverse_moves(batch: dict, root: Path) -> list[tuple[str, str]]:
    """Reverse pairs (current_location, original_location) for a batch, in the
    order undo will apply them. Drops any pair whose paths don't resolve safely
    under `root` — defense-in-depth, even though `_enc` already makes log
    injection impossible."""
    out: list[tuple[str, str]] = []
    for src, dst in reversed(batch["moves"]):
        try:
            safe_resolve(dst, root)
            safe_resolve(src, root)
        except UnsafePathError:
            continue
        out.append((dst, src))  # move current(=dst) back to original(=src)
    return out


def undo_info(root: Path) -> dict:
    """Describe the batch a confirmed undo would reverse (for the UI). Read-only."""
    batch = _last_undoable_batch()
    if batch is None:
        return {"available": False, "batch_id": None, "count": 0, "moves": []}
    reverses = [{"src": cur, "dst": orig} for cur, orig in _reverse_moves(batch, root)]
    return {
        "available": bool(reverses),
        "batch_id": batch["id"],
        "count": len(reverses),
        "moves": reverses,
    }


def _preflight_undo(reverses: list[tuple[str, str]], root: Path) -> list[str]:
    """Per-move safety check before touching anything. (cur, orig) pairs.

    Refuses (returns errors) if a file to restore is gone, an original location
    is occupied (never overwrite/merge), a path is unsafe, or two restores would
    target the same place. All-or-nothing: any error blocks the whole undo.
    """
    errs: list[str] = []
    seen: set[str] = set()
    for cur, orig in reverses:
        try:
            cur_p = safe_resolve(cur, root)
            orig_p = safe_resolve(orig, root)
        except UnsafePathError as e:
            errs.append(str(e))
            continue
        if not cur_p.exists():
            errs.append(f"file to restore no longer exists: {cur_p}")
        if orig_p.exists():
            errs.append(f"original location is occupied, won't overwrite: {orig_p}")
        if str(orig_p) in seen:
            errs.append(f"two restores target {orig_p}")
        seen.add(str(orig_p))
    return errs


def undo_last_batch(root: Path, confirmed: bool) -> dict:
    """Reverse the most recent executed batch. No-op unless confirmed.

    Obeys the same golden rules as execute: confirmation required, every path
    re-validated against the live FS, and it NEVER overwrites or merges — if an
    original location is now occupied the whole undo is refused (fail loud).
    """
    with _MOVE_LOCK:
        batch = _last_undoable_batch()
        if batch is None:
            return {"undone": False, "batch_id": None, "results": [],
                    "error": "nothing to undo"}

        reverses = _reverse_moves(batch, root)  # (current, original) pairs

        if not confirmed:
            return {"undone": False, "batch_id": batch["id"],
                    "results": [{"src": cur, "dst": orig, "ok": False,
                                 "error": "not confirmed"} for cur, orig in reverses]}

        errs = _preflight_undo(reverses, root)
        if errs:
            extra = f" (+{len(errs) - 1} more)" if len(errs) > 1 else ""
            return {"undone": False, "batch_id": batch["id"],
                    "results": [{"src": None, "dst": None, "ok": False,
                                 "error": f"blocked: {errs[0]}{extra}"}]}

        undo_id = uuid.uuid4().hex
        results: list[dict] = []
        all_ok = True
        for cur, orig in reverses:
            entry = {"src": cur, "dst": orig, "ok": False, "error": None}
            try:
                cur_p = safe_resolve(cur, root)
                orig_p = safe_resolve(orig, root)
                if not cur_p.exists():
                    raise FileNotFoundError(f"file to restore no longer exists: {cur_p}")
                if orig_p.exists():  # never overwrite/merge — fail loud
                    raise FileExistsError(f"original location is occupied: {orig_p}")
                orig_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cur_p), str(orig_p))
                _audit(f"UNDO-OK\t{_enc(str(cur_p))}\t->\t{_enc(str(orig_p))}")
                entry["ok"] = True
            except Exception as e:  # noqa: BLE001 — report, don't crash the batch
                entry["error"] = str(e)
                _audit(f"UNDO-FAIL\t{_enc(str(cur))}\t->\t{_enc(str(orig))}\t{_enc(str(e))}")
                results.append(entry)
                all_ok = False
                break  # fail loud: stop, don't half-finish silently
            results.append(entry)

        # Mark the batch undone ONLY on full success, so a crash or partial
        # failure mid-loop leaves it retryable instead of falsely "undone".
        if all_ok:
            _audit(f"UNDO\t{batch['id']}\t{undo_id}")
        return {"undone": all_ok, "batch_id": batch["id"], "results": results}
