"""Dependency-detection tests: expected warnings, no false negatives on obvious
cases, no noise on stdlib imports."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.deps import dependency_warnings, extract_references  # noqa: E402


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    d = tmp_path / "proj"
    code = d / "code"
    code.mkdir(parents=True)
    (code / "train.py").write_text(
        "import numpy as np\n"
        "from resnet50 import build\n"
        "import os\n"
        "data = open('../data/foo.csv')\n"
    )
    (code / "resnet50.py").write_text("def build():\n    pass\n")
    (d / "data").mkdir()
    (d / "data" / "foo.csv").write_text("a,b\n1,2\n")
    (d / "shared").mkdir()
    return d


def test_extract_finds_sibling_import_and_path_literal(proj: Path):
    refs = {p.name for p in extract_references(proj / "code" / "train.py")}
    assert "resnet50.py" in refs
    assert "foo.csv" in refs
    # stdlib imports must NOT appear (no sibling file exists)
    assert "numpy.py" not in refs
    assert "os.py" not in refs


def test_warns_when_file_split_from_dependency(proj: Path):
    # move train.py to shared/, leave resnet50.py behind -> dependency warning
    moves = [{"src": str(proj / "code" / "train.py"), "dst": str(proj / "shared"), "type": "file"}]
    warns = dependency_warnings(moves, proj)
    files = {w["file"] for w in warns}
    assert "train.py" in files
    msgs = " ".join(w["message"] for w in warns)
    assert "resnet50.py" in msgs


def test_no_warning_when_dependency_moves_together(proj: Path):
    # move both train.py and resnet50.py to the same destination -> no dep warning
    shared = str(proj / "shared")
    moves = [
        {"src": str(proj / "code" / "train.py"), "dst": shared, "type": "file"},
        {"src": str(proj / "code" / "resnet50.py"), "dst": shared, "type": "file"},
    ]
    warns = [w for w in dependency_warnings(moves, proj) if "resnet50" in w["message"]]
    assert warns == []


def test_shell_source_dependency(tmp_path: Path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "run.sh").write_text("source ./env.sh\npython train.py\n")
    (d / "env.sh").write_text("export X=1\n")
    (d / "elsewhere").mkdir()
    moves = [{"src": str(d / "run.sh"), "dst": str(d / "elsewhere"), "type": "file"}]
    warns = dependency_warnings(moves, d)
    assert any("env.sh" in w["message"] for w in warns)


def test_no_false_negative_for_obvious_split(proj: Path):
    # the canonical dangerous case must always fire
    moves = [{"src": str(proj / "code" / "train.py"), "dst": str(proj / "shared"), "type": "file"}]
    assert dependency_warnings(moves, proj), "must warn when splitting train.py from its deps"


# --- config-format path literals (yaml / json / toml) ------------------------

@pytest.fixture
def cfgproj(tmp_path: Path) -> Path:
    # data/weights live UNDER conf, so moving the config out of conf splits it from
    # the files it points at (they stay behind) -> the reference breaks.
    d = tmp_path / "c"
    (d / "conf" / "data").mkdir(parents=True)
    (d / "conf" / "data" / "train.csv").write_text("x\n")
    (d / "conf" / "weights").mkdir()
    (d / "conf" / "weights" / "model.pt").write_text("w")
    (d / "out").mkdir()  # a move destination, sibling of conf
    return d


@pytest.mark.parametrize(
    "fname, content",
    [
        ("exp.yaml", 'dataset: "data/train.csv"\nckpt: "weights/model.pt"\n'),
        ("exp.json", '{"dataset": "data/train.csv", "ckpt": "weights/model.pt"}'),
        ("exp.toml", 'dataset = "data/train.csv"\nckpt = "weights/model.pt"\n'),
    ],
)
def test_config_path_literals_detected(cfgproj: Path, fname: str, content: str):
    cfg = cfgproj / "conf" / fname
    cfg.write_text(content)
    refs = {p.name for p in extract_references(cfg)}
    assert "train.csv" in refs
    assert "model.pt" in refs
    # moving the config away from the data it points at -> dependency warning
    moves = [{"src": str(cfg), "dst": str(cfgproj / "out"), "type": "file"}]
    msgs = " ".join(w["message"] for w in dependency_warnings(moves, cfgproj))
    assert "train.csv" in msgs


def test_unquoted_yaml_path_is_a_known_gap(cfgproj: Path):
    # Documents the heuristic's boundary: only *quoted* literals are detected, so
    # an unquoted YAML scalar path is intentionally NOT flagged (avoids FS-walking
    # every bare token). If this ever starts detecting, revisit the trade-off.
    cfg = cfgproj / "conf" / "bare.yaml"
    cfg.write_text("dataset: data/train.csv\n")
    refs = {p.name for p in extract_references(cfg)}
    assert "train.csv" not in refs


# --- nested package imports --------------------------------------------------

def test_nested_package_import_detected(tmp_path: Path):
    d = tmp_path / "proj"
    (d / "pkg" / "models").mkdir(parents=True)
    (d / "pkg" / "__init__.py").write_text("")
    (d / "pkg" / "util.py").write_text("X = 1\n")
    (d / "pkg" / "models" / "__init__.py").write_text("")
    (d / "main.py").write_text(
        "import pkg.util\n"
        "from pkg import models\n"
        "import numpy\n"  # stdlib-ish: no sibling, must not appear
    )
    refs = {p.name for p in extract_references(d / "main.py")}
    assert "util.py" in refs            # dotted submodule import -> pkg/util.py
    assert "__init__.py" in refs        # `from pkg import ...` -> pkg/__init__.py
    assert "numpy.py" not in refs

    (d / "elsewhere").mkdir()
    moves = [{"src": str(d / "main.py"), "dst": str(d / "elsewhere"), "type": "file"}]
    msgs = " ".join(w["message"] for w in dependency_warnings(moves, d))
    assert "util.py" in msgs


def test_no_warning_when_package_moves_with_importer(tmp_path: Path):
    # move main.py AND the pkg/util.py it imports to the same place -> no warning
    d = tmp_path / "proj"
    (d / "pkg").mkdir(parents=True)
    (d / "pkg" / "util.py").write_text("X = 1\n")
    (d / "main.py").write_text("import pkg.util\n")
    (d / "out" / "pkg").mkdir(parents=True)
    moves = [
        {"src": str(d / "main.py"), "dst": str(d / "out"), "type": "file"},
        {"src": str(d / "pkg" / "util.py"), "dst": str(d / "out" / "pkg"), "type": "file"},
    ]
    warns = [w for w in dependency_warnings(moves, d) if "util.py" in w["message"]]
    assert warns == []
