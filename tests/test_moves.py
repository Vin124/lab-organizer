"""Command-generation, collision, and execution-safety tests.

These guard the dangerous paths: quoting, collision detection, and the rule that
nothing executes without confirmed=True.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backend.moves as moves_mod  # noqa: E402
from backend.moves import build_commands, collision_warnings, execute_moves  # noqa: E402


@pytest.fixture
def lab(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "lab"
    (root / "a").mkdir(parents=True)
    (root / "a" / "file one.txt").write_text("hi")  # space in name
    (root / "a" / "keep.py").write_text("x")
    (root / "b").mkdir()
    # audit log inside tmp
    monkeypatch.setattr(moves_mod, "AUDIT_LOG", tmp_path / "moves.log")
    return root.resolve()


def test_commands_quote_paths_with_spaces(lab: Path):
    moves = [{"src": str(lab / "a" / "file one.txt"), "dst": str(lab / "b"), "type": "file"}]
    cmds = build_commands(moves, lab)
    mv = [c for c in cmds if c.startswith("mv ")][0]
    assert "'" in mv and "file one.txt" in mv  # quoted


def test_commands_mkdir_for_missing_dest(lab: Path):
    moves = [{"src": str(lab / "a" / "keep.py"), "dst": str(lab / "new"), "type": "file"}]
    cmds = build_commands(moves, lab)
    assert any(c.startswith("mkdir -p") for c in cmds)


def test_collision_name_clash_is_error(lab: Path):
    (lab / "b" / "keep.py").write_text("existing")
    moves = [{"src": str(lab / "a" / "keep.py"), "dst": str(lab / "b"), "type": "file"}]
    warns = collision_warnings(moves, lab)
    assert any(w["kind"] == "name_clash" and w["severity"] == "error" for w in warns)


def test_collision_existing_dir_is_blocking_error(lab: Path):
    # never merge: an existing destination folder is a blocking error, not a warning
    (lab / "b" / "a").mkdir()  # destination already has an 'a' dir
    moves = [{"src": str(lab / "a"), "dst": str(lab / "b"), "type": "dir"}]
    warns = collision_warnings(moves, lab)
    assert any(w["severity"] == "error" for w in warns)
    assert not any(w["severity"] == "warning" for w in warns)


def test_two_moves_same_target_clash(lab: Path):
    (lab / "a2").mkdir()
    (lab / "a2" / "keep.py").write_text("y")
    moves = [
        {"src": str(lab / "a" / "keep.py"), "dst": str(lab / "b"), "type": "file"},
        {"src": str(lab / "a2" / "keep.py"), "dst": str(lab / "b"), "type": "file"},
    ]
    warns = collision_warnings(moves, lab)
    assert any(w["kind"] == "name_clash" for w in warns)


def test_execute_is_noop_without_confirmation(lab: Path):
    src = lab / "a" / "keep.py"
    moves = [{"src": str(src), "dst": str(lab / "b"), "type": "file"}]
    results = execute_moves(moves, lab, confirmed=False)
    assert all(not r["ok"] for r in results)
    assert src.exists()  # nothing moved
    assert not (lab / "b" / "keep.py").exists()


def test_execute_moves_file_and_writes_audit(lab: Path, tmp_path: Path):
    src = lab / "a" / "keep.py"
    moves = [{"src": str(src), "dst": str(lab / "b"), "type": "file"}]
    results = execute_moves(moves, lab, confirmed=True)
    assert results[0]["ok"] is True
    assert not src.exists()
    assert (lab / "b" / "keep.py").exists()
    log = (tmp_path / "moves.log").read_text()
    assert "OK" in log and "keep.py" in log


def test_execute_blocks_on_error_without_force(lab: Path):
    (lab / "b" / "keep.py").write_text("existing")
    src = lab / "a" / "keep.py"
    moves = [{"src": str(src), "dst": str(lab / "b"), "type": "file"}]
    results = execute_moves(moves, lab, confirmed=True, force=False)
    assert all(not r["ok"] for r in results)
    assert src.exists()  # blocked, original intact


def test_force_never_overwrites_existing_file(lab: Path):
    # force may skip the pre-flight gate but must NEVER overwrite an existing file
    (lab / "b" / "keep.py").write_text("ORIGINAL")
    src = lab / "a" / "keep.py"
    moves = [{"src": str(src), "dst": str(lab / "b"), "type": "file"}]
    results = execute_moves(moves, lab, confirmed=True, force=True)
    assert all(not r["ok"] for r in results)
    assert "exists" in (results[-1]["error"] or "")
    assert (lab / "b" / "keep.py").read_text() == "ORIGINAL"  # untouched
    assert src.exists()  # source intact


def test_collision_unsafe_path_surfaces_as_error(lab: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    moves = [{"src": str(outside / "x.py"), "dst": str(lab / "b"), "type": "file"}]
    warns = collision_warnings(moves, lab)
    assert any(w["kind"] == "unsafe_path" and w["severity"] == "error" for w in warns)


def test_execute_rejects_path_outside_root(lab: Path, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    moves = [{"src": str(lab / "a" / "keep.py"), "dst": str(outside), "type": "file"}]
    # collision/build won't include it; execute re-resolves and should fail the move
    results = execute_moves(moves, lab, confirmed=True)
    assert all(not r["ok"] for r in results)
    assert (lab / "a" / "keep.py").exists()
