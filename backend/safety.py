"""Path allowlist / escape prevention. Every client path goes through here first.

Rule: resolve symlinks and `..` to a real path, then require it to live under
LAB_ROOT. Reject anything that escapes — including symlinks pointing outside.
"""
from __future__ import annotations

from pathlib import Path


class UnsafePathError(ValueError):
    """Raised when a path escapes the allowlisted root."""


def _is_within(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def safe_resolve(client_path: str, root: Path) -> Path:
    """Resolve `client_path` to a real absolute path under `root`, or raise.

    Works for paths that don't exist yet (e.g. move destinations): the existing
    ancestors are resolved (following symlinks), so a symlinked parent that
    escapes the root is still caught.
    """
    if not client_path or not str(client_path).strip():
        raise UnsafePathError("empty path")

    root = root.resolve()
    # Anchor relative paths under root (never the server's CWD); absolute paths
    # are resolved as-is and then checked for containment.
    p = Path(client_path)
    if not p.is_absolute():
        p = root / client_path
    resolved = p.resolve()  # strict=False: resolves symlinks in what exists

    if resolved != root and not _is_within(root, resolved):
        raise UnsafePathError(f"path escapes allowlisted root: {client_path}")
    return resolved
