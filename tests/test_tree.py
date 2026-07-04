"""Tree scan + endpoint tests."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_config  # noqa: E402
from backend.tree import scan_tree  # noqa: E402


@pytest.fixture
def lab(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "lab"
    (root / "cftr" / "vin" / "code").mkdir(parents=True)
    (root / "cftr" / "vin" / "code" / "train.py").write_text("import numpy")
    (root / "cftr" / "vin" / "notes.txt").write_text("hello")
    (root / "shared").mkdir()
    monkeypatch.setenv("LAB_ROOT", str(root))
    get_config.cache_clear()
    yield root.resolve()
    get_config.cache_clear()


def test_scan_recursive_size_and_count(lab: Path):
    node = scan_tree(lab, depth=5, max_children=500, with_stats=True)
    assert node["type"] == "dir"
    assert node["item_count"] == 6  # cftr, vin, code, train.py, notes.txt, shared
    assert node["size"] == len("import numpy") + len("hello")


def test_depth_cutoff_marks_unloaded(lab: Path):
    node = scan_tree(lab, depth=1, max_children=500)
    cftr = next(c for c in node["children"] if c["name"] == "cftr")
    assert cftr.get("children_loaded") is False
    assert "children" not in cftr
    # but stats still computed
    assert cftr["item_count"] == 4


def test_truncation_flag(tmp_path: Path):
    big = tmp_path / "big"
    big.mkdir()
    for i in range(10):
        (big / f"f{i}.txt").write_text("x")
    node = scan_tree(big, depth=1, max_children=3)
    assert node["truncated"] is True
    assert len(node["children"]) == 3


def test_offset_pages_remaining_children(tmp_path: Path):
    big = tmp_path / "big"
    big.mkdir()
    for i in range(10):
        (big / f"f{i:02d}.txt").write_text("x")

    page1 = scan_tree(big, depth=1, max_children=3, offset=0)
    assert [c["name"] for c in page1["children"]] == ["f00.txt", "f01.txt", "f02.txt"]
    assert page1["truncated"] is True
    assert page1["next_offset"] == 3
    assert page1["remaining"] == 7

    page2 = scan_tree(big, depth=1, max_children=3, offset=page1["next_offset"])
    assert [c["name"] for c in page2["children"]] == ["f03.txt", "f04.txt", "f05.txt"]
    assert page2["next_offset"] == 6
    assert page2["remaining"] == 4

    # final page: no truncation, no next_offset
    last = scan_tree(big, depth=1, max_children=3, offset=9)
    assert [c["name"] for c in last["children"]] == ["f09.txt"]
    assert "truncated" not in last
    assert "next_offset" not in last


def test_expand_endpoint_accepts_offset(lab: Path):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/tree/expand", params={"path": str(lab / "cftr" / "vin"), "offset": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["offset"] == 1
    # vin has [code, notes.txt]; offset 1 skips "code"
    assert [c["name"] for c in body["children"]] == ["notes.txt"]


def test_expand_endpoint_rejects_absurd_offset(lab: Path):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/tree/expand", params={"path": str(lab / "cftr"), "offset": 999_999_999})
    assert r.status_code == 422  # bounded by le= to prevent needless full scans


def test_endpoint_rejects_escape(lab: Path):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/tree", params={"path": str(lab / ".." / ".." / "etc")})
    assert r.status_code == 403


def test_endpoint_dirs_sorted_before_files(lab: Path):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    vin = client.get("/api/tree", params={"path": str(lab / "cftr" / "vin"), "depth": 1}).json()
    names = [c["name"] for c in vin["children"]]
    assert names == ["code", "notes.txt"]  # dir first, then file
