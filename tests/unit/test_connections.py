"""Connection storage, migration, URLs, and browser contracts (no network)."""

import json
import os

import httpx
import pytest
from flask import Flask

from src.core.llm import connections as store
from src.core.llm.factory import create_llm_provider


@pytest.fixture
def connection_store(tmp_path, monkeypatch):
    path = tmp_path / "TranslateBook_Data" / "connections.json"
    monkeypatch.setattr(store, "CONNECTIONS_PATH", path)
    builtin = store._normalize({"name": "Local Ollama", "type": "ollama", "default_model": "local-model"})
    builtin.update(id="local-ollama", builtin=True)
    store._write({"connections": [builtin], "default": {"connection_id": "local-ollama", "model": "local-model"}})
    return path


def add_connection(**fields):
    return store.create_connection({"type": "openai_compatible", "name": "Test server",
                                    "base_url": "http://localhost:8000", **fields})


def test_crud_masks_keys_and_keeps_private_atomic_file(connection_store):
    created = add_connection(api_keys=["sk-test-xxxx", "sk-test-yyyy"], default_model="test-model")
    assert created["key_count"] == 2
    assert created["key_hint"] == "xxxx"
    assert "api_keys" not in created
    assert "sk-test-" not in json.dumps(store.list_connections())
    assert store.get_connection(created["id"]) == created
    updated = store.update_connection(created["id"], {"name": "Renamed"})
    assert updated["name"] == "Renamed"
    assert updated["key_count"] == 2
    assert store.resolve_for_pipeline(created["id"], "test-model")["api_key"] == "sk-test-xxxx,sk-test-yyyy"
    assert store.set_default(created["id"]) == {"connection_id": created["id"], "model": "test-model"}
    assert store.get_default()["connection_id"] == created["id"]
    assert store.update_connection(created["id"], {"api_keys": []})["key_count"] == 0
    assert connection_store.stat().st_mode & 0o777 == 0o600
    assert not list(connection_store.parent.glob(".connections-*"))
    store.delete_connection(created["id"])
    assert store.get_connection(created["id"]) is None
    assert store.get_default()["connection_id"] == "local-ollama"
    with pytest.raises(store.ConnectionNotFound):
        store.resolve_for_pipeline(created["id"], "test-model")


def test_builtin_is_editable_but_not_deletable(connection_store):
    with pytest.raises(ValueError, match="cannot be deleted"):
        store.delete_connection("local-ollama")
    with pytest.raises(ValueError, match="type cannot be changed"):
        store.update_connection("local-ollama", {"type": "openai"})
    result = store.update_connection("local-ollama", {"base_url": "http://studio.local:11434/api/generate"})
    assert result["resolved"]["chat_url"] == "http://studio.local:11434/api/chat"
    assert result["builtin"] and result["local"]


def test_atomic_failure_preserves_original_file(connection_store, monkeypatch):
    original = connection_store.read_bytes()
    def fail_replace(*args):
        raise OSError("Disk unavailable")
    monkeypatch.setattr(store.os, "replace", fail_replace)
    with pytest.raises(OSError):
        add_connection()
    assert connection_store.read_bytes() == original
    assert not list(connection_store.parent.glob(".connections-*"))


def test_corrupt_store_is_not_replaced(connection_store):
    connection_store.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError, match="restore"):
        add_connection()
    assert connection_store.read_text() == "broken"


@pytest.mark.parametrize("kind,raw,base,chat,models", [
    ("ollama", "http://localhost:11434/", "http://localhost:11434", "/api/chat", "/api/tags"),
    ("ollama", "http://localhost:11434/api/generate", "http://localhost:11434", "/api/chat", "/api/tags"),
    ("ollama", "http://host.local/prefix/api/chat/", "http://host.local/prefix", "/api/chat", "/api/tags"),
    ("ollama_cloud", "https://ollama.com", "https://ollama.com", "/api/chat", "/api/tags"),
    ("openai", "https://api.openai.com/v1/chat/completions/", "https://api.openai.com/v1", "/chat/completions", "/models"),
    ("openai_compatible", "http://[::1]:8000/", "http://[::1]:8000/v1", "/chat/completions", "/models"),
    ("openai_compatible", "https://server.example/custom/v2", "https://server.example/custom/v2", "/chat/completions", "/models"),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "https://openrouter.ai/api/v1", "/chat/completions", "/models"),
    ("gemini", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent", "https://generativelanguage.googleapis.com/v1beta", "/models/{model}:generateContent", "/models"),
    ("deepseek", "https://api.deepseek.com/chat/completions", "https://api.deepseek.com", "/chat/completions", "/models"),
])
def test_url_normalization(kind, raw, base, chat, models):
    actual_base, resolved = store.normalize_url(kind, raw)
    assert actual_base == base
    assert resolved == {"chat_url": base + chat, "models_url": base + models}


def test_url_keeps_noncredential_query_on_resolved_paths():
    base, resolved = store.normalize_url("openai_compatible", "https://example.test?version=2026")
    assert base == "https://example.test/v1?version=2026"
    assert resolved["chat_url"] == "https://example.test/v1/chat/completions?version=2026"


@pytest.mark.parametrize("url", [
    "https://user:password@example.test/v1", "https://user@example.test/v1",
    "https://example.test?key=sk-test-xxxx", "https://example.test?api_key=sk-test-xxxx",
    "https://example.test?access_token=placeholder", "https://example.test?%74oken=placeholder",
    "https://example.test?X-Amz-Signature=placeholder", "https://example.test?KEY=",
    "file:///etc/passwd", "javascript:alert(1)", "https://example.test#token=placeholder",
    "https://example.test:invalid", "https://example.test/white space",
])
def test_rejects_credentials_and_invalid_urls(url):
    with pytest.raises(ValueError):
        store.normalize_url("openai_compatible", url)


@pytest.mark.parametrize("host,expected", [("localhost", True), ("127.0.0.1", True),
    ("[::1]", True), ("machine.local", True), ("LOCALHOST.", True),
    ("localhost.example.com", False), ("192.168.1.9", False), ("example.com", False)])
def test_locality_and_type_defaults(connection_store, host, expected):
    connection = add_connection(base_url=f"http://{host}:8000")
    assert connection["local"] is expected
    assert connection["parallel_requests"] == (1 if expected else 4)
    assert connection["request_timeout"] == (900 if expected else 300)
    assert connection["max_attempts"] == 2
    assert connection["rate_limit_behavior"] == "retry"
    assert connection["rate_limit_retry_seconds"] == 60
    assert connection["temperature"] is None


def test_explicit_locality_persists_and_knobs_are_resolved(connection_store):
    created = add_connection(local=False, parallel_requests=3, request_timeout=45, max_attempts=5,
                             rate_limit_behavior="pause", rate_limit_retry_seconds=12, temperature=0.7)
    updated = store.update_connection(created["id"], {"base_url": "http://other.local:8000"})
    assert updated["local"] is False
    result = store.resolve_for_pipeline(created["id"], "chosen-model", "high")
    assert result == dict(llm_provider="openai", llm_api_endpoint="http://other.local:8000/v1/chat/completions",
                         api_key="", model="chosen-model", reasoning_effort="high", connection_id=created["id"],
                         connection_type="openai_compatible", connection_name="Test server", local=False,
                         parallel_requests=3, request_timeout=45, max_attempts=5,
                         rate_limit_behavior="pause", rate_limit_retry_seconds=12, temperature=0.7)


@pytest.mark.parametrize("fields", [{"local": "false"}, {"parallel_requests": 0},
    {"request_timeout": True}, {"max_attempts": -1}, {"rate_limit_behavior": "unknown"},
    {"rate_limit_retry_seconds": 0}, {"temperature": float("nan")}, {"temperature": True},
    {"temperature": 3}, {"api_keys": "sk-test-xxxx"}, {"api_keys": [1]}, {"api_keys": ["line\nbreak"]},
    {"builtin": True}, {"id": "fake"}, {"name": ""}, {"default_model": None}])
def test_validates_draft_fields(connection_store, fields):
    with pytest.raises(ValueError):
        add_connection(**fields)


def test_resolve_and_factory_never_fall_back_to_env(connection_store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-env-xxxx")
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test-env-yyyy")
    for kind in store._TYPES:
        fields = {"type": kind}
        if kind == "openai_compatible":
            fields["base_url"] = "https://server.test/v1"
        connection = store.create_connection(fields)
        resolved = store.resolve_for_pipeline(connection["id"], "gemini-model")
        assert resolved["api_key"] == ""
        provider = create_llm_provider("wrong-provider", api_key="sk-test-ignored", connection=resolved)
        assert provider.api_key is None
        assert provider.api_endpoint == resolved["llm_api_endpoint"]
        assert provider.model == "gemini-model"
        assert provider.request_timeout == connection["request_timeout"]
        assert provider.max_attempts == connection["max_attempts"]
        assert provider.temperature is None
        assert provider.reasoning_effort == "off"
        assert provider.connection_type == kind


@pytest.mark.parametrize("official", [False, True])
def test_migration_seeds_existing_config_once(connection_store, monkeypatch, official):
    from src import config
    connection_store.unlink()
    values = {
        "LLM_PROVIDER": "openai", "DEFAULT_MODEL": "configured-model",
        "OLLAMA_API_ENDPOINT": "http://studio.local:11434/api/generate",
        "OPENAI_API_ENDPOINT": "https://api.openai.com/v1/chat/completions" if official else "https://custom.test/v1/chat/completions",
        "OPENAI_API_KEY": "sk-test-xxxx,sk-test-yyyy", "OLLAMA_API_KEY": "sk-test-ollama",
        **{f"{name}_API_KEY": f"sk-test-{name.lower()}" for name in ("GEMINI", "OPENROUTER", "MISTRAL", "DEEPSEEK", "POE", "NIM")},
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    items = store.list_connections()
    assert len(items) == 9
    migrated = next(item for item in items if item["type"] in {"openai", "openai_compatible"})
    assert migrated["name"] == ("OpenAI" if official else "OpenAI-compatible")
    assert migrated["key_count"] == 2
    assert store.get_default() == {"connection_id": migrated["id"], "model": "configured-model"}
    assert store.get_connection("local-ollama")["base_url"] == "http://studio.local:11434"
    cloud = next(item for item in items if item["type"] == "ollama_cloud")
    assert cloud["local"] is False
    assert cloud["resolved"]["chat_url"] == "https://ollama.com/api/chat"
    assert connection_store.stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-new")
    assert store.list_connections() == items
    assert store.resolve_for_pipeline(migrated["id"], "m")["api_key"] == "sk-test-xxxx,sk-test-yyyy"


@pytest.fixture
def api(connection_store):
    from src.api.auth import API_TOKEN, register_auth
    from src.api.blueprints.connections_routes import create_connections_blueprint
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_auth(app)
    app.register_blueprint(create_connections_blueprint())
    return app.test_client(), {"X-API-Token": API_TOKEN}


def mock_models(monkeypatch, handler):
    client_class = httpx.Client
    monkeypatch.setattr(store.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handler), **kw))


def test_routes_crud_types_defaults_and_auth(api):
    client, headers = api
    assert client.get("/api/connections").status_code == 401
    types = client.get("/api/connection-types", headers=headers).json["types"]
    assert {item["type"] for item in types} == set(store._TYPES)
    assert set(types[0]) == {"type", "default_base_url", "base_url_editable", "base_url_required", "key_required", "reasoning", "temperature"}
    created = client.post("/api/connections", headers=headers, json={"type": "openai", "api_keys": ["sk-test-xxxx"], "default_model": "gpt-4o"})
    assert created.status_code == 201
    connection = created.json["connection"]
    assert "api_keys" not in connection
    cid = connection["id"]
    updated = client.patch(f"/api/connections/{cid}", headers=headers, json={"local": True, "parallel_requests": 1, "request_timeout": 910,
                           "max_attempts": 3, "rate_limit_behavior": "pause", "rate_limit_retry_seconds": 4, "temperature": None})
    assert updated.json["connection"]["request_timeout"] == 910
    assert updated.json["connection"]["key_count"] == 1
    assert client.post(f"/api/connections/{cid}/default", json={"model": "gpt-4.1"}, headers=headers).json == {"connection_id": cid, "model": "gpt-4.1"}
    listed = client.get("/api/connections", headers=headers).json
    assert listed["default"]["model"] == "gpt-4.1"
    assert client.delete(f"/api/connections/{cid}", headers=headers).status_code == 200
    assert client.patch(f"/api/connections/{cid}", json={}, headers=headers).json["error"]["code"] == "connection_not_found"
    assert client.delete("/api/connections/local-ollama", headers=headers).json["error"]["code"] == "invalid_request"
    assert client.post("/api/connections", data="broken", content_type="application/json", headers=headers).json["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("kind,model", [("openai", "gpt-4o"), ("ollama_cloud", "cloud-model"), ("gemini", "gemini-2.5-pro")])
def test_draft_route_lists_models_and_sends_one_token_chat(api, monkeypatch, kind, model):
    client, headers = api
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            item = {"name": f"models/{model}", "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1000} if kind == "gemini" else {"id": model}
            return httpx.Response(200, json={"models" if kind in {"gemini", "ollama_cloud"} else "data": [item]})
        return httpx.Response(200, json={})
    mock_models(monkeypatch, handler)
    before = store.CONNECTIONS_PATH.read_bytes()
    response = client.post("/api/connections/test", headers=headers, json={"type": kind, "api_keys": ["sk-test-xxxx"], "model": model})
    assert response.status_code == 200
    result = response.json
    assert result["ok"] and result["chat_ok"]
    assert result["chat_error"] is None
    assert result["model_count"] == len(result["models"]) == 1
    assert result["models"][0]["id"] == model
    assert result["latency_ms"] >= 0
    assert len(requests) == 2
    assert "sk-test-" not in response.get_data(as_text=True)
    payload = json.loads(requests[1].content)
    if kind == "gemini":
        assert payload["generationConfig"]["maxOutputTokens"] == 1
        assert requests[1].headers["x-goog-api-key"] == "sk-test-xxxx"
    elif kind == "ollama_cloud":
        assert payload["options"]["num_predict"] == 1
        assert "num_ctx" not in payload["options"]
        assert requests[1].headers["Authorization"] == "Bearer sk-test-xxxx"
    else:
        assert payload["max_completion_tokens"] == 1
    assert store.CONNECTIONS_PATH.read_bytes() == before


def test_test_route_preserves_list_and_reports_sanitized_chat_error(api, monkeypatch):
    client, headers = api
    created = store.create_connection({"type": "openai", "api_keys": ["sk-test-xxxx"]})
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "gpt-4o"}]})
        return httpx.Response(401, json={"error": "sk-test-xxxx rejected"})
    mock_models(monkeypatch, handler)
    response = client.post("/api/connections/test", headers=headers, json={"id": created["id"], "model": "gpt-4o"})
    assert response.json["model_count"] == 1
    assert response.json["chat_ok"] is False
    assert response.json["chat_error"] == "Provider returned HTTP 401"
    assert "sk-test-xxxx" not in response.get_data(as_text=True)


@pytest.mark.parametrize("kind", ["openrouter", "poe"])
def test_models_include_api_prices(connection_store, monkeypatch, kind):
    created = store.create_connection({"type": kind})
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "test-model", "name": "Test model", "context_length": 32000,
                              "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]})
    mock_models(monkeypatch, handler)
    assert store.list_models(created["id"]) == [{"id": "test-model", "name": "Test model", "context_length": 32000,
                "pricing": {"input_per_m": 1, "output_per_m": 2}, "remote": False}]


def test_local_ollama_models_mark_remote_without_free_prices(connection_store, monkeypatch):
    mock_models(monkeypatch, lambda request: httpx.Response(200, json={"models": [
        {"name": "local:latest"}, {"name": "large-cloud"}, {"name": "large:cloud"}, {"name": "other", "remote_host": "https://ollama.com"}]}))
    models = store.list_models("local-ollama")
    assert [item["remote"] for item in models] == [False, True, True, True]
    assert all(item["pricing"] is None for item in models)


def test_gemini_model_listing_paginates(connection_store, monkeypatch):
    created = store.create_connection({"type": "gemini"})
    requests = []
    def handler(request):
        requests.append(request)
        item = {"name": "models/gemini-2.5-flash", "displayName": "Gemini Flash", "supportedGenerationMethods": ["generateContent"]}
        if "pageToken" not in request.url.params:
            return httpx.Response(200, json={"models": [item], "nextPageToken": "next"})
        return httpx.Response(200, json={"models": [{"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]}]})
    mock_models(monkeypatch, handler)
    models = store.list_models(created["id"])
    assert len(models) == 1
    assert models[0]["pricing"] == {"input_per_m": 0.3, "output_per_m": 2.5}
    assert requests[1].url.params["pageToken"] == "next"


def test_test_route_retries_optional_parameters_without_persisting(api, monkeypatch):
    client, headers = api
    payloads = []
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "gpt-5.1"}]})
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": "reasoning_effort unsupported"})
        return httpx.Response(200, json={})
    mock_models(monkeypatch, handler)
    result = client.post("/api/connections/test", headers=headers, json={"type": "openai", "model": "gpt-5.1"}).json
    assert result["ok"] and result["chat_ok"]
    assert payloads[0]["reasoning_effort"] == "none"
    assert "reasoning_effort" not in payloads[1]


def test_model_route_reports_safe_provider_errors(api, monkeypatch):
    client, headers = api
    mock_models(monkeypatch, lambda request: httpx.Response(403, text="sk-test-xxxx is invalid"))
    response = client.get("/api/connections/local-ollama/models", headers=headers)
    assert response.status_code == 502
    assert response.json == {"error": {"code": "provider_http_error", "message": "Provider returned HTTP 403"}}
    assert "sk-test" not in response.get_data(as_text=True)


@pytest.mark.parametrize("field,value", [("type", []), ("rate_limit_behavior", []), ("reasoning", [])])
def test_routes_reject_wrong_json_field_types(api, field, value):
    client, headers = api
    path = "/api/connections/test" if field == "reasoning" else "/api/connections"
    response = client.post(path, headers=headers, json={"type": "openai", field: value})
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_request"


def test_empty_configuration_migrates_only_builtin(connection_store, monkeypatch):
    from src import config
    connection_store.unlink()
    monkeypatch.setattr(store.os, "environ", {})
    for name in ("OPENAI", "GEMINI", "OPENROUTER", "MISTRAL", "DEEPSEEK", "POE", "NIM", "OLLAMA"):
        monkeypatch.setattr(config, f"{name}_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "OPENAI_API_ENDPOINT", "https://api.openai.com/v1/chat/completions")
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    assert [item["id"] for item in store.list_connections()] == ["local-ollama"]


def test_migration_uses_provider_model_when_default_not_explicit(connection_store, monkeypatch):
    from src import config
    connection_store.unlink()
    monkeypatch.setattr(store.os, "environ", {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "sk-test-xxxx", "GEMINI_MODEL": "gemini-2.5-pro"})
    for name in ("OPENAI", "OPENROUTER", "MISTRAL", "DEEPSEEK", "POE", "NIM", "OLLAMA"):
        monkeypatch.setattr(config, f"{name}_API_KEY", "", raising=False)
    monkeypatch.setattr(config, "OPENAI_API_ENDPOINT", "https://api.openai.com/v1/chat/completions")
    assert store.get_default() == {"connection_id": "gemini", "model": "gemini-2.5-pro"}


def test_auth_failure_uses_new_error_shape(api):
    client, _ = api
    response = client.get("/api/connections")
    assert response.status_code == 401
    assert response.json == {"error": {"code": "missing_or_invalid_token", "message": "Unauthorized"}}


@pytest.mark.parametrize("model", ["large-cloud", "large:cloud", "large-cloud:latest"])
def test_remote_model_on_local_ollama_resolves_as_remote_execution(connection_store, model):
    assert store.get_connection("local-ollama")["local"] is True
    resolved = store.resolve_for_pipeline("local-ollama", model)
    assert resolved["local"] is False
    assert resolved["connection_type"] == "ollama"
