"""Create providers, preserving the legacy env defaults outside connections."""

import os
from urllib.parse import urlsplit

from src import config
from .base import LLMProvider, normalize_api_keys
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAICompatibleProvider
from .providers.gemini import GeminiProvider
from .providers.openrouter import OpenRouterProvider
from .providers.mistral import MistralProvider
from .providers.deepseek import DeepSeekProvider
from .providers.poe import PoeProvider


def _require_key(raw, error_message: str):
    if not normalize_api_keys(raw):
        raise ValueError(error_message)
    return raw


def create_llm_provider(provider_type: str = "ollama", *, connection: dict | None = None, **kwargs) -> LLMProvider:
    if connection is not None:
        provider_type = connection["llm_provider"]
        kwargs.update(api_endpoint=connection["llm_api_endpoint"], model=connection["model"],
                      api_key=connection["api_key"],
                      **{key: connection[key] for key in (
                          "request_timeout", "max_attempts", "temperature", "reasoning_effort",
                          "local", "connection_type")})
    provider_type = provider_type.lower()
    model = kwargs.get("model", config.DEFAULT_MODEL)
    if connection is None and provider_type == "ollama" and model and model.startswith("gemini"):
        provider_type = "gemini"
    options = {key: kwargs[key] for key in (
        "request_timeout", "max_attempts", "temperature", "reasoning_effort", "local",
        "connection_type", "log_callback") if key in kwargs}
    endpoint = kwargs.get("api_endpoint") or kwargs.get("endpoint")

    def key(prefix):
        if connection is not None:
            return kwargs["api_key"]
        value = kwargs.get("api_key") or kwargs.get(prefix.lower() + "_api_key") or os.getenv(prefix + "_API_KEY", getattr(config, prefix + "_API_KEY", ""))
        if provider_type not in {"ollama", "openai", "openai_compatible"}:
            _require_key(value, f"{prefix} provider requires an API key. Set {prefix}_API_KEY or pass api_key.")
        return value

    if provider_type in {"ollama", "ollama_cloud"}:
        if provider_type == "ollama_cloud":
            options.setdefault("local", False)
            options.setdefault("connection_type", "ollama_cloud")
        return OllamaProvider(api_endpoint=endpoint or ("https://ollama.com/api/chat" if provider_type == "ollama_cloud" else config.API_ENDPOINT),
                              model=model, api_key=key("OLLAMA"),
                              context_window=kwargs.get("context_window") or config.OLLAMA_NUM_CTX, **options)
    if provider_type in {"openai", "openai_compatible", "nim"}:
        endpoint = endpoint or (config.NIM_API_ENDPOINT if provider_type == "nim" else "")
        pname = "nim" if provider_type == "nim" else ("openai" if urlsplit(endpoint).hostname == "api.openai.com" else "openai-compatible")
        return OpenAICompatibleProvider(api_endpoint=endpoint,
                                        model=kwargs.get("model", config.NIM_MODEL if provider_type == "nim" else config.DEFAULT_MODEL),
                                        api_key=key("NIM" if provider_type == "nim" else "OPENAI"),
                                        context_window=kwargs.get("context_window") or config.OLLAMA_NUM_CTX,
                                        provider_name=pname, **options)
    if provider_type == "gemini":
        return GeminiProvider(api_key=key("GEMINI"), model=kwargs.get("model", "gemini-2.0-flash"),
                              api_endpoint=endpoint, **options)
    if provider_type == "openrouter":
        return OpenRouterProvider(api_key=key("OPENROUTER"), model=kwargs.get("model", config.OPENROUTER_MODEL),
                                  api_endpoint=endpoint or config.OPENROUTER_API_ENDPOINT, **options)
    if provider_type == "mistral":
        return MistralProvider(api_key=key("MISTRAL"), model=kwargs.get("model", config.MISTRAL_MODEL),
                               api_endpoint=endpoint or config.MISTRAL_API_ENDPOINT, **options)
    if provider_type == "deepseek":
        if connection is None and "deepseek_disable_thinking" in kwargs:
            options.setdefault("reasoning_effort", "off" if kwargs["deepseek_disable_thinking"] else "low")
        return DeepSeekProvider(api_key=key("DEEPSEEK"), model=kwargs.get("model", config.DEEPSEEK_MODEL),
                                api_endpoint=endpoint or config.DEEPSEEK_API_ENDPOINT, **options)
    if provider_type == "poe":
        return PoeProvider(api_key=key("POE"), model=kwargs.get("model", config.POE_MODEL),
                           api_endpoint=endpoint or config.POE_API_ENDPOINT, **options)
    raise ValueError(f"Unknown provider type: {provider_type}")


def create_llm_client(provider_type: str = "ollama", *, connection: dict | None = None, **kwargs) -> LLMProvider:
    return create_llm_provider(provider_type, connection=connection, **kwargs)
