"""Inspect actual mocked HTTP requests for connection knobs and reasoning."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from src.core.llm.factory import create_llm_provider, create_llm_client as factory_client
from src.core.llm.key_pool import KeyPool
from src.core.llm.retry import retry_operation
from src.core.llm.exceptions import RateLimitError
from src.core.llm_client import LLMClient, create_llm_client


@pytest.fixture(autouse=True)
def reset_key_state():
    KeyPool.clear_shared_state()
    yield
    KeyPool.clear_shared_state()


def connection(kind, model="test-model", reasoning="off", **fields):
    return dict(llm_provider={"openai_compatible": "openai", "neuralwatt": "openai", "ollama_cloud": "ollama"}.get(kind, kind),
                llm_api_endpoint="https://custom.test/chat", api_key="sk-test-xxxx", model=model,
                reasoning_effort=reasoning, connection_id="test", connection_name="Test", connection_type=kind,
                local=False, request_timeout=47, max_attempts=1, temperature=None,
                rate_limit_behavior="retry", rate_limit_retry_seconds=60, **fields)


def success(kind):
    if kind == "gemini":
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Translated"}]}}],
                                      "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4}})
    if kind in {"ollama", "ollama_cloud"}:
        return httpx.Response(200, text=json.dumps({"message": {"content": "Translated"}, "done": True,
                                                   "prompt_eval_count": 3, "eval_count": 4}) + "\n")
    return httpx.Response(200, json={"choices": [{"message": {"content": "Translated"}}],
                                   "usage": {"prompt_tokens": 3, "completion_tokens": 4}})


async def generate_with_http(connection_config, handler, *, context_window=2048, timeout=None):
    provider = create_llm_provider(connection=connection_config, context_window=context_window)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        return provider, await provider.generate("Translate", system_prompt="Instructions", timeout=timeout)
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'gemini', 'deepseek', 'mistral', 'openrouter', 'poe', 'ollama_cloud'])
@pytest.mark.parametrize('status', [400, 401, 402, 403, 404])
async def test_passage_budget_retries_http_errors_except_auth_and_billing(monkeypatch, kind, status):
    monkeypatch.setattr('asyncio.sleep', AsyncMock())
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={'error': 'offline failure'})

    provider = create_llm_provider(connection=connection(kind) | {'max_attempts': 3})
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await retry_operation(provider, lambda: provider.generate('Translate')) is None
        assert len(requests) == (1 if status in (401, 402, 403) else 3)
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'gemini', 'deepseek', 'mistral', 'openrouter', 'poe', 'ollama_cloud'])
async def test_validation_and_transport_share_one_budget(monkeypatch, kind):
    monkeypatch.setattr('asyncio.sleep', AsyncMock())
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(500) if len(requests) == 1 else success(kind)

    provider = create_llm_provider(connection=connection(kind) | {'max_attempts': 3})
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        response = await retry_operation(
            provider, lambda: provider.generate('Translate'),
            succeeded=lambda result: len(requests) == 3 and result is not None,
        )
        assert response is not None
        assert len(requests) == 3
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['openai', 'gemini', 'deepseek', 'mistral', 'openrouter', 'poe', 'ollama_cloud'])
async def test_exhausted_rate_limit_budget_still_pauses(monkeypatch, kind):
    monkeypatch.setattr('asyncio.sleep', AsyncMock())
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={'Retry-After': '1'})

    provider = create_llm_provider(connection=connection(kind) | {'max_attempts': 3})
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RateLimitError):
            await retry_operation(provider, lambda: provider.generate('Translate'))
        assert len(requests) == 3
    finally:
        await provider.close()


LEVELS = ["off", "low", "medium", "high", "default"]
CASES = [
    ("ollama", "qwen3:8b", "think", [False, "low", "medium", "high", None]),
    ("ollama_cloud", "gpt-oss:120b", "think", ["low", "low", "medium", "high", None]),
    ("openai", "gpt-5.1", "reasoning_effort", ["none", "low", "medium", "high", None]),
    ("openai_compatible", "qwen3", "reasoning_effort", [None, "low", "medium", "high", None]),
    ("neuralwatt", "test-model", "reasoning_effort", ["none", "low", "medium", "high", None]),
    ("openrouter", "anthropic/claude-sonnet-4", "reasoning", [{"enabled": False}, {"effort": "low"}, {"effort": "medium"}, {"effort": "high"}, {"enabled": False}]),
    ("gemini", "gemini-2.5-flash", "thinkingBudget", [0, 1024, 8192, 24576, 0]),
    ("gemini", "gemini-2.5-pro", "thinkingBudget", [128, 1024, 8192, 24576, 128]),
    ("gemini", "gemini-3-flash-preview", "thinkingLevel", ["minimal", "low", "medium", "high", None]),
    ("gemini", "gemini-3-pro-preview", "thinkingLevel", ["low", "low", "high", "high", None]),
    ("deepseek", "deepseek-v4-pro", "thinking", [{"type": "disabled"}, {"type": "enabled"}, {"type": "enabled"}, {"type": "enabled"}, {"type": "disabled"}]),
    ("mistral", "mistral-small-latest", "reasoning_effort", ["none", "high", "high", "high", None]),
    ("poe", "GPT-5.1", "reasoning_effort", ["none", "low", "medium", "high", None]),
    ("nim", "nvidia/nemotron", "reasoning_effort", [None, "low", "medium", "high", None]),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("level_index", range(5), ids=LEVELS)
@pytest.mark.parametrize("kind,model,field,expected", CASES, ids=[f"{kind}-{model}" for kind, model, *_ in CASES])
async def test_provider_reasoning_payloads(kind, model, field, expected, level_index):
    requests = []
    def handler(request):
        requests.append(request)
        return success(kind)
    config = connection(kind, model, LEVELS[level_index])
    provider, result = await generate_with_http(config, handler)
    assert result and result.content == "Translated"
    assert len(requests) == 1
    assert str(requests[0].url) == config["llm_api_endpoint"]
    payload = json.loads(requests[0].content)
    if kind == "neuralwatt" and level_index == 4:
        assert not any(key in payload for key in ("reasoning", "reasoning_effort", "thinking", "think", "chat_template_kwargs"))
    if kind == "gemini":
        actual = payload["generationConfig"].get("thinkingConfig", {}).get(field)
    else:
        actual = payload.get(field)
    assert actual == expected[level_index]
    if kind in {"nim", "openai_compatible"} and level_index == 0:
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    if kind == "gemini":
        assert requests[0].headers["x-goog-api-key"] == "sk-test-xxxx"
        assert "temperature" not in payload["generationConfig"]
    else:
        assert requests[0].headers["Authorization"] == "Bearer sk-test-xxxx"
        assert "temperature" not in payload
    assert requests[0].extensions["timeout"]["read"] == 47


@pytest.mark.asyncio
@pytest.mark.parametrize("model,expected", [("gpt-5", "minimal"), ("gpt-5-mini", "minimal"),
    ("gpt-5.2", "none"), ("gpt-6-astra", "low"), ("gpt-6.1-sol", "low"),
    ("o3", "low"), ("o4-mini", "low"), ("gpt-4o", None), ("o1-pro", None)])
async def test_openai_off_uses_lowest_supported_effort(model, expected):
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return success("openai")
    _, result = await generate_with_http(connection("openai", model), handler)
    assert result
    assert payloads[0].get("reasoning_effort") == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ollama", "ollama_cloud", "openai", "openai_compatible", "neuralwatt", "openrouter", "gemini", "mistral", "deepseek", "poe", "nim"])
async def test_400_drops_reasoning_once_without_spending_attempt(kind, caplog):
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": "Unsupported reasoning/thinking/think/chat_template_kwargs parameter"})
        return success(kind)
    config = connection(kind, "gemini-2.5-flash" if kind == "gemini" else "gpt-5.1")
    if kind == "neuralwatt":
        config["reasoning_effort"] = "high"
    _, result = await generate_with_http(config, handler)
    assert result
    assert len(payloads) == 2
    assert "optional parameters" in caplog.text
    assert not any(key in payloads[-1] for key in ("reasoning", "reasoning_effort", "thinking", "think", "chat_template_kwargs"))
    if kind == "gemini":
        assert "thinkingConfig" not in payloads[-1]["generationConfig"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ollama_cloud", "openai", "neuralwatt", "openrouter", "gemini", "mistral", "deepseek", "poe", "nim"])
async def test_400_temperature_is_sent_then_dropped(kind):
    payloads = []
    def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": "temperature not supported"})
        return success(kind)
    config = connection(kind)
    config["temperature"] = 0.6
    _, result = await generate_with_http(config, handler)
    assert result
    assert len(payloads) == 2
    container = "options" if kind == "ollama_cloud" else "generationConfig" if kind == "gemini" else None
    first = payloads[0][container] if container else payloads[0]
    last = payloads[-1][container] if container else payloads[-1]
    assert first["temperature"] == 0.6
    assert "temperature" not in last


@pytest.mark.asyncio
async def test_repeated_optional_rejection_terminates():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": "reasoning_effort not supported"})
    _, result = await generate_with_http(connection("openai", "gpt-5.1"), handler)
    assert result is None
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_unrelated_400_is_not_retried():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": "Invalid model"})
    _, result = await generate_with_http(connection("openai"), handler)
    assert result is None
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_ollama_level_retries_boolean_then_omits():
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) < 3:
            return httpx.Response(400, json={"error": "think is unsupported"})
        return success("ollama_cloud")
    _, result = await generate_with_http(connection("ollama_cloud", "qwen3", "high"), handler)
    assert result
    assert payloads[0]["think"] == "high"
    assert payloads[1]["think"] is True
    assert "think" not in payloads[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("local,model", [(False, "qwen3"), (True, "large-cloud"), (True, "large:cloud")])
async def test_remote_ollama_skips_probes_and_context_abort(local, model):
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return success("ollama")
    config = connection("ollama", model, "default")
    config["local"] = local
    _, result = await generate_with_http(config, handler, context_window=1)
    assert result and not result.was_truncated
    assert result.context_limit == 0
    assert len(payloads) == 1
    assert "num_ctx" not in payloads[0]["options"]
    assert "think" not in payloads[0]


@pytest.mark.asyncio
async def test_local_ollama_default_keeps_probe_and_num_ctx(monkeypatch):
    from src.core.llm.providers.ollama import OllamaProvider
    from src.core.llm.thinking.behavior import ThinkingBehavior
    probe = AsyncMock(return_value=ThinkingBehavior.CONTROLLABLE)
    monkeypatch.setattr(OllamaProvider, "_detect_thinking_behavior", probe)
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return success("ollama")
    config = connection("ollama", "qwen3:8b", "default")
    config["local"] = True
    _, result = await generate_with_http(config, handler, context_window=8192)
    assert result
    probe.assert_awaited_once()
    assert payloads[0]["options"]["num_ctx"] == 8192
    assert payloads[0]["think"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ollama_cloud", "openai", "openrouter", "gemini", "mistral", "deepseek", "poe", "nim"])
async def test_empty_key_sends_no_auth_despite_env(kind, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-env-xxxx")
    requests = []
    def handler(request):
        requests.append(request)
        return success(kind)
    config = connection(kind)
    config["api_key"] = ""
    _, result = await generate_with_http(config, handler)
    assert result
    assert "Authorization" not in requests[0].headers
    assert "x-goog-api-key" not in requests[0].headers


@pytest.mark.asyncio
async def test_explicit_attempt_and_timeout_settings(monkeypatch):
    from src.core.llm.providers import openai
    sleep = AsyncMock()
    monkeypatch.setattr(openai.asyncio, "sleep", sleep)
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("Test timeout", request=request)
    config = connection("openai")
    config["max_attempts"] = 3
    _, result = await generate_with_http(config, handler, timeout=17)
    assert result is None
    assert len(calls) == 3
    assert all(request.extensions["timeout"]["read"] == 17 for request in calls)
    assert sleep.await_count == 2


def test_client_wrappers_forward_connection_and_override_legacy_fields(monkeypatch):
    resolved = connection("ollama_cloud", "gpt-oss:120b", "low")
    for client in (LLMClient("openai", connection=resolved, api_key="sk-test-ignored"),
                   create_llm_client("gemini", "sk-test-ignored", "https://ignored.test", "ignored", connection=resolved)):
        assert client.provider_type == "ollama"
        assert client.api_endpoint == resolved["llm_api_endpoint"]
        assert client.model == resolved["model"]
        provider = client._get_provider()
        assert provider.connection_type == "ollama_cloud"
        assert provider.api_key == "sk-test-xxxx"
        assert provider.local is False
        assert provider.reasoning_effort == "low"
    assert factory_client(connection=resolved).connection_type == "ollama_cloud"


def test_legacy_factory_still_uses_env_and_auto_detection(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-env-xxxx")
    provider = create_llm_provider("openai", model="test", api_endpoint="https://api.openai.com/v1/chat/completions")
    assert provider.api_key == "sk-test-env-xxxx"
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test-env-yyyy")
    assert create_llm_provider("ollama", model="gemini-2.5-flash").connection_type == "gemini"


@pytest.mark.asyncio
async def test_mistral_thinking_chunks_return_only_answer_text():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": [
            {"type": "thinking", "thinking": [{"type": "text", "text": "Private reasoning"}]},
            {"type": "text", "text": "Translated "}, {"type": "text", "text": "answer"}]}}]})
    _, result = await generate_with_http(connection("mistral", "mistral-small-latest", "high"), handler)
    assert result.content == "Translated answer"


@pytest.mark.asyncio
async def test_ollama_cloud_rotates_keys_without_consuming_attempts():
    keys = []
    def handler(request):
        key = request.headers["Authorization"]
        keys.append(key)
        if key.endswith("xxxx"):
            return httpx.Response(429, headers={"Retry-After": "60"})
        return success("ollama_cloud")
    config = connection("ollama_cloud")
    config["api_key"] = "sk-test-xxxx,sk-test-yyyy"
    _, result = await generate_with_http(config, handler)
    assert result
    assert keys == ["Bearer sk-test-xxxx", "Bearer sk-test-yyyy"]


@pytest.mark.asyncio
async def test_authenticated_local_ollama_context_probe_uses_bearer_key():
    from src.core.llm.providers.ollama import OllamaProvider
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"parameters": "num_ctx 8192"})
    provider = OllamaProvider(api_endpoint="http://localhost:11434/api/chat", api_key="sk-test-xxxx", local=True)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await provider.get_model_context_size() == 8192
    finally:
        await provider.close()
    assert requests[0].headers["Authorization"] == "Bearer sk-test-xxxx"


def test_provider_model_listing_urls_use_custom_connection_endpoints():
    for kind in ("gemini", "openrouter", "mistral", "deepseek", "poe"):
        config = connection(kind)
        config["llm_api_endpoint"] = ("https://custom.test/v1beta/models/gemini-test:generateContent" if kind == "gemini"
                                      else "https://custom.test/v1/chat/completions")
        provider = create_llm_provider(connection=config)
        assert provider.models_url == ("https://custom.test/v1beta/models" if kind == "gemini" else "https://custom.test/v1/models")


@pytest.mark.asyncio
async def test_connection_model_overrides_legacy_make_request_model():
    config = connection("openai", "gpt-5.1")
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return success("openai")
    client = LLMClient(connection=config)
    client._get_provider()._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await client.make_request("Translate", model="legacy-model")
    finally:
        await client.close()
    assert payloads[0]["model"] == "gpt-5.1"


@pytest.mark.parametrize("disabled,expected", [(True, "off"), (False, "low")])
def test_legacy_explicit_deepseek_toggle_remains_effective(disabled, expected):
    provider = create_llm_provider("deepseek", api_key="sk-test-xxxx", deepseek_disable_thinking=disabled)
    assert provider.reasoning_effort == expected
