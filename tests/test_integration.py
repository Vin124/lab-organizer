"""End-to-end pipeline over the HTTP API: analyze -> preview -> execute.

Exercises the real golden-rule contract: warnings surface, preview never touches
the FS, execute is a no-op without confirmation, and a confirmed run moves the file
on disk and writes the audit log.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_config  # noqa: E402


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    root = tmp_path / "lab"
    (root / "code").mkdir(parents=True)
    (root / "code" / "train.py").write_text("from resnet50 import build\n")
    (root / "code" / "resnet50.py").write_text("def build():\n    pass\n")
    (root / "shared").mkdir()
    log = tmp_path / "moves.log"

    monkeypatch.setenv("LAB_ROOT", str(root))
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.delenv("READ_ONLY", raising=False)
    get_config.cache_clear()
    # AUDIT_LOG is bound at import time, so patch the attribute directly.
    monkeypatch.setattr("backend.moves.AUDIT_LOG", log)

    from fastapi.testclient import TestClient

    from backend.main import app

    yield TestClient(app), root, log
    get_config.cache_clear()


def test_analyze_preview_execute_pipeline(env):
    client, root, log = env
    moves = [{"src": str(root / "code" / "train.py"), "dst": str(root / "shared"), "type": "file"}]

    # 1. analyze -> dependency warning about the left-behind import
    warnings = client.post("/api/analyze-moves", json={"moves": moves}).json()["warnings"]
    assert any(w["kind"] == "dependency" and "resnet50.py" in w["message"] for w in warnings)

    # 2. preview -> exact mv command; nothing moved yet
    commands = client.post("/api/preview-moves", json={"moves": moves}).json()["commands"]
    assert any(c.startswith("mv ") and "train.py" in c for c in commands)
    assert (root / "code" / "train.py").exists()
    assert not (root / "shared" / "train.py").exists()

    # 3. execute WITHOUT confirmation -> no-op
    r = client.post("/api/execute-moves", json={"moves": moves, "confirmed": False}).json()
    assert all(res["ok"] is False for res in r["results"])
    assert (root / "code" / "train.py").exists()
    assert not (root / "shared" / "train.py").exists()

    # 4. execute WITH confirmation -> the file actually moves
    r = client.post("/api/execute-moves", json={"moves": moves, "confirmed": True}).json()
    assert all(res["ok"] for res in r["results"])
    assert not (root / "code" / "train.py").exists()
    assert (root / "shared" / "train.py").exists()

    # 5. audit log records the executed move
    assert log.exists()
    assert "OK" in log.read_text() and "train.py" in log.read_text()


def test_execute_blocked_in_read_only(env, monkeypatch):
    client, root, _ = env
    monkeypatch.setenv("READ_ONLY", "true")
    get_config.cache_clear()
    moves = [{"src": str(root / "code" / "train.py"), "dst": str(root / "shared"), "type": "file"}]
    r = client.post("/api/execute-moves", json={"moves": moves, "confirmed": True})
    assert r.status_code == 403
    assert (root / "code" / "train.py").exists()  # untouched


def test_name_clash_blocks_execute(env):
    client, root, _ = env
    # pre-create the destination file so the move would clash
    (root / "shared" / "train.py").write_text("OLD CONTENT — must not be overwritten\n")
    moves = [{"src": str(root / "code" / "train.py"), "dst": str(root / "shared"), "type": "file"}]

    warnings = client.post("/api/analyze-moves", json={"moves": moves}).json()["warnings"]
    assert any(w["severity"] == "error" and w["kind"] == "name_clash" for w in warnings)

    r = client.post("/api/execute-moves", json={"moves": moves, "confirmed": True}).json()
    assert all(res["ok"] is False for res in r["results"])
    # original preserved, source intact — never overwrites/merges
    assert (root / "shared" / "train.py").read_text().startswith("OLD CONTENT")
    assert (root / "code" / "train.py").exists()


def test_undo_round_trip_over_http(env):
    client, root, log = env
    moves = [{"src": str(root / "code" / "train.py"), "dst": str(root / "shared"), "type": "file"}]

    # nothing to undo yet
    assert client.get("/api/undo-info").json()["available"] is False

    # execute -> file moves, batch becomes undoable
    client.post("/api/execute-moves", json={"moves": moves, "confirmed": True})
    assert (root / "shared" / "train.py").exists()
    info = client.get("/api/undo-info").json()
    assert info["available"] is True and info["count"] == 1

    # undo without confirmation -> no-op
    r = client.post("/api/undo", json={"confirmed": False}).json()
    assert r["undone"] is False
    assert (root / "shared" / "train.py").exists()

    # undo confirmed -> file returns home, audit records it
    r = client.post("/api/undo", json={"confirmed": True}).json()
    assert r["undone"] is True
    assert (root / "code" / "train.py").exists()
    assert not (root / "shared" / "train.py").exists()
    assert "UNDO-OK" in log.read_text()


def test_undo_blocked_in_read_only(env, monkeypatch):
    client, root, _ = env
    monkeypatch.setenv("READ_ONLY", "true")
    get_config.cache_clear()
    r = client.post("/api/undo", json={"confirmed": True})
    assert r.status_code == 403
