import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_js_unit():
    result = subprocess.run(
        ["node", "--test", "tests/js"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout
