"""LLM client — Groq (primary), Cerebras (fallback), or OpenAI via OpenAI-compatible SDK."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"
# Groq retired llama-3.3-70b-versatile on 2026-08-16 — see console.groq.com/docs/deprecations
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
DEFAULT_CEREBRAS_MODEL = "gpt-oss-120b"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))

_PROVIDER_ORDER = ("groq", "cerebras", "openai")


def _has_provider(provider: str) -> bool:
    if provider == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    if provider == "cerebras":
        return bool(os.getenv("CEREBRAS_API_KEY"))
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    return False


def llm_providers_available() -> list[str]:
    return [p for p in _PROVIDER_ORDER if _has_provider(p)]


def iter_llm_providers() -> Iterator[str]:
    for provider in _PROVIDER_ORDER:
        if _has_provider(provider):
            yield provider


def llm_provider() -> str | None:
    """Return first available provider name or None."""
    available = llm_providers_available()
    return available[0] if available else None


def should_use_llm() -> bool:
    flag = os.getenv("USE_LLM", "0").lower() in ("1", "true", "yes")
    return flag and bool(llm_providers_available())


def agent_mode_label(use_llm: bool, provider: str | None = None) -> str:
    if not use_llm:
        return "react_planner"
    provider = provider or llm_provider()
    if provider == "groq":
        return "react_groq"
    if provider == "cerebras":
        return "react_cerebras"
    if provider == "openai":
        return "react_llm"
    return "react_planner"


def get_llm_model(provider: str | None = None) -> str:
    provider = provider or llm_provider()
    if provider == "groq":
        return os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    if provider == "cerebras":
        return os.getenv("CEREBRAS_MODEL", DEFAULT_CEREBRAS_MODEL)
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    raise RuntimeError("No LLM provider configured")


def assistant_message_for_api(msg: Any) -> dict[str, Any]:
    """Strip OpenAI SDK fields Groq/Cerebras reject when replaying tool-call turns."""
    dump_fn = getattr(msg, "model_dump", None)
    if callable(dump_fn):
        try:
            dump = dump_fn(exclude_none=True)
        except TypeError:
            dump = dump_fn()
    else:
        dump = {"role": "assistant", "content": getattr(msg, "content", None)}
    if not isinstance(dump, dict):
        dump = {"role": "assistant", "content": ""}
    for key in ("annotations", "audio", "function_call", "refusal"):
        dump.pop(key, None)
    return dump


def create_llm_client(provider: str | None = None) -> Any:
    """Create OpenAI-compatible client for Groq, Cerebras, or OpenAI.

    Retries are disabled so a quota-blocked model fails fast and callers can
    fail over to the next model/provider instead of waiting on SDK backoff.
    """
    from openai import OpenAI

    opts: dict[str, Any] = {"timeout": LLM_TIMEOUT_SECONDS, "max_retries": 0}
    provider = provider or llm_provider()
    if provider == "groq":
        return OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL, **opts)
    if provider == "cerebras":
        return OpenAI(api_key=os.environ["CEREBRAS_API_KEY"], base_url=CEREBRAS_BASE_URL, **opts)
    if provider == "openai":
        return OpenAI(api_key=os.environ["OPENAI_API_KEY"], **opts)
    raise RuntimeError("No GROQ_API_KEY, CEREBRAS_API_KEY, or OPENAI_API_KEY configured")
