"""Real-directory benchmark for the tree scanner.

Compares the HTTP endpoints' lazy scan (structure only) against the eager scan
(recursive sizes for every node), plus a single on-demand dir-stats call, against
a *real* directory tree. The point: lazy scan must not block on sizing the world.

Usage:
    python scripts/bench_tree.py [PATH] [--depth N] [--repeat K]

PATH defaults to $LAB_ROOT, else the current directory.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import tree  # noqa: E402


def _time(fn, repeat: int) -> float:
    best = float("inf")
    for _ in range(repeat):
        tree.clear_stats_cache()  # cold cache each run for a fair comparison
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def _count_nodes(node: dict) -> int:
    return 1 + sum(_count_nodes(c) for c in node.get("children", []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=None)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--max-children", type=int, default=500)
    args = ap.parse_args()

    import os

    root = Path(args.path or os.environ.get("LAB_ROOT") or ".").expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")

    def lazy() -> dict:
        return tree.scan_tree(root, args.depth, args.max_children, with_stats=False)

    def eager() -> dict:
        return tree.scan_tree(root, args.depth, args.max_children, with_stats=True)

    sample = lazy()
    nodes = _count_nodes(sample)

    t_lazy = _time(lazy, args.repeat)
    t_eager = _time(eager, args.repeat)
    # one on-demand stats call (the per-node cost the UI pays lazily, cold)
    tree.clear_stats_cache()
    t0 = time.perf_counter()
    tree.dir_stats(root)
    t_stats = time.perf_counter() - t0

    speedup = t_eager / t_lazy if t_lazy else float("inf")
    print(f"root         : {root}")
    print(f"depth        : {args.depth}   nodes emitted: {nodes}   (best of {args.repeat})")
    print(f"lazy  scan   : {t_lazy * 1000:8.1f} ms   (endpoint default — structure only)")
    print(f"eager scan   : {t_eager * 1000:8.1f} ms   (full recursive sizes for every node)")
    print(f"speedup      : {speedup:8.1f}x faster, no full subtree walk on the request")
    print(f"dir-stats(1) : {t_stats * 1000:8.1f} ms   (one lazy size call for the root subtree)")


if __name__ == "__main__":
    main()
