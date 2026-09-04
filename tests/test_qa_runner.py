"""Scoring must attribute every answer, or an 'AI' score can be pure keyword fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.connectors.loaders import (
    attach_lines_to_batches,
    load_recon_json,
    load_settlements_json,
)
from src.domain.models import AnswerEnvelope
from src.eval.qa_cases import QaCase
from src.eval.qa_runner import aggregate, allowed_money_for, run_column, score_case


@pytest.fixture
def batches():
    d = Path("data/synthetic/demo")
    lines = load_recon_json(d / "recon.json")
    got = attach_lines_to_batches(load_settlements_json(d / "settlements.json"), lines)
    return {b.settlement_id: b for b in got}


def case(**kw) -> QaCase:
    base = {"case_id": "c1", "class": "answerable", "question": "q"}
    base.update(kw)
    return QaCase.model_validate(base)


def test_answerable_passes_when_cited_by_llm():
    env = AnswerEnvelope(answer_text="Settled.", citations=["setl_a"], agent_mode="groq")
    row = score_case(case(), env, [], set())
    assert row["passed"] is True
    assert row["answered_by"] == "llm"


def test_answerable_fails_without_citation():
    env = AnswerEnvelope(answer_text="Settled.", citations=[], agent_mode="groq")
    assert score_case(case(), env, [], set())["passed"] is False


def test_keyword_answer_attributed_to_rules():
    env = AnswerEnvelope(answer_text="Settled.", citations=["setl_a"], agent_mode="keyword")
    assert score_case(case(), env, [], set())["answered_by"] == "rules"


def test_must_abstain_passes_only_when_abstained():
    c = case(case_id="c2", **{"class": "must_abstain"}, expect_abstain=True,
             expect_citations=False)
    yes = AnswerEnvelope(answer_text="I don't have that.", abstained=True, agent_mode="groq")
    no = AnswerEnvelope(answer_text="It was ₹500.00.", citations=["setl_a"], agent_mode="groq")
    assert score_case(c, yes, [], set())["passed"] is True
    assert score_case(c, no, [], set())["passed"] is False


def test_must_refuse_passes_on_abstention_flag():
    c = case(case_id="c3", **{"class": "must_refuse"}, expect_refuse=True,
             expect_citations=False)
    env = AnswerEnvelope(answer_text="I can only answer about your data.", abstained=True)
    assert score_case(c, env, [], set())["passed"] is True


def test_money_precision_requires_exact_expected_amount():
    c = case(case_id="c4", **{"class": "money_precision"}, expect_amounts=["₹58.44"])
    allowed = {"₹58.44", "₹5844.00"}
    right = AnswerEnvelope(answer_text="GST was ₹58.44.", citations=["setl_a"], agent_mode="groq")
    wrong = AnswerEnvelope(answer_text="GST was ₹5,844.00.", citations=["setl_a"], agent_mode="groq")
    assert score_case(c, right, [], allowed)["passed"] is True
    assert score_case(c, wrong, [], allowed)["passed"] is False


def test_labels_with_commas_match_canonical_answer_forms():
    """Labels are authored naturally; normalisation must bridge the two forms."""
    c = case(case_id="c4b", **{"class": "money_precision"}, expect_amounts=["₹42,640.00"])
    env = AnswerEnvelope(answer_text="The header was ₹42,640.00.", citations=["setl_a"],
                         agent_mode="groq")
    assert score_case(c, env, [], {"₹42640.00"})["passed"] is True


def test_forbidden_amount_fails_even_if_expected_also_present():
    c = case(case_id="c5", **{"class": "money_precision"},
             expect_amounts=["₹58.44"], forbid_amounts=["₹5,844.00"])
    env = AnswerEnvelope(answer_text="GST ₹58.44, or ₹5,844.00 in paise.",
                         citations=["setl_a"], agent_mode="groq")
    assert score_case(c, env, [], {"₹58.44", "₹5844.00"})["passed"] is False


def test_guardrail_events_recorded_on_the_row():
    events = [{"category": "wrong_amount", "detail": "quoted ₹999.00"}]
    row = score_case(case(), AnswerEnvelope(answer_text="x", citations=["setl_a"]),
                     events, set())
    assert row["validator_caught_wrong_amount"] == 1


def test_unverified_amount_is_measured_against_the_tool_derived_set():
    """A figure no tool produced is unverified; other real figures are not."""
    c = case(case_id="c6", **{"class": "money_precision"}, expect_amounts=["₹58.44"])
    allowed = {"₹58.44", "₹370.00"}
    clean = AnswerEnvelope(answer_text="GST ₹58.44 on a fee of ₹370.00.",
                           citations=["setl_a"], agent_mode="groq")
    invented = AnswerEnvelope(answer_text="GST ₹58.44 on a fee of ₹999.00.",
                              citations=["setl_a"], agent_mode="groq")
    assert score_case(c, clean, [], allowed)["unverified_amount_emitted"] is False
    assert score_case(c, invented, [], allowed)["unverified_amount_emitted"] is True


def test_allowed_money_covers_the_settlement_figures(batches):
    allowed = allowed_money_for("setl_batch_mismatch", batches)
    assert "₹42640.00" in allowed   # header
    assert "₹500.00" in allowed     # gap
    assert "₹860.00" in allowed     # total fee


def test_allowed_money_empty_for_unknown_settlement(batches):
    assert allowed_money_for("setl_nope", batches) == set()
    assert allowed_money_for(None, batches) == set()


def test_aggregate_counts_attribution_and_catches():
    rows = [
        {"qa_class": "answerable", "passed": True, "answered_by": "llm",
         "citations_valid": True, "unverified_amount_emitted": False,
         "validator_caught_wrong_amount": 1, "validator_caught_bad_citation": 0},
        {"qa_class": "answerable", "passed": False, "answered_by": "rules",
         "citations_valid": False, "unverified_amount_emitted": True,
         "validator_caught_wrong_amount": 0, "validator_caught_bad_citation": 2},
    ]
    m = aggregate(rows)
    assert m["qa_cases_total"] == 2
    assert m["qa_answered_by_llm"] == 1
    assert m["qa_answered_by_rules"] == 1
    assert m["qa_unverified_amount_emissions"] == 1
    assert m["qa_validator_caught_wrong_amount"] == 1
    assert m["qa_validator_caught_bad_citation"] == 2


def test_deterministic_column_runs_offline(batches):
    """The baseline column must not need a provider."""
    cases = [QaCase.model_validate(
        {"case_id": "d1", "class": "answerable",
         "settlement_id": "setl_merchant_d2c_000", "question": "Where is my settlement?"}
    )]
    rows = run_column(cases, batches, use_llm=False)
    assert rows[0]["answered_by"] == "rules"


def test_ai_column_records_rules_fallback_not_a_false_ai_win(monkeypatch, batches):
    """When the LLM path yields nothing, the row must say 'rules', not 'llm'."""
    import src.agent.settlement_qa as qa

    monkeypatch.setattr(qa, "should_use_llm", lambda: True)
    monkeypatch.setattr(qa, "_react_qa_llm", lambda *a, **k: None)

    cases = [QaCase.model_validate(
        {"case_id": "f1", "class": "answerable",
         "settlement_id": "setl_merchant_d2c_000", "question": "Where is my settlement?"}
    )]
    rows = run_column(cases, batches, use_llm=True)
    assert rows[0]["answered_by"] == "rules"


def test_wrong_amount_from_model_is_caught_and_counted(monkeypatch, batches):
    """A model that invents an amount is caught by the validator, not scored a pass."""
    import src.agent.settlement_qa as qa

    def fake_react(*a, **k):
        qa.record_guardrail_event("wrong_amount", "quoted ₹99999.00")
        return None

    monkeypatch.setattr(qa, "should_use_llm", lambda: True)
    monkeypatch.setattr(qa, "_react_qa_llm", fake_react)

    cases = [QaCase.model_validate(
        {"case_id": "f2", "class": "money_precision",
         "settlement_id": "setl_tax_mismatch",
         "question": "What was the GST?", "expect_amounts": ["₹999,999.00"]}
    )]
    rows = run_column(cases, batches, use_llm=True)
    assert rows[0]["validator_caught_wrong_amount"] == 1
    assert rows[0]["passed"] is False


def test_cited_settlements_widen_the_allowed_set(batches):
    """A lookup answer quoting other settlements' real figures is not inventing money."""
    from src.eval.qa_runner import allowed_money_for_answer

    c = case(case_id="c7", settlement_id="setl_batch_mismatch")
    env = AnswerEnvelope(answer_text="x", citations=["setl_messy_b2b"], agent_mode="keyword")
    allowed = allowed_money_for_answer(c, env, batches)
    assert "₹42640.00" in allowed      # from the case settlement
    assert "₹209720.00" in allowed     # from the cited settlement


def test_cited_payment_line_resolves_through_its_settlement(batches):
    from src.eval.qa_runner import allowed_money_for_answer

    c = case(case_id="c8", settlement_id=None)
    env = AnswerEnvelope(answer_text="x", citations=["pay_setl_messy_b2b_0"],
                         agent_mode="keyword")
    assert "₹209720.00" in allowed_money_for_answer(c, env, batches)


def test_provider_failure_is_recorded_per_case():
    """A rules answer caused by provider exhaustion is not model behaviour."""
    from src.eval.qa_runner import aggregate

    rows = [
        {"qa_class": "answerable", "passed": True, "answered_by": "rules",
         "citations_valid": True, "unverified_amount_emitted": False,
         "validator_caught_wrong_amount": 0, "validator_caught_bad_citation": 0,
         "llm_error": "groq: daily free-tier token limit reached"},
        {"qa_class": "answerable", "passed": True, "answered_by": "llm",
         "citations_valid": True, "unverified_amount_emitted": False,
         "validator_caught_wrong_amount": 0, "validator_caught_bad_citation": 0,
         "llm_error": None},
    ]
    assert aggregate(rows)["qa_llm_unavailable"] == 1


def test_llm_unavailable_defaults_to_zero_when_absent():
    from src.eval.qa_runner import aggregate

    rows = [{"qa_class": "answerable", "passed": True, "answered_by": "llm",
             "citations_valid": True, "unverified_amount_emitted": False,
             "validator_caught_wrong_amount": 0, "validator_caught_bad_citation": 0}]
    assert aggregate(rows)["qa_llm_unavailable"] == 0


def test_delay_is_only_applied_between_llm_cases(monkeypatch, batches):
    """Pacing protects a free-tier rate limit; the offline column must stay fast."""
    import src.eval.qa_runner as runner
    from src.eval.qa_cases import QaCase

    slept: list[float] = []
    monkeypatch.setattr(runner.time, "sleep", lambda s: slept.append(s))

    cases = [QaCase.model_validate(
        {"case_id": f"p{i}", "class": "answerable",
         "settlement_id": "setl_merchant_d2c_000", "question": "Where is my settlement?"}
    ) for i in range(3)]

    runner.run_column(cases, batches, use_llm=False, delay_seconds=5.0)
    assert slept == [], "the deterministic column must never sleep"

    runner.run_column(cases, batches, use_llm=True, delay_seconds=5.0)
    assert slept == [5.0, 5.0], "sleep between cases, not after the last one"
