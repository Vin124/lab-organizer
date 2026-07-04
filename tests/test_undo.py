"""Undo-last-batch safety tests.

These guard the dangerous parts of undo: it reverses only the most recent
executed batch, never overwrites/merges, is a no-op without confirmation, writes
its own audit entries, and won't re-undo a batch it already reversed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backend.moves as moves_mod  # noqa: E402
from backend.moves import execute_moves, undo_info, undo_last_batch  # noqa: E402


@pytest.fixture
def lab(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "lab"
    (root / "a").mkdir(parents=True)
    (root / "a" / "keep.py").write_text("x")
    (root / "a" / "note.txt").write_text("hi")
    (root / "b").mkdir()
    monkeypatch.setattr(moves_mod, "AUDIT_LOG", tmp_path / "moves.log")
    return root.resolve()


def _move(src: Path, dst: Path) -> dict:
    return {"src": str(src), "dst": str(dst), "type": "file"}


def test_undo_reverses_last_batch(lab: Path):
    src = lab / "a" / "keep.py"
    res = execute_moves([_move(src, lab / "b")], lab, confirmed=True)
    assert res[0]["ok"] and (lab / "b" / "keep.py").exists()

    out = undo_last_batch(lab, confirmed=True)
    assert out["undone"] is True
    assert all(r["ok"] for r in out["results"])
    assert (lab / "a" / "keep.py").exists()       # back home
    assert not (lab / "b" / "keep.py").exists()    # gone from destination


def test_undo_is_noop_without_confirmation(lab: Path):
    src = lab / "a" / "keep.py"
    execute_moves([_move(src, lab / "b")], lab, confirmed=True)
    out = undo_last_batch(lab, confirmed=False)
    assert out["undone"] is False
    assert all(not r["ok"] for r in out["results"])
    assert (lab / "b" / "keep.py").exists()        # still moved, nothing reversed


def test_undo_never_overwrites_occupied_original(lab: Path):
    src = lab / "a" / "keep.py"
    execute_moves([_move(src, lab / "b")], lab, confirmed=True)
    # something now sits where the file used to be
    (lab / "a" / "keep.py").write_text("DIFFERENT — must not be overwritten")

    out = undo_last_batch(lab, confirmed=True)
    assert out["undone"] is False
    assert "occupied" in (out["results"][0]["error"] or "")
    assert (lab / "a" / "keep.py").read_text() == "DIFFERENT — must not be overwritten"
    assert (lab / "b" / "keep.py").exists()        # current copy left intact


def test_undo_writes_its_own_audit_entries(lab: Path, tmp_path: Path):
    src = lab / "a" / "keep.py"
    execute_moves([_move(src, lab / "b")], lab, confirmed=True)
    undo_last_batch(lab, confirmed=True)
    log = (tmp_path / "moves.log").read_text()
    assert "UNDO\t" in log
    assert "UNDO-OK" in log


def test_nothing_to_undo(lab: Path):
    assert undo_info(lab)["available"] is False
    out = undo_last_batch(lab, confirmed=True)
    assert out["undone"] is False
    assert out["error"] == "nothing to undo"


def test_undo_only_reverses_once(lab: Path):
    src = lab / "a" / "keep.py"
    execute_moves([_move(src, lab / "b")], lab, confirmed=True)
    undo_last_batch(lab, confirmed=True)
    # the batch is now marked undone; a second undo finds nothing
    assert undo_info(lab)["available"] is False
    out = undo_last_batch(lab, confirmed=True)
    assert out["undone"] is False


def test_undo_picks_most_recent_batch(lab: Path):
    # batch 1: keep.py -> b
    execute_moves([_move(lab / "a" / "keep.py", lab / "b")], lab, confirmed=True)
    # batch 2: note.txt -> b
    execute_moves([_move(lab / "a" / "note.txt", lab / "b")], lab, confirmed=True)

    out = undo_last_batch(lab, confirmed=True)
    assert out["undone"] is True
    assert (lab / "a" / "note.txt").exists()       # most recent batch reversed
    assert (lab / "b" / "keep.py").exists()        # older batch untouched
    assert not (lab / "a" / "keep.py").exists()


def test_undo_info_reports_count_and_moves(lab: Path):
    execute_moves([_move(lab / "a" / "keep.py", lab / "b")], lab, confirmed=True)
    info = undo_info(lab)
    assert info["available"] is True
    assert info["count"] == 1
    # the reverse move: current location -> original
    assert info["moves"][0]["src"].endswith("keep.py")
    assert info["moves"][0]["dst"].endswith("keep.py")


def test_undo_missing_current_file_blocks(lab: Path):
    src = lab / "a" / "keep.py"
    execute_moves([_move(src, lab / "b")], lab, confirmed=True)
    # the moved file vanishes (deleted out-of-band) before undo
    (lab / "b" / "keep.py").unlink()
    out = undo_last_batch(lab, confirmed=True)
    assert out["undone"] is False
    assert "no longer exists" in (out["results"][0]["error"] or "")


def test_undo_falls_back_to_older_batch(lab: Path):
    execute_moves([_move(lab / "a" / "keep.py", lab / "b")], lab, confirmed=True)   # batch 1
    execute_moves([_move(lab / "a" / "note.txt", lab / "b")], lab, confirmed=True)  # batch 2
    undo_last_batch(lab, confirmed=True)  # reverses batch 2
    assert (lab / "a" / "note.txt").exists()
    # the older batch 1 is now the most recent undoable one
    info = undo_info(lab)
    assert info["available"] is True and info["count"] == 1
    out = undo_last_batch(lab, confirmed=True)
    assert out["undone"] is True
    assert (lab / "a" / "keep.py").exists()


def test_all_fail_batch_is_not_undoable(lab: Path):
    # force skips the pre-flight gate, but the move still FAILs (never overwrites);
    # the resulting batch has a BATCH marker but no OK lines, so nothing to undo.
    (lab / "b" / "keep.py").write_text("occupied")
    res = execute_moves([_move(lab / "a" / "keep.py", lab / "b")], lab,
                        confirmed=True, force=True)
    assert all(not r["ok"] for r in res)
    assert undo_info(lab)["available"] is False


def test_enc_dec_round_trip():
    from backend.moves import _dec, _enc
    for s in ["plain", "with\ttab", "two\nlines", "back\\slash", "/lab/a\tb\nc"]:
        assert _dec(_enc(s)) == s            # reversible
        enc = _enc(s)
        assert "\t" not in enc and "\n" not in enc  # field separators removed


def test_parse_batches_resists_audit_injection():
    # A filename that tries to forge a fake BATCH + redirect undo to /etc/passwd.
    from backend.moves import _enc, _parse_batches
    evil_name = "/lab/a\t2026\tBATCH\tFORGED\t/etc/passwd"
    line = f"2026-01-01T00:00:00\tOK\t{_enc(evil_name)}\t->\t{_enc('/lab/b/x')}"
    batches, undone = _parse_batches(["2026-01-01T00:00:00\tBATCH\treal", line])
    assert len(batches) == 1               # no forged batch boundary
    assert batches[0]["id"] == "real"
    assert "FORGED" not in undone
    # the path is recovered intact, not split at the embedded tabs
    assert batches[0]["moves"] == [(evil_name, "/lab/b/x")]
