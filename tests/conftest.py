"""Shared test setup."""

from __future__ import annotations

import pytest

from src.agent.settlement_qa import clear_guardrail_events, clear_llm_answer_cache


@pytest.fixture(autouse=True)
def _clear_llm_answer_cache():
    """The LLM answer cache and guardrail log are process-wide; they must not leak."""
    clear_llm_answer_cache()
    clear_guardrail_events()
    yield
    clear_llm_answer_cache()
    clear_guardrail_events()
