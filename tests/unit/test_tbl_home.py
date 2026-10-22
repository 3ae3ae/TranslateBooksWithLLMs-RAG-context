"""User data and dotenv locations must not depend on the launch directory."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src import config


@pytest.mark.parametrize("platform,variable,override,suffix", [
    ("darwin", None, None, "Library/Application Support/TBL"),
    ("linux", None, None, ".local/share/tbl"),
    ("linux", "XDG_DATA_HOME", "xdg", "xdg/tbl"),
    ("win32", None, None, "AppData/Roaming/TBL"),
    ("win32", "APPDATA", "roaming", "roaming/TBL"),
    ("darwin", "TBL_HOME", "custom", "custom"),
    ("linux", "TBL_HOME", "custom", "custom"),
    ("win32", "TBL_HOME", "custom", "custom"),
])
def test_tbl_home_resolution(tmp_path, monkeypatch, platform, variable, override, suffix):
    for name in ("TBL_HOME", "XDG_DATA_HOME", "APPDATA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    if variable:
        monkeypatch.setenv(variable, str(tmp_path / override))
    monkeypatch.setattr(sys, "platform", platform)
    assert config.resolve_tbl_home() == tmp_path / suffix


@pytest.mark.parametrize("override", ["~/custom", "custom"])
def test_relative_tbl_home_is_anchored_to_home(tmp_path, monkeypatch, override):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("TBL_HOME", override)
    monkeypatch.chdir(tmp_path.parent)
    assert config.resolve_tbl_home() == tmp_path / "custom"


@pytest.mark.parametrize("process_model", [None, "process-model"])
@pytest.mark.parametrize("output_override", [None, "finished", "absolute"])
def test_config_reads_only_home_dotenv(tmp_path, process_model, output_override):
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / ".env").write_text("DEFAULT_MODEL=cwd-model\nOUTPUT_DIR=cwd-output\n")
    (home / ".env").write_text("DEFAULT_MODEL=home-model\n")
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TBL_HOME": str(home),
           "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    if process_model:
        env["DEFAULT_MODEL"] = process_model
    if output_override:
        env["OUTPUT_DIR"] = str(tmp_path / "absolute") if output_override == "absolute" else output_override
    result = subprocess.run([
        sys.executable, "-c",
        "import json; from src import config as c; "
        "print(json.dumps([c.DEFAULT_MODEL, c.OUTPUT_DIR, str(c.DATA_DIR), "
        "str(c.INCOMING_DIR), str(c.UPLOADS_DIR), str(c.THUMBNAILS_DIR), "
        "str(c.NOVEL_CONTEXTS_DIR), str(c.CUSTOM_INSTRUCTIONS_DIR)]))",
    ], cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    expected_output = tmp_path / "absolute" if output_override == "absolute" else home / (output_override or "translations")
    assert json.loads(result.stdout) == [process_model or "home-model", str(expected_output),
        str(home / "data"), str(home / "data/incoming"), str(home / "data/uploads"),
        str(home / "data/thumbnails"), str(home / "notes"), str(home / "styles")]
    assert list(home.iterdir()) == [home / ".env"]
