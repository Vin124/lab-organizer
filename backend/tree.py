"""Directory scanning -> nested JSON for the explorer.

Emits children down to `depth`; directories past the cutoff are returned with
`children_loaded: false` so the frontend can lazily expand them. Sizes and item
counts are recursive totals (cached per path+mtime so repeat calls are cheap).
"""
from __future__ import annotations

import os
import re
from collections import OrderedDict
from pathlib import Path

_EXT_SAFE = re.compile(r"[^a-z0-9]")


def _ext_of(name: str) -> str:
    """Lowercased extension, sanitized to [a-z0-9] (prevents XSS via filenames)."""
    if "." not in name:
        return ""
    return _EXT_SAFE.sub("", name.rsplit(".", 1)[-1].lower())

# (size_bytes, item_count) cached by (path, mtime_ns). Bounded LRU, mtime-invalidated.
_MAX_STATS_CACHE = 50_000
_stats_cache: "OrderedDict[tuple[str, int], tuple[int, int]]" = OrderedDict()


def clear_stats_cache() -> None:
    """Drop the memoized directory stats (used by benchmarks/tests)."""
    _stats_cache.clear()


def _dir_stats(path: Path) -> tuple[int, int]:
    """Recursive (total_size_bytes, total_item_count) for a directory."""
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return (0, 0)
    cached = _stats_cache.get(key)
    if cached is not None:
        _stats_cache.move_to_end(key)  # LRU: mark recently used
        return cached

    size = 0
    count = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                count += 1
                try:
                    if entry.is_symlink():
                        continue  # don't traverse symlinks; avoid loops/escapes
                    if entry.is_dir(follow_symlinks=False):
                        s, c = _dir_stats(Path(entry.path))
                        size += s
                        count += c
                    else:
                        size += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        return (0, 0)

    _stats_cache[key] = (size, count)
    _stats_cache.move_to_end(key)
    if len(_stats_cache) > _MAX_STATS_CACHE:
        _stats_cache.popitem(last=False)  # evict least-recently-used
    return (size, count)


def dir_stats(path: Path) -> dict:
    """On-demand recursive size/count for one directory (mtime-cached)."""
    size, item_count = _dir_stats(path)
    return {"size": size, "item_count": item_count}


SEARCH_MAX_RESULTS = 200
SEARCH_MAX_DEPTH = 12


def search(
    root: Path,
    query: str,
    max_results: int = SEARCH_MAX_RESULTS,
    max_depth: int = SEARCH_MAX_DEPTH,
) -> dict:
    """Case-insensitive substring match on entry names under `root`.

    Path-safe by construction: it only ever descends into `root`'s real children
    and never follows symlinks (avoids loops and escapes outside the allowlisted
    tree). Bounded by `max_results` and `max_depth` so a huge tree can't hang the
    server. Returns {"hits": [...], "truncated": bool}.
    """
    q = query.lower()
    boundary = root.resolve()
    hits: list[dict] = []
    truncated = False

    def walk(path: Path, depth: int) -> None:
        nonlocal truncated
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            if len(hits) >= max_results:
                truncated = True
                return
            try:
                if entry.is_symlink():
                    continue  # don't traverse symlinks; avoid loops/escapes
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if q in entry.name.lower():
                hits.append({
                    "name": entry.name,
                    "path": entry.path,
                    "type": "dir" if is_dir else "file",
                })
            if is_dir and not _escapes(entry.path, boundary):
                # `is_symlink()` misses Windows junctions/reparse points; the real-path
                # containment check below catches any dir entry that escapes the root.
                walk(Path(entry.path), depth + 1)
                if len(hits) >= max_results:
                    return

    walk(root, 0)
    return {"hits": hits, "truncated": truncated}


def _escapes(path: str, boundary: Path) -> bool:
    """True if `path`'s real location is outside `boundary` (e.g. a junction)."""
    try:
        Path(path).resolve().relative_to(boundary)
        return False
    except (ValueError, OSError):
        return True


def _file_node(entry: os.DirEntry) -> dict:
    name = entry.name
    ext = _ext_of(name)
    try:
        size = entry.stat(follow_symlinks=False).st_size
    except OSError:
        size = 0
    return {"name": name, "path": entry.path, "type": "file", "size": size, "ext": ext}


def scan_tree(
    path: Path,
    depth: int,
    max_children: int,
    offset: int = 0,
    with_stats: bool = True,
) -> dict:
    """Scan `path` to `depth` levels. depth=0 -> dir node without children loaded.

    `offset` pages into the sorted child list: the node returns up to
    `max_children` children starting at `offset`, plus `next_offset`/`remaining`
    when more remain so the UI can click-to-load the rest. Offset applies only to
    this node; recursive child scans always start at 0.

    `with_stats=False` omits recursive `size`/`item_count` (which require a full
    subtree walk). The HTTP endpoints use this so a deep/wide scan never blocks on
    sizing the whole tree; the UI fills sizes in lazily via `/api/dir-stats`.
    """
    if not path.is_dir():
        # a file requested directly (is_dir() returns False for broken symlinks
        # without raising; guard the stat against a TOCTOU race / dead link)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        return {"name": path.name, "path": str(path), "type": "file",
                "size": size, "ext": _ext_of(path.name)}

    node: dict = {
        "name": path.name or str(path),
        "path": str(path),
        "type": "dir",
    }
    if with_stats:
        size, item_count = _dir_stats(path)
        node["size"] = size
        node["item_count"] = item_count

    if depth <= 0:
        node["children_loaded"] = False
        return node

    children: list[dict] = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
    except OSError:
        node["children_loaded"] = False
        return node

    consumed = 0
    for entry in entries[offset:]:
        if len(children) >= max_children:
            break
        consumed += 1
        try:
            if entry.is_symlink():
                continue  # don't traverse symlinks; avoid loops/escapes
            if entry.is_dir(follow_symlinks=False):
                children.append(
                    scan_tree(Path(entry.path), depth - 1, max_children, with_stats=with_stats)
                )
            else:
                children.append(_file_node(entry))
        except OSError:
            continue

    node["children"] = children
    node["children_loaded"] = True
    node["offset"] = offset
    next_offset = offset + consumed
    if next_offset < len(entries):
        node["truncated"] = True
        node["next_offset"] = next_offset
        node["remaining"] = len(entries) - next_offset
    return node
