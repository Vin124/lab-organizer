"""Dependency detection. Pure + testable: input = move plan + root, output =
warnings. Reads file contents (no writes, no network).

A dependency is a *warning* when a moved file references another file that, after
the moves are applied, would no longer sit where the reference expects it — i.e.
the reference would break. Heuristic and conservative: only flags references that
resolve to a file that actually exists on disk, so stdlib imports (`import numpy`)
don't produce noise.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from backend.safety import UnsafePathError, safe_resolve

# --- reference extraction ----------------------------------------------------

_PY_IMPORT = re.compile(r"^\s*(?:from\s+(\.*)([\w.]*)\s+import\b|import\s+([\w.]+))", re.M)
# quoted strings that look like a relative file path (has a dot-extension or a slash)
_PATH_LITERAL = re.compile(r"""['"]([^'"\n]*?(?:/[^'"\n]*|\.[A-Za-z0-9]{1,5}))['"]""")
_SHELL_SOURCE = re.compile(r"^\s*(?:source|\.)\s+(\S+)", re.M)

_CODE_EXT = {"py", "sh", "bash", "yaml", "yml", "json", "toml", "cfg", "ini", "r"}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _resolve_existing(file_dir: Path, ref: str) -> Path | None:
    """Resolve a relative reference against file_dir; return it if it exists."""
    ref = ref.strip().strip("'\"")
    if not ref or ref.startswith(("/", "http://", "https://", "~")) or ":" in ref[:3]:
        return None
    cand = Path(os.path.normpath(file_dir / ref))
    return cand if cand.exists() else None


def _python_import_candidates(file_dir: Path, dots: str, name: str) -> list[Path]:
    base = file_dir
    for _ in range(max(0, len(dots) - 1)):
        base = base.parent
    parts = name.split(".") if name else []
    if not parts and not dots:
        return []
    stem = base.joinpath(*parts) if parts else base
    return [stem.with_suffix(".py"), stem / "__init__.py"]


def extract_references(path: Path) -> set[Path]:
    """Return existing sibling/relative files that `path` references."""
    ext = path.suffix.lstrip(".").lower()
    if ext not in _CODE_EXT or not path.is_file():
        return set()

    text = _read(path)
    file_dir = path.parent
    refs: set[Path] = set()

    if ext == "py":
        for dots, frm, imp in _PY_IMPORT.findall(text):
            for cand in _python_import_candidates(file_dir, dots, frm or imp):
                if cand.exists():
                    refs.add(Path(os.path.normpath(cand)))

    if ext in {"sh", "bash"}:
        for ref in _SHELL_SOURCE.findall(text):
            hit = _resolve_existing(file_dir, ref)
            if hit:
                refs.add(hit)

    # relative path literals work for every text format (py/sh/yaml/json/toml…)
    for ref in _PATH_LITERAL.findall(text):
        hit = _resolve_existing(file_dir, ref)
        if hit and hit != path:
            refs.add(hit)

    return refs


# --- applying the move plan --------------------------------------------------

def _norm(p: str | Path) -> str:
    return os.path.normpath(str(p))


def _post_move_path(abs_path: str, plan: list[dict]) -> str:
    """Where `abs_path` ends up after the plan is applied."""
    ap = _norm(abs_path)
    for m in plan:
        src = _norm(m["src"])
        dst_final = _norm(os.path.join(m["dst"], os.path.basename(src)))
        if ap == src:
            return dst_final
        prefix = src + os.sep
        if ap.startswith(prefix):
            return _norm(os.path.join(dst_final, ap[len(prefix):]))
    return ap


# --- public API --------------------------------------------------------------

def dependency_warnings(moves: list[dict], root: Path) -> list[dict]:
    warnings: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for m in moves:
        if m.get("type") != "file":
            continue
        try:  # defense-in-depth: never touch the FS with an unvalidated path
            src = safe_resolve(m["src"], root)
            safe_resolve(m["dst"], root)
        except UnsafePathError:
            continue
        if not src.is_file():
            continue
        dst_dir = _post_move_path(str(src), moves)
        dst_dir = os.path.dirname(dst_dir)  # directory the file lands in

        for ref in extract_references(src):
            rel = os.path.relpath(str(ref), str(src.parent))
            expected = _norm(os.path.join(dst_dir, rel))
            actual = _post_move_path(str(ref), moves)
            if expected != actual:
                key = (src.name, ref.name)
                if key in seen:
                    continue
                seen.add(key)
                warnings.append({
                    "file": src.name,
                    "kind": "dependency",
                    "severity": "warning",
                    "message": (
                        f"{src.name} references {ref.name} which is not moving with it "
                        f"- the reference may break."
                    ),
                })
    return warnings
