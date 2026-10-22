"""The installed app must include every runtime resource from the checkout."""
from pathlib import Path
import subprocess
import zipfile


def test_wheel_contains_runtime_resources(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
                   cwd=root, check=True, capture_output=True, text=True)
    with zipfile.ZipFile(next(tmp_path.glob("*.whl"))) as wheel:
        names = set(wheel.namelist())
        for folder in ("src/web", "src/prompts"):
            expected = {p.relative_to(root).as_posix() for p in (root / folder).rglob("*")
                        if p.is_file() and "__pycache__" not in p.parts}
            assert expected <= names
        assert "src/core/llm/thinking/model_capabilities.json" in names
        assert "src/server.py" in names
        assert not any(name.startswith(("tests/", "scripts/")) for name in names)
        entrypoints = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        assert "tbl = src.server:main" in wheel.read(entrypoints).decode()
