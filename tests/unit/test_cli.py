import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src import config
from src.core.llm_client import LLMClient, create_llm_client


@pytest.fixture
def cli(monkeypatch):
    translate = AsyncMock(return_value=True)
    refine = AsyncMock(return_value=True)
    logger = Mock()
    notify = Mock()
    monkeypatch.setattr("src.core.adapters.translate_file", translate)
    monkeypatch.setattr("src.core.adapters.refine_file", refine)
    monkeypatch.setattr("src.persistence.checkpoint_manager.CheckpointManager", Mock())
    monkeypatch.setattr("src.utils.unified_logger.setup_cli_logger", Mock(return_value=logger))
    monkeypatch.setattr("src.utils.console.ensure_utf8_stdio", Mock())
    monkeypatch.setattr("src.utils.notifier.notify", notify)
    monkeypatch.setattr(config, "warn_env_config_missing", Mock())
    monkeypatch.setattr(config, "DEFAULT_SOURCE_LANGUAGE", "English")
    monkeypatch.setattr(config, "DEFAULT_TARGET_LANGUAGE", "Korean")
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(config, "API_ENDPOINT", "http://localhost:11434/api/generate")
    for provider in ("gemini", "openai", "openrouter", "mistral", "deepseek", "poe", "nim"):
        monkeypatch.setattr(config, f"{provider.upper()}_API_KEY", "YOUR_API_KEY_HERE")

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["translate.py", "-i", "book.txt", *args])
        return runpy.run_path(str(Path(__file__).resolve().parents[2] / "translate.py"), run_name="__main__")

    return SimpleNamespace(run=run, translate=translate, refine=refine, logger=logger, notify=notify)


@pytest.mark.parametrize("refine_only", [False, True])
@pytest.mark.parametrize("endpoint", [None, "https://custom.example/v1/chat/completions", "http://localhost:11434/api/generate"])
@pytest.mark.parametrize("provider,constructor,default_endpoint", [
    ("ollama", "OllamaProvider", "http://localhost:11434/api/generate"),
    ("openai", "OpenAICompatibleProvider", "http://localhost:11434/api/generate"),
    ("gemini", "GeminiProvider", None),
    ("openrouter", "OpenRouterProvider", config.OPENROUTER_API_ENDPOINT),
    ("mistral", "MistralProvider", config.MISTRAL_API_ENDPOINT),
    ("deepseek", "DeepSeekProvider", config.DEEPSEEK_API_ENDPOINT),
    ("poe", "PoeProvider", config.POE_API_ENDPOINT),
    ("nim", "OpenAICompatibleProvider", config.NIM_API_ENDPOINT),
])
def test_cli_preserves_provider_endpoints(cli, monkeypatch, provider, constructor, default_endpoint, endpoint, refine_only):
    provider_factory = Mock()
    monkeypatch.setattr(f"src.core.llm.factory.{constructor}", provider_factory)
    args = ["--provider", provider, "--model", "test-model"]
    if endpoint is not None:
        args += ["--api_endpoint", endpoint]
    if refine_only:
        args += ["--refine-only"]
    cli.run(*args)
    pipeline = cli.refine if refine_only else cli.translate
    selected_endpoint = pipeline.call_args.kwargs["llm_api_endpoint"]
    expected_cli_endpoint = default_endpoint if provider in {"ollama", "openai"} else None
    assert selected_endpoint == (endpoint if endpoint is not None else expected_cli_endpoint)

    # Generic TXT/SRT and legacy EPUB/refine clients must choose the same endpoint.
    api_keys = {f"{provider}_api_key": "YOUR_API_KEY_HERE"} if provider != "ollama" else {}
    clients = [
        LLMClient(provider, model="test-model", endpoint=selected_endpoint, api_key="YOUR_API_KEY_HERE"),
        create_llm_client(provider, api_endpoint=selected_endpoint, model_name="test-model",
                          **api_keys),
    ]
    for client in clients:
        client._get_provider()
        assert provider_factory.call_args.kwargs["api_endpoint"] == (endpoint if endpoint is not None else default_endpoint)


@pytest.mark.parametrize("refine_only", [False, True])
@pytest.mark.parametrize("language", ["source", "target"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_cli_validates_languages_before_starting(cli, monkeypatch, capsys, refine_only, language, value):
    args = ["--refine-only"] if refine_only else []
    if value is None:
        monkeypatch.setattr(config, f"DEFAULT_{language.upper()}_LANGUAGE", "")
    else:
        args += [f"--{language}_lang", value]

    if refine_only and language == "source":
        cli.run(*args)
        cli.refine.assert_awaited_once()
    else:
        with pytest.raises(SystemExit) as exc:
            cli.run(*args)
        assert exc.value.code == 2
        assert f"--{language}_lang is required" in capsys.readouterr().err
        cli.translate.assert_not_awaited()
        cli.refine.assert_not_awaited()
        config.warn_env_config_missing.assert_not_called()
