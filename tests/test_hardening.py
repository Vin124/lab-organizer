"""Network-exposure hardening: rate limiting + path privacy. Both off by default."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_config  # noqa: E402
from backend.privacy import rel, relativize_tree  # noqa: E402
from backend.ratelimit import RateLimiter  # noqa: E402


# ---- unit: rate limiter ----

def test_rate_limiter_allows_under_limit_then_blocks():
    rl = RateLimiter(limit=3, window=60)
    assert [rl.allow("ip", now=t) for t in (0, 1, 2)] == [True, True, True]
    assert rl.allow("ip", now=3) is False          # 4th in window blocked


def test_rate_limiter_resets_after_window():
    rl = RateLimiter(limit=1, window=60)
    assert rl.allow("ip", now=0) is True
    assert rl.allow("ip", now=30) is False         # still in window
    assert rl.allow("ip", now=61) is True          # window passed


def test_rate_limiter_is_per_key():
    rl = RateLimiter(limit=1, window=60)
    assert rl.allow("a", now=0) is True
    assert rl.allow("b", now=0) is True            # different client unaffected


# ---- unit: path privacy ----

def test_rel_relativizes_and_handles_root(tmp_path):
    root = tmp_path / "lab"
    (root / "a").mkdir(parents=True)
    assert rel(root / "a" / "x.py", root) == "a/x.py"
    assert rel(root, root) == ""                   # the root itself
    # outside the root -> basename only, never the absolute path (no layout leak)
    assert rel("/somewhere/else.py", root) == "else.py"


def test_relativize_tree_rewrites_nested_paths(tmp_path):
    root = tmp_path / "lab"
    node = {
        "path": str(root), "name": "lab", "type": "dir",
        "children": [
            {"path": str(root / "a"), "name": "a", "type": "dir",
             "children": [{"path": str(root / "a" / "f.py"), "name": "f.py", "type": "file"}]},
        ],
    }
    out = relativize_tree(node, root)
    assert out["path"] == ""
    assert out["children"][0]["path"] == "a"
    assert out["children"][0]["children"][0]["path"] == "a/f.py"
    assert node["path"] == str(root)               # original untouched (immutable)


# ---- HTTP ----

@pytest.fixture
def make_client(tmp_path, monkeypatch):
    def _make(**env):
        root = tmp_path / "lab"
        (root / "code").mkdir(parents=True, exist_ok=True)
        (root / "code" / "train.py").write_text("x")
        (root / "shared").mkdir(exist_ok=True)
        monkeypatch.setenv("LAB_ROOT", str(root))
        monkeypatch.delenv("AUTH_TOKEN", raising=False)
        monkeypatch.delenv("READ_ONLY", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr("backend.main._limiter", None, raising=False)
        monkeypatch.setattr("backend.moves.AUDIT_LOG", tmp_path / "moves.log")
        get_config.cache_clear()
        from fastapi.testclient import TestClient

        from backend.main import app
        return TestClient(app), root
    yield _make
    get_config.cache_clear()


def test_defaults_leak_absolute_paths_and_no_limit(make_client):
    client, root = make_client()  # no privacy, no rate limit
    tree = client.get("/api/tree").json()
    assert tree["path"] == str(root)               # absolute by default
    for _ in range(20):
        assert client.get("/healthz").status_code == 200


def test_rate_limit_returns_429(make_client):
    client, _ = make_client(RATE_LIMIT="3")
    codes = [client.get("/api/config").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert 429 in codes
    # /healthz is exempt even when over the limit
    assert client.get("/healthz").status_code == 200


def test_path_privacy_hides_absolute_paths(make_client):
    client, _ = make_client(PATH_PRIVACY="1")
    cfg = client.get("/api/config").json()
    assert cfg["lab_root"] == "lab"                # name only, not the server path
    assert cfg["path_privacy"] is True

    tree = client.get("/api/tree").json()
    assert tree["path"] == ""                      # root relativized
    code = [c for c in tree["children"] if c["name"] == "code"][0]
    assert code["path"] == "code"

    hits = client.get("/api/search", params={"q": "train"}).json()["hits"]
    assert hits and all(not Path(h["path"]).is_absolute() for h in hits)


def test_path_privacy_move_and_undo_round_trip(make_client):
    client, root = make_client(PATH_PRIVACY="1")
    # client echoes the relative paths it received
    moves = [{"src": "code/train.py", "dst": "shared", "type": "file"}]
    r = client.post("/api/execute-moves", json={"moves": moves, "confirmed": True}).json()
    assert all(x["ok"] for x in r["results"])
    assert not Path(r["results"][0]["src"]).is_absolute()   # echoed relative
    assert (root / "shared" / "train.py").exists()          # really moved

    info = client.get("/api/undo-info").json()
    assert info["available"] and not Path(info["moves"][0]["src"]).is_absolute()

    u = client.post("/api/undo", json={"confirmed": True}).json()
    assert u["undone"] is True
    assert (root / "code" / "train.py").exists()            # restored
    assert not Path(u["results"][0]["src"]).is_absolute()   # relative echo


def test_path_privacy_scrubs_root_from_error_messages(make_client):
    client, root = make_client(PATH_PRIVACY="1")
    (root / "shared" / "train.py").write_text("occupied")   # force a FileExistsError
    moves = [{"src": "code/train.py", "dst": "shared", "type": "file"}]
    r = client.post("/api/execute-moves",
                    json={"moves": moves, "confirmed": True, "force": True}).json()
    err = r["results"][-1]["error"] or ""
    assert "exists" in err                       # the real failure still surfaces
    assert str(root) not in err                  # but the absolute root is scrubbed


def test_path_privacy_preview_uses_relative_paths(make_client):
    client, _ = make_client(PATH_PRIVACY="1")
    moves = [{"src": "code/train.py", "dst": "shared", "type": "file"}]
    cmds = client.post("/api/preview-moves", json={"moves": moves}).json()["commands"]
    joined = "\n".join(cmds)
    assert "code/train.py" in joined
    assert "shared/train.py" in joined
    assert ":\\" not in joined and "/lab/" not in joined    # no absolute server path
