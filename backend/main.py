"""FastAPI app + routes for the Lab Server File Organizer.

Golden rules enforced here: the client only ever proposes moves; the server
builds and runs commands, re-validates at execute time, and writes an audit log.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.auth import check_basic_auth, is_exempt
from backend.config import get_config
from backend.deps import dependency_warnings
from backend.moves import (
    build_commands,
    collision_warnings,
    execute_moves,
    undo_info,
    undo_last_batch,
)
from backend.privacy import rel, relativize_tree
from backend.ratelimit import RateLimiter
from backend.safety import UnsafePathError, safe_resolve
from backend.tree import dir_stats, scan_tree, search

app = FastAPI(title="Lab Server File Organizer")

# Lazily-built rate limiter, rebuilt if RATE_LIMIT changes (e.g. across tests).
_limiter: RateLimiter | None = None


def _get_limiter(limit: int) -> RateLimiter | None:
    global _limiter
    if limit <= 0:
        return None
    if _limiter is None or _limiter.limit != limit:
        _limiter = RateLimiter(limit)
    return _limiter


@app.middleware("http")
async def gate(request: Request, call_next):
    """Per-request guards: optional rate limit (all clients), then optional auth.

    Rate limiting runs first so it also throttles failed auth attempts. Both are
    off by default; /healthz is always exempt so liveness probes never trip them.
    """
    cfg = get_config()
    exempt = is_exempt(request.url.path)
    if not exempt:
        limiter = _get_limiter(cfg.rate_limit)
        if limiter is not None:
            # Client IP from the TCP socket — NOT X-Forwarded-For, which a client can
            # forge. Correct for the direct localhost/SSH-tunnel posture. Behind a
            # reverse proxy every request shares the proxy's IP, so move throttling to
            # the proxy (set RATE_LIMIT=0 here). See the README threat model.
            client = request.client.host if request.client else "unknown"
            if not limiter.allow(client):
                return Response(
                    status_code=429,
                    content="rate limit exceeded",
                    headers={"Retry-After": "60"},
                )
        if cfg.auth_enabled and not check_basic_auth(
            request.headers.get("Authorization"), cfg.auth_token
        ):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Lab File Organizer"'},
            )
    return await call_next(request)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _resolve(path: str) -> Path:
    cfg = get_config()
    try:
        return safe_resolve(path, cfg.lab_root)
    except UnsafePathError as e:
        raise HTTPException(status_code=403, detail=str(e))


def _client_path(path) -> str:
    """A path as the client should see it: relative to lab_root in privacy mode."""
    cfg = get_config()
    return rel(path, cfg.lab_root) if cfg.path_privacy else str(path)


def _client_tree(node: dict) -> dict:
    cfg = get_config()
    return relativize_tree(node, cfg.lab_root) if cfg.path_privacy else node


def _client_moves(results: list[dict]) -> list[dict]:
    """Relativize src/dst echoed back in move/undo results when privacy is on, and
    scrub the absolute root out of any error message (which may embed a full path)."""
    cfg = get_config()
    if not cfg.path_privacy:
        return results
    root_str = str(cfg.lab_root)
    out = []
    for r in results:
        nr = dict(r)
        if nr.get("src") is not None:
            nr["src"] = _client_path(nr["src"])
        if nr.get("dst") is not None:
            nr["dst"] = _client_path(nr["dst"])
        if nr.get("error") and root_str in str(nr["error"]):
            nr["error"] = str(nr["error"]).replace(root_str, "<root>")
        out.append(nr)
    return out


# ---- API: read-only ----

@app.get("/api/config")
def api_config() -> dict:
    cfg = get_config()
    # In privacy mode expose only the root's name as a label, not its server path.
    lab_root = cfg.lab_root.name if cfg.path_privacy else str(cfg.lab_root)
    return {
        "lab_root": lab_root,
        "read_only": cfg.read_only,
        "ai_enabled": cfg.ai_enabled,
        "max_children": cfg.max_children,
        "path_privacy": cfg.path_privacy,
    }


@app.get("/api/tree")
def api_tree(
    path: str | None = Query(default=None),
    depth: int = Query(default=3, ge=0, le=6),
) -> dict:
    cfg = get_config()
    target = _resolve(path) if path else cfg.lab_root
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    # Lazy stats: structure now, sizes via /api/dir-stats — keeps deep scans non-blocking.
    return _client_tree(
        scan_tree(target, depth=depth, max_children=cfg.max_children, with_stats=False)
    )


@app.get("/api/tree/expand")
def api_tree_expand(
    path: str = Query(...),
    offset: int = Query(default=0, ge=0, le=10_000_000),
) -> dict:
    """Load a single level of children on demand, paged from `offset`."""
    cfg = get_config()
    target = _resolve(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="path not found")
    return _client_tree(
        scan_tree(target, depth=1, max_children=cfg.max_children, offset=offset, with_stats=False)
    )


@app.get("/api/dir-stats")
def api_dir_stats(path: str = Query(...)) -> dict:
    """Recursive size + item_count for one directory, loaded lazily by the UI."""
    target = _resolve(path)
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    return dir_stats(target)


@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1, max_length=200),
    path: str | None = Query(default=None),
) -> dict:
    """Case-insensitive name search under LAB_ROOT (or `path`, if within root).

    Path-safe and bounded: the start dir goes through `safe_resolve`, the walk
    never follows symlinks, and results/depth are capped in `tree.search`.
    """
    cfg = get_config()
    target = _resolve(path) if path else cfg.lab_root
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    result = search(target, q)
    if cfg.path_privacy:
        result = {**result,
                  "hits": [{**h, "path": _client_path(h["path"])} for h in result["hits"]]}
    return {"query": q, **result}


# ---- API: move planning + execution ----

class Move(BaseModel):
    src: str
    dst: str
    type: str = "file"  # "file" | "dir"


class MovePlan(BaseModel):
    moves: list[Move]


class ExecutePlan(MovePlan):
    confirmed: bool = False
    force: bool = False


class AiQuery(BaseModel):
    context: str = Field(default="", max_length=8000)
    question: str = Field(..., max_length=1000)


class UndoRequest(BaseModel):
    confirmed: bool = False


def _validate_plan(moves: list[Move]) -> list[dict]:
    """Reject any move touching a path outside the allowlist; return as dicts."""
    cfg = get_config()
    out: list[dict] = []
    for m in moves:
        try:
            safe_resolve(m.src, cfg.lab_root)
            safe_resolve(m.dst, cfg.lab_root)
        except UnsafePathError as e:
            raise HTTPException(status_code=403, detail=str(e))
        out.append(m.model_dump())
    return out


def _require_writable() -> None:
    if get_config().read_only:
        raise HTTPException(status_code=403, detail="server is in read-only mode")


@app.post("/api/analyze-moves")
def api_analyze(plan: MovePlan) -> dict:
    cfg = get_config()
    moves = _validate_plan(plan.moves)
    warnings = dependency_warnings(moves, cfg.lab_root) + collision_warnings(moves, cfg.lab_root)
    return {"warnings": warnings}


@app.post("/api/preview-moves")
def api_preview(plan: MovePlan) -> dict:
    cfg = get_config()
    moves = _validate_plan(plan.moves)
    display_root = cfg.lab_root if cfg.path_privacy else None
    return {"commands": build_commands(moves, cfg.lab_root, display_root=display_root)}


@app.post("/api/execute-moves")
def api_execute(plan: ExecutePlan) -> dict:
    _require_writable()
    cfg = get_config()
    moves = _validate_plan(plan.moves)
    results = execute_moves(moves, cfg.lab_root, confirmed=plan.confirmed, force=plan.force)
    return {"results": _client_moves(results)}


@app.get("/api/undo-info")
def api_undo_info() -> dict:
    """What a confirmed undo would reverse — the most recent executed batch."""
    cfg = get_config()
    info = undo_info(cfg.lab_root)
    info["read_only"] = cfg.read_only  # let the UI suppress the button up front
    if cfg.path_privacy:
        info["moves"] = [{"src": _client_path(m["src"]), "dst": _client_path(m["dst"])}
                         for m in info["moves"]]
    return info


@app.post("/api/undo")
def api_undo(req: UndoRequest) -> dict:
    _require_writable()
    out = undo_last_batch(get_config().lab_root, confirmed=req.confirmed)
    out["results"] = _client_moves(out["results"])
    return out


@app.post("/api/ask-ai")
def api_ask_ai(query: AiQuery) -> dict:
    from backend.ai import ask_ai

    return {"answer": ask_ai(query.context, query.question)}


# ---- frontend ----

if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))


class _Health(BaseModel):
    status: str = "ok"


@app.get("/healthz")
def healthz() -> _Health:
    return _Health()
