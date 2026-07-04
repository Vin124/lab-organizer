"""Optional shared-token gate tests."""
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.auth import check_basic_auth, is_exempt  # noqa: E402
from backend.config import get_config  # noqa: E402


def _basic(user: str, password: str) -> str:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {raw}"


def test_check_basic_auth_matches_password():
    assert check_basic_auth(_basic("anyone", "s3cret"), "s3cret") is True


def test_check_basic_auth_rejects_wrong_or_missing():
    assert check_basic_auth(_basic("u", "nope"), "s3cret") is False
    assert check_basic_auth(None, "s3cret") is False
    assert check_basic_auth("Bearer s3cret", "s3cret") is False
    assert check_basic_auth("Basic !!!notbase64!!!", "s3cret") is False
    # no colon -> malformed
    bad = "Basic " + base64.b64encode(b"nocolon").decode()
    assert check_basic_auth(bad, "s3cret") is False


def test_check_basic_auth_rejects_empty_token():
    # an empty token means "auth not configured" — must never authenticate, even
    # with a matching empty password (guards a future caller that skips the or-None).
    assert check_basic_auth(_basic("u", ""), "") is False
    assert check_basic_auth(_basic("u", "x"), "") is False


def test_healthz_exempt():
    assert is_exempt("/healthz") is True
    assert is_exempt("/api/tree") is False


@pytest.fixture
def lab(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.setenv("LAB_ROOT", str(root))
    yield root
    get_config.cache_clear()


def test_auth_disabled_by_default(lab: Path, monkeypatch):
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    get_config.cache_clear()
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get("/api/config").status_code == 200


def test_auth_enabled_blocks_without_creds(lab: Path, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "s3cret")
    get_config.cache_clear()
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/config")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Basic")

    ok = client.get("/api/config", headers={"Authorization": _basic("lab", "s3cret")})
    assert ok.status_code == 200

    bad = client.get("/api/config", headers={"Authorization": _basic("lab", "wrong")})
    assert bad.status_code == 401

    # healthz stays reachable without creds
    assert client.get("/healthz").status_code == 200
