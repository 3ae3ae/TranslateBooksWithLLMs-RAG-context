"""Server-side defaults for newly created jobs; never a running job's config."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from src import config

_lock = threading.RLock()


def preferences_path() -> Path:
    return Path(config.CUSTOM_INSTRUCTIONS_DIR).parent / "settings.json"


def _field(kind, default, **constraints):
    return {"type": kind, "default": default, **constraints}


SCHEMA = {
    "default_connection_id": _field("string", ""),
    "default_model": _field("string", ""),
    "default_reasoning": _field("string", "off", choices=["off", "low", "medium", "high", "default"]),
    "source_language": _field("string", ""),
    "target_language": _field("string", ""),
    "task": _field("string", "translate", choices=["translate", "polish"]),
    "polish_after": _field("boolean", False),
    "notes_mode": _field("string", "build", choices=["build", "copy", "off"]),
    "notes_update_interval": _field("integer", 1, min=1, max=10000),
    "notes_prompt_max_tokens": _field("integer", 1800, min=0, max=1000000),
    "notes_source_memory_chars": _field("integer", 6000, min=0, max=1000000),
    "notes_consolidation_interval": _field("integer", 5, min=0, max=10000),
    "notes_accept_gender_corrections": _field("boolean", True),
    "glossary_id": _field("integer", None, min=1),
    "style": _field("string", ""),
    "simplify_formatting": _field("boolean", False),
    "bilingual": _field("boolean", False),
    "ocr_cleanup": _field("boolean", False),
    "passage_tokens": _field("integer", 450, min=50, max=1000000),
    "chapter_mode": _field("boolean", False),
    "srt_lines_per_block": _field("integer", 10, min=1, max=10000),
    "output_filename_pattern": _field("string", "{originalName} ({targetLang}).{ext}"),
    "price_overrides": _field("object", {}),
    "notifications": _field("object", {}),
    "book_font": _field("string", "sans", choices=["sans", "serif"]),
}
NOTIFICATION_SCHEMA = {
    "enabled": _field("boolean", False),
    "url": _field("string", "", secret=True),
    "method": _field("string", "POST", choices=["GET", "POST", "PUT", "PATCH"]),
    "headers": _field("object", {}, secret=True),
    "payload": _field("string", ""),
    "events": _field("array", ["success", "failure", "system_paused", "queue_finished"]),
    "timeout_seconds": _field("integer", 5, min=1, max=120),
}
SCHEMA["notifications"]["properties"] = NOTIFICATION_SCHEMA


# The default connection and model are owned by the connections store; preferences
# only expose them so the UI reads every default from one place.
_CONNECTION_KEYS = ("default_connection_id", "default_model")


def _connection_defaults():
    try:
        from src.core.llm.connections import get_default
        default = get_default() or {}
    except Exception:
        return {}
    return {"default_connection_id": default.get("connection_id") or "", "default_model": default.get("model") or ""}


def _seed():
    values = {k: copy.deepcopy(v["default"]) for k, v in SCHEMA.items()}
    env_keys = {
        "source_language": "DEFAULT_SOURCE_LANGUAGE", "target_language": "DEFAULT_TARGET_LANGUAGE",
        "passage_tokens": "MAX_TOKENS_PER_CHUNK", "srt_lines_per_block": "SRT_LINES_PER_BLOCK",
        "output_filename_pattern": "OUTPUT_FILENAME_PATTERN", "notes_update_interval": "NOVEL_CONTEXT_UPDATE_INTERVAL",
        "notes_prompt_max_tokens": "NOVEL_CONTEXT_PROMPT_MAX_TOKENS", "notes_source_memory_chars": "NOVEL_CONTEXT_SOURCE_MEMORY_CHARS",
        "notes_consolidation_interval": "NOVEL_CONTEXT_CONSOLIDATION_INTERVAL", "notes_accept_gender_corrections": "BYPASS_CONTEXT_GATING",
    }
    for key, attr in env_keys.items():
        value = getattr(config, attr, values[key])
        if _validate(value, SCHEMA[key]) is None:
            values[key] = value
    values.update(_connection_defaults())
    notifications = {k: copy.deepcopy(v["default"]) for k, v in NOTIFICATION_SCHEMA.items()}
    notifications.update({
        "enabled": bool(config.NOTIFY_WEBHOOK_URL), "url": config.NOTIFY_WEBHOOK_URL,
        "method": config.NOTIFY_WEBHOOK_METHOD, "payload": config.NOTIFY_WEBHOOK_PAYLOAD,
        "timeout_seconds": max(1, min(120, config.NOTIFY_TIMEOUT_SECONDS)),
        "events": [event for event, flag in [("success", config.NOTIFY_ON_SUCCESS), ("failure", config.NOTIFY_ON_FAILURE), ("interruption", config.NOTIFY_ON_INTERRUPTION), ("system_paused", config.NOTIFY_ON_INTERRUPTION), ("queue_finished", config.NOTIFY_ON_SUCCESS)] if flag],
    })
    try:
        headers = json.loads(config.NOTIFY_WEBHOOK_HEADERS or "{}")
        if isinstance(headers, dict) and all(isinstance(v, str) for v in headers.values()):
            notifications["headers"] = headers
    except (ValueError, TypeError):
        pass
    values["notifications"] = notifications
    return values


def _atomic_write(values):
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(values, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_existing_preferences():
    path = preferences_path()
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def get_preferences() -> dict:
    with _lock:
        values = read_existing_preferences()
        if values is None:
            values = _seed()
            _atomic_write(values)
        defaults = {k: copy.deepcopy(v["default"]) for k, v in SCHEMA.items()}
        defaults.update(values)
        defaults["notifications"] = {**{k: copy.deepcopy(v["default"]) for k, v in NOTIFICATION_SCHEMA.items()}, **defaults["notifications"]}
        defaults.update(_connection_defaults())
        return defaults


def _validate(value, rule):
    types = {"string": str, "boolean": bool, "integer": int, "object": dict, "array": list}
    if type(value) is not types[rule["type"]]:
        return "Expected " + rule["type"]
    if "choices" in rule and value not in rule["choices"]:
        return "Invalid choice"
    if "min" in rule and value < rule["min"] or "max" in rule and value > rule["max"]:
        return "Outside allowed range"
    return None


class PreferenceValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Invalid preferences")


def patch_preferences(patch):
    if not isinstance(patch, dict):
        raise PreferenceValidationError({"body": "Expected object"})
    with _lock:
        values = get_preferences()
        errors = {}
        for key, value in patch.items():
            if key not in SCHEMA:
                errors[key] = "Unknown preference"
                continue
            if value is None:
                continue
            error = _validate(value, SCHEMA[key])
            if error:
                errors[key] = error
                continue
            if key == "notifications":
                for subkey, subvalue in value.items():
                    name = "notifications." + subkey
                    if subkey not in NOTIFICATION_SCHEMA:
                        errors[name] = "Unknown preference"
                        continue
                    if subvalue is None:
                        continue
                    error = _validate(subvalue, NOTIFICATION_SCHEMA[subkey])
                    if not error and subkey == "headers" and not all(isinstance(k, str) and isinstance(v, str) and "\n" not in k + v and "\r" not in k + v for k, v in subvalue.items()):
                        error = "Expected string header values without newlines"
                    if not error and subkey == "events" and any(e not in ["success", "failure", "interruption", "system_paused", "queue_finished"] for e in subvalue):
                        error = "Unknown event"
                    if not error and subkey == "url" and subvalue and not subvalue.startswith(("http://", "https://")):
                        error = "Expected HTTP or HTTPS URL"
                    if not error and subkey == "payload" and subvalue:
                        try:
                            json.loads(subvalue)
                        except ValueError:
                            error = "Expected JSON template"
                    if error:
                        errors[name] = error
                    else:
                        values[key][subkey] = subvalue
                continue
            if key == "price_overrides":
                for name, prices in value.items():
                    if not isinstance(prices, dict) or set(prices) != {"input_per_m", "output_per_m"} or any(type(p) not in (int, float) or not math.isfinite(p) or p < 0 for p in prices.values()):
                        errors[key + "." + name] = "Expected nonnegative input_per_m and output_per_m prices"
            values[key] = value
        if errors:
            raise PreferenceValidationError(errors)
        if any(patch.get(key) is not None for key in _CONNECTION_KEYS):
            from src.core.llm.connections import set_default
            current = _connection_defaults()
            connection_id = patch.get("default_connection_id") or current.get("default_connection_id")
            try:
                set_default(connection_id, patch.get("default_model") or None)
            except Exception as exc:
                raise PreferenceValidationError({"default_connection_id": str(exc)}) from exc
        for key in _CONNECTION_KEYS:
            values.pop(key, None)
        _atomic_write(values)
        values.update(_connection_defaults())
        return values


def public_preferences(values):
    values = copy.deepcopy(values)
    for key in ("url", "headers"):
        secret = values["notifications"][key]
        values["notifications"][key] = {"set": bool(secret), "hint": "…/" + secret[-4:] if key == "url" and secret else ""}
    return values


def remember_job_defaults(job_request: dict) -> None:
    patch = {key: job_request[key] for key in SCHEMA if key in job_request and key not in ("notifications", "price_overrides")}
    for source, target in [("connection_id", "default_connection_id"), ("model", "default_model"), ("reasoning", "default_reasoning")]:
        if source in job_request:
            patch[target] = job_request[source]
    for key, value in (job_request.get("notes") or {}).items():
        if "notes_" + key in SCHEMA:
            patch["notes_" + key] = value
    patch_preferences(patch)
