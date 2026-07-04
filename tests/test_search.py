"""Tree-search tests: correctness + the bounds/path-safety that keep it cheap."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_config  # noqa: E402
from backend.tree import search  # noqa: E402


@pytest.fixture
def lab(tmp_path: Path) -> Path:
    root = tmp_path / "lab"
    (root / "code").mkdir(parents=True)
    (root / "code" / "train.py").write_text("x")
    (root / "code" / "Train_BACKUP.py").write_text("x")  # case variation
    (root / "data").mkdir()
    (root / "data" / "nested" / "more").mkdir(parents=True)
    (root / "data" / "nested" / "more" / "buried.txt").write_text("x")
    return root.resolve()


def test_search_is_case_insensitive(lab: Path):
    names = [h["name"] for h in search(lab, "train")["hits"]]
    assert "train.py" in names and "Train_BACKUP.py" in names


def test_search_finds_deeply_nested(lab: Path):
    hits = search(lab, "buried")["hits"]
    assert any(h["name"] == "buried.txt" and h["type"] == "file" for h in hits)


def test_search_matches_directories(lab: Path):
    hits = search(lab, "nested")["hits"]
    assert any(h["name"] == "nested" and h["type"] == "dir" for h in hits)


def test_search_result_bound_and_truncation(lab: Path):
    for i in range(10):
        (lab / "code" / f"match{i}.log").write_text("x")
    res = search(lab, "match", max_results=4)
    assert len(res["hits"]) == 4
    assert res["truncated"] is True


def test_search_depth_bound(lab: Path):
    # buried.txt lives 3 levels deep; a depth-1 search must not reach it
    assert search(lab, "buried", max_depth=1)["hits"] == []


def test_search_no_matches(lab: Path):
    res = search(lab, "zzzznotfound")
    assert res["hits"] == [] and res["truncated"] is False


def test_escapes_helper(tmp_path: Path):
    from backend.tree import _escapes
    root = tmp_path / "lab"
    (root / "inside").mkdir(parents=True)
    assert _escapes(str(root / "inside"), root.resolve()) is False
    assert _escapes(str(tmp_path / "outside"), root.resolve()) is True


def test_search_does_not_follow_dir_link_escaping_root(tmp_path: Path):
    # a link inside the root that points OUTSIDE it must not be traversed
    root = tmp_path / "lab"
    (root / "sub").mkdir(parents=True)
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "passwords.txt").write_text("x")
    try:
        (root / "link").symlink_to(secret, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform/privilege")
    # symlink is skipped outright; the _escapes guard is the backstop for junctions
    assert search(root.resolve(), "passwords")["hits"] == []


# ---- HTTP layer ----

@pytest.fixture
def client(lab: Path, monkeypatch):
    monkeypatch.setenv("LAB_ROOT", str(lab))
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    get_config.cache_clear()
    from fastapi.testclient import TestClient

    from backend.main import app
    yield TestClient(app)
    get_config.cache_clear()


def test_search_endpoint_returns_hits(client):
    r = client.get("/api/search", params={"q": "train"}).json()
    assert r["query"] == "train"
    assert any(h["name"] == "train.py" for h in r["hits"])


def test_search_endpoint_rejects_path_escape(client):
    r = client.get("/api/search", params={"q": "x", "path": "../../etc"})
    assert r.status_code == 403


def test_search_endpoint_requires_query(client):
    assert client.get("/api/search").status_code == 422       # q missing
    assert client.get("/api/search", params={"q": ""}).status_code == 422  # too short
