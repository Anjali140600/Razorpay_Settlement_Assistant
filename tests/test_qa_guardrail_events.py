"""Guardrail catches must be countable, not inferred from prose traces."""

from __future__ import annotations

from src.agent.settlement_qa import (
    clear_guardrail_events,
    last_guardrail_events,
    record_guardrail_event,
)


def test_events_start_empty():
    clear_guardrail_events()
    assert last_guardrail_events() == []


def test_event_recorded_with_category_and_detail():
    clear_guardrail_events()
    record_guardrail_event("wrong_amount", "quoted amounts not present in your data")
    assert last_guardrail_events() == [
        {"category": "wrong_amount", "detail": "quoted amounts not present in your data"}
    ]


def test_events_accumulate_in_order():
    clear_guardrail_events()
    record_guardrail_event("bad_citation", "cited unknown id setl_nope")
    record_guardrail_event("wrong_amount", "quoted ₹999.00")
    assert [e["category"] for e in last_guardrail_events()] == ["bad_citation", "wrong_amount"]


def test_clear_resets_between_questions():
    record_guardrail_event("abstained", "no evidence")
    clear_guardrail_events()
    assert last_guardrail_events() == []


def test_returned_list_is_a_copy_not_the_live_store():
    clear_guardrail_events()
    record_guardrail_event("no_answer", "model returned only reasoning")
    got = last_guardrail_events()
    got.append({"category": "forged", "detail": "x"})
    assert len(last_guardrail_events()) == 1


def test_unknown_category_rejected():
    import pytest

    with pytest.raises(ValueError, match="vibes"):
        record_guardrail_event("vibes", "nope")
