"""Optional path-privacy: present paths to the client relative to LAB_ROOT so
absolute server paths aren't leaked over the network. Off by default.

Inbound needs no change: `safety.safe_resolve` already anchors relative client
paths under LAB_ROOT, so a client that received "cftr/code/x.py" can send it
straight back and it resolves correctly.
"""
from __future__ import annotations

from pathlib import Path


def rel(path: str | Path, root: Path) -> str:
    """`path` relative to `root` as a POSIX string; "" for the root itself.

    If `path` isn't under `root` (shouldn't happen for server-emitted paths), fall
    back to the BASENAME — never the absolute path, so privacy mode can't leak the
    server's layout even on an unexpected input.
    """
    p = Path(path)
    try:
        s = p.relative_to(root).as_posix()
    except ValueError:
        return p.name
    return "" if s == "." else s


def relativize_tree(node: dict, root: Path) -> dict:
    """Copy of a scan_tree node with every 'path' field relativized (immutably)."""
    out = dict(node)
    if "path" in out:
        out["path"] = rel(out["path"], root)
    if "children" in out:
        out["children"] = [relativize_tree(c, root) for c in out["children"]]
    return out
