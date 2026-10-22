"""Server-owned model connections. Secrets leave this module only for requests."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

import httpx

from .base import normalize_api_keys
from .thinking.parameters import REASONING_LEVELS, drop_rejected_parameters, reasoning_parameters
from src.config import TBL_HOME


CONNECTIONS_PATH = TBL_HOME / "connections.json"
_lock = threading.RLock()
_TYPES = {
    "ollama": ("Ollama", "http://localhost:11434", False, "levels"),
    "ollama_cloud": ("Ollama Cloud", "https://ollama.com", True, "levels"),
    "openai": ("OpenAI", "https://api.openai.com/v1", True, "levels"),
    "neuralwatt": ("Neuralwatt", "https://api.neuralwatt.com/v1", True, "best_effort"),
    "openai_compatible": ("OpenAI-compatible", "", False, "best_effort"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", True, "levels"),
    "gemini": ("Gemini", "https://generativelanguage.googleapis.com/v1beta", True, "levels"),
    "mistral": ("Mistral", "https://api.mistral.ai/v1", True, "best_effort"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com", True, "on_off"),
    "poe": ("Poe", "https://api.poe.com/v1", True, "best_effort"),
    "nim": ("NVIDIA NIM", "https://integrate.api.nvidia.com/v1", True, "best_effort"),
}
_KNOBS = ("request_timeout", "max_attempts", "rate_limit_behavior",
          "rate_limit_retry_seconds", "temperature")
_FIELDS = {"name", "type", "base_url", "api_keys", "default_model", "local", *_KNOBS}


class ConnectionNotFound(Exception):
    pass


def connection_types() -> list[dict]:
    return [dict(type=kind, default_base_url=base, base_url_editable=True,
                 base_url_required=True, key_required=key,
                 reasoning=reasoning, temperature=True)
            for kind, (label, base, key, reasoning) in _TYPES.items()]


def normalize_url(connection_type: str, base_url: str) -> tuple[str, dict]:
    if not isinstance(connection_type, str) or connection_type not in _TYPES:
        raise ValueError("Unknown connection type")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url must be an HTTP or HTTPS URL")
    try:
        parsed = urlsplit(base_url.strip())
        host, port = parsed.hostname, parsed.port
    except ValueError:
        raise ValueError("Invalid base_url") from None
    if parsed.scheme not in {"http", "https"} or not host or any(c.isspace() for c in base_url):
        raise ValueError("base_url must be an HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not contain credentials")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        compact = re.sub(r"[^a-z0-9]", "", unquote(key).lower())
        if compact in {"auth", "sig", "pwd"} or any(word in compact for word in ("key", "token", "secret", "password", "credential", "authorization", "signature")):
            raise ValueError("base_url must not contain credentials")
    if parsed.fragment:
        raise ValueError("base_url must not contain a fragment")
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    path = parsed.path.rstrip("/")
    if connection_type in {"ollama", "ollama_cloud"}:
        for suffix in ("/api/chat", "/api/generate", "/api/tags", "/api"):
            if path.endswith(suffix):
                path = path[:-len(suffix)]
                break
        chat, models = path + "/api/chat", path + "/api/tags"
    elif connection_type == "gemini":
        path = re.sub(r"/models(?:/[^/]+:generateContent)?$", "", path)
        chat, models = path + "/models/{model}:generateContent", path + "/models"
    else:
        path = re.sub(r"/(?:chat/completions|models)$", "", path)
        if connection_type == "openai_compatible" and not path:
            path = "/v1"
        chat, models = path + "/chat/completions", path + "/models"
    def url(url_path):
        return urlunsplit((parsed.scheme, authority, url_path, parsed.query, ""))
    return url(path), {"chat_url": url(chat), "models_url": url(models)}


def _is_local(base_url):
    host = urlsplit(base_url).hostname.lower().rstrip(".")
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


def _normalize(fields, previous=None):
    if not isinstance(fields, dict):
        raise ValueError("Unknown connection fields")
    fields = {key: value for key, value in fields.items() if key != "parallel_requests"}
    if fields.keys() - _FIELDS:
        raise ValueError("Unknown connection fields")
    connection = dict(previous or {})
    connection.pop("parallel_requests", None)
    connection.update(fields)
    kind = connection.get("type")
    if not isinstance(kind, str) or kind not in _TYPES:
        raise ValueError("Unknown connection type")
    base, resolved = normalize_url(kind, connection.get("base_url", _TYPES[kind][1]))
    local = connection.get("local")
    local_explicit = "local" in fields or bool(previous and previous.get("_local_explicit"))
    if not local_explicit and (not previous or "base_url" in fields):
        local = _is_local(base)
    if not isinstance(local, bool):
        raise ValueError("local must be a boolean")
    defaults = dict(request_timeout=900 if local else 300,
                    max_attempts=2, rate_limit_behavior="retry", rate_limit_retry_seconds=60,
                    temperature=None, default_model="", api_keys=[])
    connection = {**defaults, **connection, "base_url": base, "resolved": resolved,
                  "local": local, "_local_explicit": local_explicit}
    name = connection.get("name", _TYPES[kind][0])
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError("name must be a nonempty string of at most 200 characters")
    connection["name"] = name.strip()
    if not isinstance(connection["default_model"], str) or len(connection["default_model"]) > 500:
        raise ValueError("default_model must be a string of at most 500 characters")
    keys = connection["api_keys"]
    if not isinstance(keys, list) or any(not isinstance(key, str) or "\r" in key or "\n" in key for key in keys):
        raise ValueError("api_keys must be a list of strings without line breaks")
    connection["api_keys"] = list(dict.fromkeys(key.strip() for key in keys if key.strip()))
    for key in ("request_timeout", "max_attempts", "rate_limit_retry_seconds"):
        value = connection[key]
        if type(value) is not int or value < 1:
            raise ValueError(f"{key} must be a positive integer")
    if connection["rate_limit_behavior"] not in ("pause", "retry"):
        raise ValueError("rate_limit_behavior must be pause or retry")
    temperature = connection["temperature"]
    if temperature is not None and (type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2):
        raise ValueError("temperature must be null or a number between 0 and 2")
    return connection


def _write(data):
    path = Path(CONNECTIONS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".connections-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _migrate():
    from src import config
    def setting(name, default=""):
        return os.environ.get(name, getattr(config, name, default))
    builtin = _normalize({"type": "ollama", "name": "Local Ollama",
                          "base_url": setting("OLLAMA_API_ENDPOINT", _TYPES["ollama"][1]),
                          "default_model": setting("DEFAULT_MODEL")})
    builtin.update(id="local-ollama", builtin=False)
    items = [builtin]
    provider = setting("LLM_PROVIDER", "ollama").lower()
    default_id, default_model = "", ""
    for kind in ("openai", "neuralwatt", "gemini", "openrouter", "mistral", "deepseek", "poe", "nim", "ollama_cloud"):
        prefix = "OLLAMA" if kind == "ollama_cloud" else kind.upper()
        keys = normalize_api_keys(setting(prefix + "_API_KEY"))
        endpoint = setting(prefix + "_API_ENDPOINT", _TYPES[kind][1]) if kind != "ollama_cloud" else "https://ollama.com"
        if not keys and not (kind == "openai" and (provider in {"openai", "openai_compatible"} or endpoint != _TYPES[kind][1] + "/chat/completions")):
            continue
        if kind == "openai" and urlsplit(endpoint).hostname != "api.openai.com":
            kind = "openai_compatible"
        selected = provider in {kind, "openai" if kind == "openai_compatible" else kind}
        model = setting(prefix + "_MODEL")
        if selected:
            model = os.environ.get("DEFAULT_MODEL") or model or setting("DEFAULT_MODEL")
        item = _normalize({"type": kind, "name": _TYPES[kind][0], "base_url": endpoint,
                           "api_keys": keys, "default_model": model})
        item.update(id=kind.replace("_", "-"), builtin=False)
        items.append(item)
        if selected:
            default_id, default_model = item["id"], model
    return {"connections": items, "default": {"connection_id": default_id, "model": default_model}}


def _read():
    path = Path(CONNECTIONS_PATH)
    if not path.exists():
        data = _migrate()
        _write(data)
        return data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data["connections"], list) or not isinstance(data["default"], dict):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError("connections.json is invalid; restore it before editing connections") from None
    for connection in data["connections"]:
        connection.pop("parallel_requests", None)
        if connection.get('builtin'):
            connection['builtin'] = False
            if connection.get('local') and data['default'].get('connection_id') == connection['id']:
                data['default'] = {'connection_id': '', 'model': ''}
            _write(data)
    return data


def _find(data, connection_id):
    for connection in data["connections"]:
        if connection["id"] == connection_id:
            return connection
    raise ConnectionNotFound("Connection removed or not found; choose a model connection")


def _view(connection):
    result = {key: value for key, value in connection.items() if key not in {"api_keys", "_local_explicit"}}
    keys = connection["api_keys"]
    result.update(key_count=len(keys), key_hint=keys[0][-4:] if keys else "")
    return result


def list_connections() -> list[dict]:
    with _lock:
        return [_view(item) for item in _read()["connections"]]


def get_connection(connection_id) -> dict | None:
    with _lock:
        try:
            return _view(_find(_read(), connection_id))
        except ConnectionNotFound:
            return None


def create_connection(fields) -> dict:
    connection = _normalize(fields)
    connection.update(id=uuid.uuid4().hex, builtin=False)
    with _lock:
        data = _read()
        data["connections"].append(connection)
        _write(data)
    return _view(connection)


def update_connection(connection_id, fields) -> dict:
    with _lock:
        data = _read()
        previous = _find(data, connection_id)
        connection = _normalize(fields, previous)
        data["connections"][data["connections"].index(previous)] = connection
        _write(data)
    return _view(connection)


def delete_connection(connection_id) -> None:
    with _lock:
        data = _read()
        connection = _find(data, connection_id)
        data["connections"].remove(connection)
        if data["default"]["connection_id"] == connection_id:
            data["default"] = {"connection_id": "", "model": ""}
        _write(data)


def get_default() -> dict:
    with _lock:
        return dict(_read()["default"])


def set_default(connection_id, model=None) -> dict:
    with _lock:
        data = _read()
        connection = _find(data, connection_id)
        model = connection["default_model"] if model is None else model
        _validate_model(model)
        data["default"] = {"connection_id": connection_id, "model": model}
        _write(data)
        return dict(data["default"])


def _validate_model(model):
    if not isinstance(model, str) or not model.strip() or len(model) > 500:
        raise ValueError("model must be a nonempty string of at most 500 characters")


def _resolve(connection, model, reasoning):
    _validate_model(model)
    if not isinstance(reasoning, str) or reasoning not in REASONING_LEVELS:
        raise ValueError("Reasoning must be off, low, medium, high, or default")
    kind = connection["type"]
    provider = {"ollama_cloud": "ollama", "openai_compatible": "openai", "neuralwatt": "openai"}.get(kind, kind)
    local = connection["local"] and not (kind == "ollama" and re.search(r"(?:-cloud|:cloud)(?:$|:)", model))
    return dict(llm_provider=provider,
                llm_api_endpoint=connection["resolved"]["chat_url"].replace("{model}", model),
                api_key=",".join(connection["api_keys"]), model=model, reasoning_effort=reasoning,
                connection_id=connection.get("id", ""), connection_type=kind,
                connection_name=connection["name"], local=bool(local),
                **{key: connection[key] for key in _KNOBS})


def resolve_for_pipeline(connection_id: str, model: str, reasoning: str = "off") -> dict:
    with _lock:
        return _resolve(_find(_read(), connection_id), model, reasoning)


def _headers(connection):
    keys = connection["api_keys"]
    if not keys:
        return {}
    return {"x-goog-api-key": keys[0]} if connection["type"] == "gemini" else {"Authorization": f"Bearer {keys[0]}"}


def _list_models(connection, client):
    from src.core.pricing.pricing_data import get_default_pricing
    kind = connection["type"]
    models, page = [], None
    while True:
        response = client.get(connection["resolved"]["models_url"], headers=_headers(connection),
                              params={"pageToken": page} if page else None)
        response.raise_for_status()
        data = response.json()
        for item in data.get("models" if kind in {"ollama", "ollama_cloud", "gemini"} else "data", []):
            if kind == "gemini" and "generateContent" not in item.get("supportedGenerationMethods", []):
                continue
            metadata = item.get("metadata") or {}
            if kind == "neuralwatt" and (metadata.get("deprecated") or item.get("deprecated")):
                continue
            model = item.get("id") or item.get("name", "")
            if kind == "gemini":
                model = model.removeprefix("models/")
            if not model:
                continue
            pricing = None
            name = item.get("displayName") or item.get("name") or model
            context_length = item.get("context_length") or item.get("inputTokenLimit") or item.get("max_context_length")
            raw = item.get("pricing") or {}
            if kind == "neuralwatt":
                name = metadata.get("display_name") or model
                context_length = item.get("max_model_len") or (metadata.get("limits") or {}).get("max_context_length")
                raw = metadata.get("pricing") or {}
                prices = (raw.get("input_per_million"), raw.get("output_per_million"))
                if raw.get("currency") == "USD" and not raw.get("pricing_tbd") and all(
                    type(price) in (int, float) and math.isfinite(price) and price >= 0 for price in prices
                ):
                    pricing = {"input_per_m": prices[0], "output_per_m": prices[1]}
            elif kind in {"openrouter", "poe"} and raw.get("prompt") is not None and raw.get("completion") is not None:
                pricing = {"input_per_m": float(raw["prompt"]) * 1_000_000,
                           "output_per_m": float(raw["completion"]) * 1_000_000}
            elif not connection["local"]:
                known = get_default_pricing(kind, model)
                if known:
                    pricing = {"input_per_m": known["input"], "output_per_m": known["output"]}
            remote = kind == "ollama_cloud" or (kind == "ollama" and connection["local"] and
                     bool(item.get("remote_host") or item.get("remote_model") or re.search(r"(?:-cloud|:cloud)(?:$|:)", model)))
            models.append(dict(id=model, name=name,
                               pricing=pricing, context_length=context_length,
                               remote=remote))
        page = data.get("nextPageToken") if kind == "gemini" else None
        if not page:
            return models


def list_models(connection_id) -> list[dict]:
    with _lock:
        connection = _find(_read(), connection_id)
    with httpx.Client(timeout=connection["request_timeout"]) as client:
        return _list_models(connection, client)


def test_connection(fields) -> dict:
    """Test a saved connection or an unsaved draft without persisting secrets."""
    import time
    started = time.monotonic()
    fields = dict(fields)
    connection_id = fields.pop("id", None)
    model = fields.pop("model", None)
    reasoning = fields.pop("reasoning", "off")
    with _lock:
        previous = _find(_read(), connection_id) if connection_id else None
    connection = _normalize(fields, previous)
    result = dict(ok=False, models=[], model_count=0, chat_ok=None, chat_error=None,
                  latency_ms=0, error=None, resolved=connection["resolved"])
    if model is not None:
        _validate_model(model)
    if not isinstance(reasoning, str) or reasoning not in REASONING_LEVELS:
        raise ValueError("Invalid reasoning level")
    try:
        with httpx.Client(timeout=connection["request_timeout"]) as client:
            result["models"] = _list_models(connection, client)
            result["model_count"] = len(result["models"])
            if model:
                result["chat_ok"] = False
                kind = connection["type"]
                if kind == "gemini":
                    payload = {"contents": [{"parts": [{"text": "Hi"}]}],
                               "generationConfig": {"maxOutputTokens": 1, **reasoning_parameters(kind, model, reasoning)}}
                    if connection["temperature"] is not None:
                        payload["generationConfig"]["temperature"] = connection["temperature"]
                else:
                    payload = {"model": model, "messages": [{"role": "user", "content": "Hi"}], "stream": False,
                               **reasoning_parameters(kind, model, reasoning, local=connection["local"])}
                    if kind in {"ollama", "ollama_cloud"}:
                        payload["options"] = {"num_predict": 1}
                        if connection["temperature"] is not None:
                            payload["options"]["temperature"] = connection["temperature"]
                    else:
                        payload["max_completion_tokens" if kind == "openai" else "max_tokens"] = 1
                        if connection["temperature"] is not None:
                            payload["temperature"] = connection["temperature"]
                while True:
                    response = client.post(connection["resolved"]["chat_url"].replace("{model}", model),
                                           headers=_headers(connection), json=payload)
                    if drop_rejected_parameters(payload, response):
                        continue
                    response.raise_for_status()
                    break
                result["chat_ok"] = True
            result["ok"] = True
    except httpx.HTTPStatusError as error:
        result["error"] = {"code": "provider_http_error", "message": f"Provider returned HTTP {error.response.status_code}"}
    except (httpx.RequestError, ValueError, TypeError, KeyError):
        result["error"] = {"code": "connection_failed", "message": "Could not connect or read the provider response"}
    if result["chat_ok"] is False and result["error"]:
        result["chat_error"] = result["error"]["message"]
    result["latency_ms"] = round((time.monotonic() - started) * 1000)
    return result
