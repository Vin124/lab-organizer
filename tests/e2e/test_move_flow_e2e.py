"""End-to-end browser test of the full move flow, driving the real UI:

    Browse -> Organize -> drag train.py into shared/ -> dependency warning ->
    preview the exact mv command -> confirm & execute -> file moved on disk +
    audit log written.

This automates the flow that was previously captured by hand (see docs/screenshots).
Excluded from the default test run (marked `e2e`); CI runs it in a dedicated job
with `pytest -m e2e`. Skips cleanly if pytest-playwright isn't installed.
"""
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parent.parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(base: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=1) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("server did not become healthy")


@pytest.fixture
def server(tmp_path: Path):
    root = tmp_path / "lab"
    (root / "code").mkdir(parents=True)
    # train.py imports resnet50.py; leaving resnet50.py behind triggers a warning
    (root / "code" / "train.py").write_text("from resnet50 import build\n")
    (root / "code" / "resnet50.py").write_text("def build():\n    pass\n")
    (root / "shared").mkdir()
    log = tmp_path / "moves.log"

    port = _free_port()
    env = {
        "LAB_ROOT": str(root),
        "MOVES_LOG": str(log),
        "BIND_PORT": str(port),
        "PATH": __import__("os").environ.get("PATH", ""),
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO), env=env,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_healthy(base)
        yield base, root, log
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


# Dispatch a real HTML5 drag/drop sequence the way organize.js listens for it.
_DND = """
([srcSel, dstSel]) => {
  const src = document.querySelector(srcSel);
  const dst = document.querySelector(dstSel);
  if (!src || !dst) return false;
  const dt = new DataTransfer();
  const ev = () => ({ bubbles: true, cancelable: true, dataTransfer: dt });
  src.dispatchEvent(new DragEvent('dragstart', ev()));
  dst.dispatchEvent(new DragEvent('dragover', ev()));
  dst.dispatchEvent(new DragEvent('drop', ev()));
  src.dispatchEvent(new DragEvent('dragend', ev()));
  return true;
}
"""


def test_full_move_flow(server):
    base, root, log = server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(base, wait_until="networkidle")

        # 1. Browse loaded — switch to Organize
        page.click("#mode-organize")
        page.wait_for_selector('.chip[data-name="train.py"]', state="attached")

        # 2. Drag train.py into shared/
        dragged = page.evaluate(_DND, ['.chip[data-name="train.py"]',
                                        '.node.dir[data-name="shared"]'])
        assert dragged is True

        # 3. The move is queued and the dependency warning surfaces
        page.wait_for_function("document.querySelectorAll('#move-list li').length === 1")
        page.wait_for_selector("#warn-list li")
        warn_text = page.inner_text("#warn-list")
        assert "resnet50.py" in warn_text

        # 4. Preview shows the exact mv command; nothing moved yet
        page.click("#preview-btn")
        page.wait_for_function(
            "document.getElementById('modal-commands').textContent.includes('mv ')"
        )
        cmds = page.inner_text("#modal-commands")
        assert "train.py" in cmds
        assert (root / "code" / "train.py").exists()
        assert not (root / "shared" / "train.py").exists()

        # 5. Confirm & execute -> the move actually happens (modal closes, toast shows)
        page.click("#modal-confirm")
        page.wait_for_selector("#toast:not([hidden])")
        assert "Moved" in page.inner_text("#toast")
        assert (root / "shared" / "train.py").exists()
        assert not (root / "code" / "train.py").exists()

        # 6. Audit log records it
        assert log.exists()
        assert "OK" in log.read_text() and "train.py" in log.read_text()

        browser.close()
