"""AI advisor tests.

The advisor is an optional enhancement: it must degrade gracefully with no key,
and when a key IS set it forwards the move-plan context to Anthropic and returns
the text — without the test needing a real key or network. We inject a fake
`anthropic` module so the import + client call are exercised end-to-end.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_config  # noqa: E402


@pytest.fixture(autouse=True)
def clean_config():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def _reload_ai():
    # ai.py imports get_config at module load; reimport fresh each test.
    sys.modules.pop("backend.ai", None)
    import backend.ai as ai  # noqa: PLC0415
    return ai


def test_degrades_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ai = _reload_ai()
    out = ai.ask_ai("ctx", "Is this safe?")
    assert "not configured" in out.lower()


def test_reports_missing_package(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "anthropic", None)  # force ImportError
    ai = _reload_ai()
    out = ai.ask_ai("ctx", "Is this safe?")
    assert "not installed" in out.lower()


def _fake_anthropic(captured: dict):
    """A stand-in `anthropic` module whose client records the call + echoes text."""
    mod = types.ModuleType("anthropic")

    class _Block:
        type = "text"
        text = "Move resnet50.py together with train.py, or the import will break."

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(content=[_Block()])

    class _Client:
        def __init__(self, **kwargs):
            captured["api_key"] = kwargs.get("api_key")
            self.messages = _Messages()

    mod.Anthropic = _Client
    return mod


def test_forwards_context_and_returns_advice(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    captured: dict = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(captured))
    ai = _reload_ai()

    context = (
        "Warning on train.py: references resnet50.py which stays behind\n"
        'Move plan: [{"src": "/lab/code/train.py", "dst": "/lab/shared"}]'
    )
    out = ai.ask_ai(context, "Will this break anything?")

    assert "resnet50.py" in out                       # the model's advice came back
    assert captured["api_key"] == "sk-test-key"        # key forwarded
    assert "advisor" in captured["system"].lower()     # real system prompt used
    # the move-plan context reached the model
    user_text = captured["messages"][0]["content"]
    assert "train.py" in user_text and "Will this break anything?" in user_text


def test_handles_api_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mod = types.ModuleType("anthropic")

    class _Boom:
        def __init__(self, **kwargs):
            raise RuntimeError("network down")

    mod.Anthropic = _Boom
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    ai = _reload_ai()
    out = ai.ask_ai("ctx", "q")
    assert "failed" in out.lower()
