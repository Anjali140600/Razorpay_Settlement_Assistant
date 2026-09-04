"""Provider selection and fallback ordering for the LLM client."""

from __future__ import annotations

import pytest

from src.agent import llm_client as lc


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    """Provider availability reads os.environ directly, so tests must isolate it."""
    for key in (
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "CEREBRAS_API_KEY",
        "OPENAI_API_KEY",
        "USE_LLM",
    ):
        monkeypatch.delenv(key, raising=False)


def test_no_provider_configured():
    assert lc.llm_providers_available() == []
    assert lc.llm_provider() is None


def test_groq_only(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    assert lc.llm_providers_available() == ["groq"]
    assert lc.llm_provider() == "groq"


def test_gemini_only(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk_x")
    assert lc.llm_providers_available() == ["gemini"]


def test_openrouter_only(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "ork_x")
    assert lc.llm_providers_available() == ["openrouter"]


def test_fallback_order_is_groq_then_gemini_then_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "ork_x")
    monkeypatch.setenv("GEMINI_API_KEY", "gk_x")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    assert lc.llm_providers_available() == ["groq", "gemini", "openrouter"]
    assert list(lc.iter_llm_providers()) == ["groq", "gemini", "openrouter"]
    assert lc.llm_provider() == "groq"


def test_cerebras_and_openai_are_no_longer_recognised(monkeypatch):
    """The provider set is exactly groq/gemini/openrouter now."""
    monkeypatch.setenv("CEREBRAS_API_KEY", "csk_x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk_x")
    assert lc.llm_providers_available() == []


def test_should_use_llm_requires_flag_and_provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk_x")
    monkeypatch.setenv("USE_LLM", "0")
    assert lc.should_use_llm() is False
    monkeypatch.setenv("USE_LLM", "1")
    assert lc.should_use_llm() is True


def test_agent_mode_label_per_provider(monkeypatch):
    assert lc.agent_mode_label(False) == "react_planner"
    assert lc.agent_mode_label(True, "groq") == "react_groq"
    assert lc.agent_mode_label(True, "gemini") == "react_gemini"
    assert lc.agent_mode_label(True, "openrouter") == "react_openrouter"


def test_get_llm_model_defaults(monkeypatch):
    assert lc.get_llm_model("groq") == lc.DEFAULT_GROQ_MODEL
    assert lc.get_llm_model("gemini") == lc.DEFAULT_GEMINI_MODEL
    assert lc.get_llm_model("openrouter") == lc.DEFAULT_OPENROUTER_MODEL


def test_get_llm_model_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-custom")
    assert lc.get_llm_model("gemini") == "gemini-custom"
    monkeypatch.setenv("OPENROUTER_MODEL", "some/other-model")
    assert lc.get_llm_model("openrouter") == "some/other-model"


def test_get_llm_model_raises_with_no_provider():
    with pytest.raises(RuntimeError, match="No LLM provider configured"):
        lc.get_llm_model(None)


def test_create_llm_client_uses_correct_base_url_and_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gk_secret")
    client = lc.create_llm_client("gemini")
    assert client.base_url is not None
    assert str(client.base_url).rstrip("/") == lc.GEMINI_BASE_URL.rstrip("/")
    assert client.api_key == "gk_secret"


def test_create_llm_client_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "ork_secret")
    client = lc.create_llm_client("openrouter")
    assert str(client.base_url).rstrip("/") == lc.OPENROUTER_BASE_URL.rstrip("/")
    assert client.api_key == "ork_secret"


def test_create_llm_client_no_provider_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="GROQ_API_KEY|GEMINI_API_KEY|OPENROUTER_API_KEY"):
        lc.create_llm_client(None)
