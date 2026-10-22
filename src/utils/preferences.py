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
    return config.TBL_HOME / "settings.json"


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
    "notes_mode": _field("string", "build", choices=["build", "copy"]),
    "notes_prompt_max_tokens": _field("integer", 1800, min=0, max=1000000),
    "notes_source_memory_chars": _field("integer", 6000, min=0, max=1000000),
    "notes_consolidation_interval": _field("integer", 5, min=0, max=10000),
    "notes_accept_gender_corrections": _field("boolean", True),
    "style": _field("string", ""),
    "simplify_formatting": _field("boolean", False),
    "bilingual": _field("boolean", False),
    "ocr_cleanup": _field("boolean", False),
    "passage_tokens": _field("integer", 450, min=50, max=1000000),
    "chapter_mode": _field("boolean", False),
    "srt_lines_per_block": _field("integer", 10, min=1, max=10000),
    "output_filename_pattern": _field("string", "{originalName} ({targetLang}).{ext}"),
    "price_overrides": _field("object", {}),
    "book_font": _field("string", "sans", choices=["sans", "serif"]),
}


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
        "output_filename_pattern": "OUTPUT_FILENAME_PATTERN",
        "notes_prompt_max_tokens": "NOVEL_CONTEXT_PROMPT_MAX_TOKENS", "notes_source_memory_chars": "NOVEL_CONTEXT_SOURCE_MEMORY_CHARS",
        "notes_consolidation_interval": "NOVEL_CONTEXT_CONSOLIDATION_INTERVAL", "notes_accept_gender_corrections": "BYPASS_CONTEXT_GATING",
    }
    for key, attr in env_keys.items():
        value = getattr(config, attr, values[key])
        if _validate(value, SCHEMA[key]) is None:
            values[key] = value
    values.update(_connection_defaults())
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
        defaults.update({k: v for k, v in values.items() if k in SCHEMA})
        if defaults["notes_mode"] == "off":
            defaults["notes_mode"] = "build"
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


def remember_job_defaults(job_request: dict) -> None:
    patch = {key: job_request[key] for key in SCHEMA if key in job_request and key != "price_overrides"}
    for source, target in [("connection_id", "default_connection_id"), ("model", "default_model"), ("reasoning", "default_reasoning")]:
        if source in job_request:
            patch[target] = job_request[source]
    for key, value in (job_request.get("notes") or {}).items():
        if "notes_" + key in SCHEMA and not (key == "mode" and value == "off"):
            patch["notes_" + key] = value
    patch_preferences(patch)
