"""Path-safety tests: escapes must be rejected, legit paths allowed.

These are the dangerous-bug tests — a hole here means arbitrary FS access.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.safety import UnsafePathError, safe_resolve  # noqa: E402


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "lab"
    (r / "cftr" / "vin").mkdir(parents=True)
    (r / "cftr" / "vin" / "train.py").write_text("x")
    return r.resolve()


def test_allows_path_inside_root(root: Path):
    p = safe_resolve(str(root / "cftr" / "vin" / "train.py"), root)
    assert p == (root / "cftr" / "vin" / "train.py").resolve()


def test_allows_root_itself(root: Path):
    assert safe_resolve(str(root), root) == root


def test_allows_nonexistent_dest_inside_root(root: Path):
    # move destinations don't exist yet — must still be allowed
    p = safe_resolve(str(root / "cftr" / "shared" / "new.py"), root)
    assert str(p).startswith(str(root))


def test_rejects_dotdot_escape(root: Path):
    with pytest.raises(UnsafePathError):
        safe_resolve(str(root / "cftr" / ".." / ".." / "secret"), root)


def test_rejects_absolute_outside(root: Path, tmp_path: Path):
    outside = tmp_path / "outside" / "passwd"
    outside.parent.mkdir()
    outside.write_text("secret")
    with pytest.raises(UnsafePathError):
        safe_resolve(str(outside), root)


def test_rejects_empty_path(root: Path):
    with pytest.raises(UnsafePathError):
        safe_resolve("", root)


def test_rejects_dotdot_traversal_string(root: Path):
    with pytest.raises(UnsafePathError):
        safe_resolve(str(root) + "/../../../etc/passwd", root)


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privilege on Windows")
def test_rejects_symlink_escape(root: Path, tmp_path: Path):
    secret = tmp_path / "secret_area"
    secret.mkdir()
    (secret / "keys.txt").write_text("topsecret")
    link = root / "cftr" / "escape"
    link.symlink_to(secret)
    # accessing through the symlink resolves outside root -> rejected
    with pytest.raises(UnsafePathError):
        safe_resolve(str(link / "keys.txt"), root)
