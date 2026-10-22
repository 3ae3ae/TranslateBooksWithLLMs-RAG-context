"""Translate the UI's reasoning levels into provider request parameters."""

import logging
import re


REASONING_LEVELS = {"off", "low", "medium", "high", "default"}


def reasoning_parameters(connection_type, model, effort, *, local=False):
    if not isinstance(effort, str) or effort not in REASONING_LEVELS:
        raise ValueError("Reasoning must be off, low, medium, high, or default")
    model = model.lower()
    if effort == "default":
        if connection_type == "openrouter":
            return {"reasoning": {"enabled": False}}
        if connection_type == "gemini" and "2.5" in model:
            effort = "off"
        elif connection_type == "openai_compatible" and local:
            effort = "off"
        elif connection_type == "deepseek" and "deepseek-v4" in model:
            effort = "off"
        else:
            return {}
    if connection_type in {"ollama", "ollama_cloud"}:
        return {"think": ("low" if "gpt-oss" in model else False) if effort == "off" else effort}
    if connection_type == "openrouter":
        return {"reasoning": {"enabled": False} if effort == "off" else {"effort": effort}}
    if connection_type == "deepseek":
        return {"thinking": {"type": "disabled" if effort == "off" else "enabled"}}
    if connection_type == "neuralwatt":
        # "none" skips reasoning; models where reasoning is mandatory ignore it.
        return {"reasoning_effort": "none" if effort == "off" else effort}
    if connection_type in {"openai_compatible", "nim"}:
        return {"chat_template_kwargs": {"enable_thinking": False}} if effort == "off" else {"reasoning_effort": effort}
    if connection_type in {"openai", "poe"}:
        # shortcut: Poe bot parameters are best effort; use its native API if a bot ignores this hint.
        if effort != "off":
            return {"reasoning_effort": effort}
        if model.startswith(("o1-pro", "o3-pro", "gpt-5-pro")):
            return {}
        if model.startswith(("o1", "o3", "o4", "gpt-6")):
            return {"reasoning_effort": "low"}
        if re.match(r"gpt-5(?:-(?:mini|nano))?(?:$|-\d{4})", model):
            return {"reasoning_effort": "minimal"}
        if model.startswith("gpt-5"):
            return {"reasoning_effort": "none"}
        return {} if connection_type == "openai" else {"reasoning_effort": "none"}
    if connection_type == "mistral":
        if model == "zai-glm-5-3":
            return {"reasoning_effort": "low" if effort in {"off", "low"} else "high"}
        return {"reasoning_effort": "none" if effort == "off" else "high"}
    if connection_type == "gemini":
        if "2.5" in model:
            budget = {"off": 128 if "pro" in model else 0, "low": 1024, "medium": 8192, "high": 24576}[effort]
            return {"thinkingConfig": {"thinkingBudget": budget}}
        if re.search(r"gemini-[34]", model):
            supports_minimal = "flash" in model and not re.search(r"3\.[78]", model)
            level = ("minimal" if supports_minimal else "low") if effort == "off" else effort
            if model.startswith("gemini-3-pro") and level == "medium":
                level = "high"
            return {"thinkingConfig": {"thinkingLevel": level}}
    return {}


def drop_rejected_parameters(payload, response, *, log_callback=None):
    """A rejected optional field gets one retry; deleting it bounds the retries."""
    if response.status_code not in (400, 422):
        return False
    body = response.text.lower()
    removed = []
    if any(name in body for name in ("reasoning", "thinking", "think", "chat_template_kwargs")):
        for key in ("reasoning", "reasoning_effort", "thinking", "think", "chat_template_kwargs"):
            if key in payload:
                # Older Ollama versions accept booleans but not named levels.
                if key == "think" and payload[key] in ("low", "medium", "high") and "gpt-oss" not in payload.get("model", "").lower():
                    payload[key] = True
                else:
                    del payload[key]
                removed.append(key)
        config = payload.get("generationConfig", {})
        if "thinkingConfig" in config:
            del config["thinkingConfig"]
            removed.append("thinkingConfig")
    if "temperature" in body:
        for config in (payload, payload.get("options", {}), payload.get("generationConfig", {})):
            if "temperature" in config:
                del config["temperature"]
                removed.append("temperature")
    if removed:
        message = "Provider rejected optional parameters; retrying without unsupported settings: " + ", ".join(removed)
        logging.getLogger(__name__).warning(message)
        if log_callback:
            log_callback("llm_http_400_retry", message)
    return bool(removed)
