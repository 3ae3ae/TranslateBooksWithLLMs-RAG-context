"""
Pytest configuration and fixtures for all tests.

This file is automatically loaded by pytest and provides common fixtures
and configuration for all test modules.
"""

import sys
import os
from pathlib import Path
import importlib.util
from tempfile import TemporaryDirectory

# Collection imports config too, before per-test fixtures can run.
_collection_home = TemporaryDirectory(prefix="tbl-tests-")
os.environ["TBL_HOME"] = _collection_home.name

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import pytest for fixtures
import pytest


def import_module_from_path(module_name, file_path):
    """
    Import a module directly from file path without triggering package imports.

    This avoids circular import issues when testing isolated modules.
    """
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Pre-load EPUB modules to avoid circular import issues
_epub_exceptions = import_module_from_path(
    'src.core.epub.exceptions',
    project_root / 'src' / 'core' / 'epub' / 'exceptions.py'
)

_placeholder_validator = import_module_from_path(
    'src.core.epub.placeholder_validator',
    project_root / 'src' / 'core' / 'epub' / 'placeholder_validator.py'
)

_tag_preservation = import_module_from_path(
    'src.core.epub.tag_preservation',
    project_root / 'src' / 'core' / 'epub' / 'tag_preservation.py'
)


# ---------------------------------------------------------------------------
# Translator's Sampler — canonical EPUB fixture
# ---------------------------------------------------------------------------
# Built on demand from scripts/build_test_epub.py so the script itself is the
# only versioned artifact (the .epub is gitignored under /tests).

_sampler_module = import_module_from_path(
    'scripts.build_test_epub',
    project_root / 'scripts' / 'build_test_epub.py',
)


@pytest.fixture(scope="session")
def sampler_epub_path(tmp_path_factory):
    """Path to a freshly built Translator's Sampler EPUB, scoped to the session."""
    out = tmp_path_factory.mktemp("sampler") / "translation_sampler.epub"
    _sampler_module.build_epub(out)
    return out


@pytest.fixture(scope="session")
def sampler_epub_bytes(sampler_epub_path):
    """Raw bytes of the sampler EPUB."""
    return sampler_epub_path.read_bytes()


@pytest.fixture(scope="session")
def sampler_spine_docs():
    """Mapping of {href: xhtml_string} for the sampler's spine documents."""
    return dict(_sampler_module.SPINE_DOCS)


@pytest.fixture(autouse=True)
def _isolate_user_data(tmp_path, monkeypatch):
    """Keep all app data, including credentials and defaults, inside each test."""
    import src.config as config
    from src.core.llm import connections
    from src.core.llm.thinking import cache

    home = tmp_path / "_user_data"
    monkeypatch.setenv("TBL_HOME", str(home))
    monkeypatch.setattr(config, "TBL_HOME", home)
    monkeypatch.setattr(config, "DATA_DIR", home / "data")
    monkeypatch.setattr(config, "UPLOADS_DIR", home / "data" / "uploads")
    monkeypatch.setattr(config, "INCOMING_DIR", home / "data" / "incoming")
    monkeypatch.setattr(config, "THUMBNAILS_DIR", home / "data" / "thumbnails")
    monkeypatch.setattr(config, "OUTPUT_DIR", str(home / "translations"))
    monkeypatch.setattr(config, "NOVEL_CONTEXTS_DIR", home / "notes")
    monkeypatch.setattr(config, "CUSTOM_INSTRUCTIONS_DIR", home / "styles")
    monkeypatch.setattr(connections, "CONNECTIONS_PATH", home / "connections.json")
    monkeypatch.setattr(cache, "_global_cache", None)
