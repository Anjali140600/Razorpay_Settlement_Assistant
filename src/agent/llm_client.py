"""LLM client — Groq (primary), Gemini (fallback), OpenRouter (fallback). All three are
OpenAI-compatible endpoints, so one client shape covers them."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Groq retired llama-3.3-70b-versatile on 2026-08-16 — see console.groq.com/docs/deprecations
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
# gemini-2.5-flash was retired for new users; Google's own 404 names the replacement.
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-oss-120b"
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))

_PROVIDER_ORDER = ("groq", "gemini", "openrouter")


def _has_provider(provider: str) -> bool:
    if provider == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    if provider == "gemini":
        return bool(os.getenv("GEMINI_API_KEY"))
    if provider == "openrouter":
        return bool(os.getenv("OPENROUTER_API_KEY"))
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
    if provider == "gemini":
        return "react_gemini"
    if provider == "openrouter":
        return "react_openrouter"
    return "react_planner"


def get_llm_model(provider: str | None = None) -> str:
    provider = provider or llm_provider()
    if provider == "groq":
        return os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    if provider == "openrouter":
        return os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
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
    """Create OpenAI-compatible client for Groq, Gemini, or OpenRouter.

    Retries are disabled so a quota-blocked model fails fast and callers can
    fail over to the next model/provider instead of waiting on SDK backoff.
    """
    from openai import OpenAI

    opts: dict[str, Any] = {"timeout": LLM_TIMEOUT_SECONDS, "max_retries": 0}
    provider = provider or llm_provider()
    if provider == "groq":
        return OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url=GROQ_BASE_URL, **opts)
    if provider == "gemini":
        return OpenAI(api_key=os.environ["GEMINI_API_KEY"], base_url=GEMINI_BASE_URL, **opts)
    if provider == "openrouter":
        return OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"], base_url=OPENROUTER_BASE_URL, **opts
        )
    raise RuntimeError("No GROQ_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY configured")
