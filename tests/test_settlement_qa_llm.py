"""Mocked LLM path tests for Settlement Q&A."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agent.settlement_qa import (
    answer_free_text,
    last_llm_error,
    needs_support_ticket,
    raise_support_ticket,
)
from src.connectors.loaders import attach_lines_to_batches, load_recon_json, load_settlements_json
from src.controls.engine import compose_settlement_integrity_decision, validate_batch_integrity, validate_tax_lines
from src.engine import ReconciliationEngine


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    from data.synthetic.generator import generate_demo_dataset

    generate_demo_dataset(tmp_path, repo_root=tmp_path)
    return tmp_path


@pytest.fixture
def batches(demo_dir: Path):
    recon = load_recon_json(demo_dir / "recon.json")
    headers = load_settlements_json(demo_dir / "settlements.json")
    attached = attach_lines_to_batches(headers, recon)
    return {b.settlement_id: b for b in attached}


@pytest.fixture
def tax_decision(batches):
    batch = batches["setl_tax_mismatch"]
    return compose_settlement_integrity_decision(
        batch,
        validate_batch_integrity(batch),
        validate_tax_lines(batch),
    )


def _mock_tool_call(name: str, args: dict, call_id: str = "call_1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _mock_completion(tool_calls=None, content=None):
    msg = SimpleNamespace(tool_calls=tool_calls, content=content)
    msg.model_dump = lambda: {"role": "assistant", "tool_calls": tool_calls}
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    with patch("src.agent.settlement_qa.create_llm_client", return_value=client), patch(
        "src.agent.settlement_qa.iter_llm_providers", return_value=iter(["groq"])
    ), patch("src.agent.settlement_qa.get_llm_model", return_value="test-model"):
        yield client


def test_llm_tool_selection_then_answer(mock_llm_client, batches):
    mock_llm_client.chat.completions.create.side_effect = [
        _mock_completion(
            tool_calls=[_mock_tool_call("explain_fee_tax", {"settlement_id": "setl_tax_mismatch"})]
        ),
        _mock_completion(
            tool_calls=[
                _mock_tool_call(
                    "finish_answer",
                    {
                        "answer_text": "GST issue on pay_setl_tax_mismatch_1.",
                        "citations": ["setl_tax_mismatch", "pay_setl_tax_mismatch_1"],
                        "abstained": False,
                    },
                )
            ]
        ),
    ]
    ans = answer_free_text(
        "Which payment has wrong GST?",
        "setl_tax_mismatch",
        batches,
        use_llm=True,
    )
    assert ans.agent_mode == "groq"
    assert not ans.abstained
    assert "pay_setl_tax_mismatch_1" in ans.citations


def test_llm_payload_separates_recent_conversation_from_evidence(mock_llm_client, batches):
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": "The GST breakdown is available for setl_tax_mismatch.",
                    "citations": ["setl_tax_mismatch"],
                    "abstained": False,
                },
            )
        ]
    )

    answer_free_text(
        "Why?",
        "setl_tax_mismatch",
        batches,
        use_llm=True,
        conversation_context=[
            {"role": "user", "content": "What about the GST?"},
            {"role": "assistant", "content": "The fee line needs attention."},
        ],
        previous_intent="breakdown_fees",
    )

    sent = json.loads(mock_llm_client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
    assert sent["current_question"] == "Why?"
    assert sent["active_subject"] == {"kind": "settlement", "ids": ["setl_tax_mismatch"]}
    assert sent["recent_conversation"][0]["content"] == "What about the GST?"
    assert "evidence" in sent


def test_llm_cache_distinguishes_recent_conversation(mock_llm_client, batches):
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": "Settlement setl_tax_mismatch has a verified explanation.",
                    "citations": ["setl_tax_mismatch"],
                    "abstained": False,
                },
            )
        ]
    )

    # The fixture's one-shot provider iterator is sufficient for normal single-call
    # tests; this regression deliberately performs two uncached generations.
    with patch(
        "src.agent.settlement_qa.iter_llm_providers",
        side_effect=lambda: iter(["groq"]),
    ):
        for prior in ("Explain the GST.", "Explain the settlement status."):
            answer_free_text(
                "Why?",
                "setl_tax_mismatch",
                batches,
                use_llm=True,
                conversation_context=[{"role": "user", "content": prior}],
            )

    assert mock_llm_client.chat.completions.create.call_count == 2


def test_llm_answers_23_aug_from_related_matches(mock_llm_client, batches):
    """After reload the selected settlement is not 23 Aug — the model still sees the match."""
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": (
                        "Settlement setl_orphan_header_drift processed on 23 Aug 2026 "
                        "has net \u20b944,200.00 (UTR UTR20260804444ORP1)."
                    ),
                    "citations": ["setl_orphan_header_drift"],
                    "abstained": False,
                },
            )
        ]
    )
    ans = answer_free_text(
        "what is the details of 23 aug settlement?",
        "setl_merchant_d2c_000",
        batches,
        use_llm=True,
    )
    assert ans.agent_mode == "groq"
    assert not ans.abstained
    assert "setl_orphan_header_drift" in ans.answer_text
    sent = json.loads(mock_llm_client.chat.completions.create.call_args.kwargs["messages"][1]["content"])
    related_ids = [
        card["settlement"]["settlement_id"]
        for card in sent.get("related_matches", [])
        if "settlement" in card
    ]
    assert "setl_orphan_header_drift" in related_ids


def test_llm_hallucinated_citation_abstains(mock_llm_client, batches):
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": "Problem on pay_fake.",
                    "citations": ["pay_fake_id"],
                    "abstained": False,
                },
            )
        ]
    )
    ans = answer_free_text("fee issue?", "setl_tax_mismatch", batches, use_llm=True)
    assert "pay_fake" not in ans.answer_text
    assert ans.agent_mode == "keyword"


def test_groq_fail_gemini_success(batches):
    groq_client = MagicMock()
    groq_client.chat.completions.create.side_effect = RuntimeError("groq down")
    gemini_client = MagicMock()
    gemini_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": "Batch gap explained.",
                    "citations": ["setl_batch_mismatch"],
                    "abstained": False,
                },
            )
        ]
    )

    def fake_create(provider=None):
        if provider == "groq":
            return groq_client
        return gemini_client

    with patch("src.agent.settlement_qa.create_llm_client", side_effect=fake_create), patch(
        "src.agent.settlement_qa.iter_llm_providers", return_value=iter(["groq", "gemini"])
    ), patch("src.agent.settlement_qa.get_llm_model", return_value="test-model"):
        ans = answer_free_text(
            "Why does batch not add up?",
            "setl_batch_mismatch",
            batches,
            use_llm=True,
        )
    assert ans.agent_mode == "gemini"
    assert not ans.abstained


def test_groq_and_gemini_fail_openrouter_success(batches):
    groq_client = MagicMock()
    groq_client.chat.completions.create.side_effect = RuntimeError("groq down")
    gemini_client = MagicMock()
    gemini_client.chat.completions.create.side_effect = RuntimeError("gemini down")
    openrouter_client = MagicMock()
    openrouter_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": "Batch gap explained.",
                    "citations": ["setl_batch_mismatch"],
                    "abstained": False,
                },
            )
        ]
    )

    def fake_create(provider=None):
        if provider == "groq":
            return groq_client
        if provider == "gemini":
            return gemini_client
        return openrouter_client

    with patch("src.agent.settlement_qa.create_llm_client", side_effect=fake_create), patch(
        "src.agent.settlement_qa.iter_llm_providers",
        return_value=iter(["groq", "gemini", "openrouter"]),
    ), patch("src.agent.settlement_qa.get_llm_model", return_value="test-model"):
        ans = answer_free_text(
            "Why does batch not add up?",
            "setl_batch_mismatch",
            batches,
            use_llm=True,
        )
    assert ans.agent_mode == "openrouter"
    assert not ans.abstained


def test_both_llms_fail_keyword_fallback(batches):
    with patch("src.agent.settlement_qa.iter_llm_providers", return_value=iter(["groq"])), patch(
        "src.agent.settlement_qa.create_llm_client", side_effect=RuntimeError("down")
    ):
        ans = answer_free_text(
            "What are the fees and GST?",
            "setl_tax_mismatch",
            batches,
            use_llm=True,
        )
    assert ans.agent_mode == "keyword"
    assert not ans.abstained


def test_reasoning_model_stall_finalizes_in_prose(mock_llm_client, batches):
    """Groq gpt-oss can stop with no tool call and empty content — we still answer."""
    mock_llm_client.chat.completions.create.side_effect = [
        _mock_completion(
            tool_calls=[_mock_tool_call("fetch_settlement", {"settlement_id": "setl_tax_mismatch"})]
        ),
        _mock_completion(tool_calls=None, content=""),
        _mock_completion(
            content="Settlement setl_tax_mismatch shows a GST gap on pay_setl_tax_mismatch_1."
        ),
    ]
    ans = answer_free_text(
        "Explain this settlement in plain English",
        "setl_tax_mismatch",
        batches,
        use_llm=True,
    )
    assert ans.agent_mode == "groq"
    assert not ans.abstained
    assert "setl_tax_mismatch" in ans.citations


def test_step_budget_finalizer_keeps_numeric_guards(mock_llm_client, batches):
    """The loop-exhausted finalizer must not bypass money validation."""
    repeated_tool_call = _mock_completion(
        tool_calls=[_mock_tool_call("fetch_settlement", {"settlement_id": "setl_tax_mismatch"})]
    )
    mock_llm_client.chat.completions.create.side_effect = [
        repeated_tool_call,
        repeated_tool_call,
        repeated_tool_call,
        repeated_tool_call,
        _mock_completion(
            content=(
                "Settlement setl_tax_mismatch has a net amount of ₹5,844.00."
            )
        ),
    ]
    ans = answer_free_text(
        "Explain this settlement",
        "setl_tax_mismatch",
        batches,
        use_llm=True,
    )
    assert ans.agent_mode == "keyword"
    assert "5,844.00" not in ans.answer_text


def test_finalize_rejects_fabricated_ids(mock_llm_client, batches):
    mock_llm_client.chat.completions.create.side_effect = [
        _mock_completion(tool_calls=None, content=""),
        _mock_completion(content="See settlement setl_does_not_exist for details."),
    ]
    ans = answer_free_text("explain", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "keyword"


def test_rate_limit_reports_fallback_reason(batches):
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError(
        "Error code: 429 - rate_limit_exceeded tokens per day"
    )
    with patch("src.agent.settlement_qa.create_llm_client", return_value=client), patch(
        "src.agent.settlement_qa.iter_llm_providers", return_value=iter(["groq"])
    ), patch("src.agent.settlement_qa.get_llm_model", return_value="test-model"):
        ans = answer_free_text("explain", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "keyword"
    assert "daily free-tier token limit" in (last_llm_error() or "")


def test_fabricated_amount_is_rejected(mock_llm_client, batches):
    """Models mis-scale paise (₹58.44 -> ₹5,844.00) — such answers must not reach the merchant."""
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": "GST on this settlement was \u20b95,844.00.",
                    "citations": ["setl_tax_mismatch"],
                    "abstained": False,
                },
            )
        ]
    )
    ans = answer_free_text("What was the GST?", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "keyword"
    assert "5,844.00" not in ans.answer_text
    assert "numeric check" in (last_llm_error() or "")


def test_amounts_from_evidence_are_accepted(mock_llm_client, batches):
    from src.agent.settlement_qa import _preloaded_evidence, money_figures
    import json as _json

    evidence = _json.dumps(_preloaded_evidence("setl_tax_mismatch", batches), ensure_ascii=False)
    real = sorted(money_figures(evidence))[0]
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": f"This settlement shows {real} on setl_tax_mismatch.",
                    "citations": ["setl_tax_mismatch"],
                    "abstained": False,
                },
            )
        ]
    )
    ans = answer_free_text("explain", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "groq"
    assert real in ans.answer_text


def test_wrong_role_amount_is_rejected(mock_llm_client, batches):
    """A real fee figure must not be presented as the settlement net."""
    from src.agent.settlement_qa import _preloaded_evidence

    evidence = _preloaded_evidence("setl_tax_mismatch", batches)
    fee = evidence["batch_check"]["total_fee_display"]
    header = evidence["batch_check"]["header_amount_display"]
    assert fee != header
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": f"The net amount of this settlement is {fee}.",
                    "citations": ["setl_tax_mismatch"],
                    "abstained": False,
                },
            )
        ]
    )
    ans = answer_free_text("What is the net?", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "keyword"
    assert "wrong role" in (last_llm_error() or "")


def test_correct_role_amount_is_accepted(mock_llm_client, batches):
    from src.agent.settlement_qa import _preloaded_evidence

    evidence = _preloaded_evidence("setl_tax_mismatch", batches)
    header = evidence["batch_check"]["header_amount_display"]
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        tool_calls=[
            _mock_tool_call(
                "finish_answer",
                {
                    "answer_text": f"The net amount of settlement setl_tax_mismatch is {header}.",
                    "citations": ["setl_tax_mismatch"],
                    "abstained": False,
                },
            )
        ]
    )
    ans = answer_free_text("What is the net?", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "groq"
    assert header in ans.answer_text


def test_escalation_on_failing_settlement(batches, tax_decision):
    assert needs_support_ticket(tax_decision)
    ans = raise_support_ticket("setl_tax_mismatch", tax_decision, batches)
    assert ans.escalated_to_support
    assert ans.support_ticket_id.startswith("RZP-SUP-setl_tax_mismatch")
    assert "support ticket has been raised" in ans.answer_text.lower()


def test_needs_support_ticket_false_when_verified(batches):
    batch = batches["setl_merchant_d2c_000"]
    decision = compose_settlement_integrity_decision(
        batch,
        validate_batch_integrity(batch),
        validate_tax_lines(batch),
    )
    assert not needs_support_ticket(decision)


def test_what_to_do_guidance(batches, tax_decision):
    ans = answer_free_text(
        "what to do now",
        "setl_tax_mismatch",
        batches,
        use_llm=False,
        settlement_decision=tax_decision,
    )
    assert "Raise ticket with Razorpay support" in ans.answer_text


class _Body(Exception):
    """An OpenAI-SDK-shaped error carrying a provider body."""

    def __init__(self, message: str, body: dict):
        super().__init__(message)
        self.body = body


def test_answer_recovered_from_rejected_tool_call(mock_llm_client, batches):
    """Groq 400s a malformed tool call but returns the text — it is still a good answer."""
    mock_llm_client.chat.completions.create.side_effect = _Body(
        "Error code: 400 - tool_use_failed",
        {
            "error": {
                "code": "tool_use_failed",
                "failed_generation": (
                    "<tool_call>\n<function=finish_answer>\n<parameter=answer_text>\n"
                    "Settlement setl_tax_mismatch has a GST gap on pay_setl_tax_mismatch_1.\n"
                    "</parameter>\n</function>\n</tool_call>"
                ),
            }
        },
    )
    ans = answer_free_text("what is wrong?", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "groq"
    assert not ans.abstained
    assert "pay_setl_tax_mismatch_1" in ans.answer_text
    assert "<parameter" not in ans.answer_text


def test_recovered_answer_still_fails_validation_when_wrong(batches):
    """Recovery is not a bypass — a fabricated id in failed_generation is still rejected."""
    client = MagicMock()
    client.chat.completions.create.side_effect = _Body(
        "Error code: 400 - output_parse_failed",
        {"error": {"code": "output_parse_failed",
                   "failed_generation": '{"answer_text": "See setl_not_real.", "citations": []}'}},
    )
    with patch("src.agent.settlement_qa.create_llm_client", return_value=client), patch(
        "src.agent.settlement_qa.iter_llm_providers", return_value=iter(["groq"])
    ), patch("src.agent.settlement_qa.get_llm_model", return_value="test-model"):
        ans = answer_free_text("explain", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "keyword"
    assert "setl_not_real" not in ans.answer_text
    assert "unknown id" in (last_llm_error() or "")


def test_bare_reasoning_is_not_recovered(batches):
    """failed_generation holding only scratch reasoning must not reach the merchant."""
    client = MagicMock()
    client.chat.completions.create.side_effect = _Body(
        "Error code: 400 - output_parse_failed",
        {"error": {"code": "output_parse_failed",
                   "failed_generation": "We need to answer the user. The evidence shows..."}},
    )
    with patch("src.agent.settlement_qa.create_llm_client", return_value=client), patch(
        "src.agent.settlement_qa.iter_llm_providers", return_value=iter(["groq"])
    ), patch("src.agent.settlement_qa.get_llm_model", return_value="test-model"):
        ans = answer_free_text("explain", "setl_tax_mismatch", batches, use_llm=True)
    assert "We need to answer" not in ans.answer_text
    assert ans.agent_mode == "keyword"


def test_first_turn_sends_no_tool_schemas(mock_llm_client, batches):
    """Evidence is inlined, so the cheap first turn must not pay for tool schemas."""
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        content="Settlement setl_tax_mismatch is short on GST."
    )
    answer_free_text("explain", "setl_tax_mismatch", batches, use_llm=True)
    first = mock_llm_client.chat.completions.create.call_args_list[0].kwargs
    assert "tools" not in first


def test_rejected_answer_reports_why(mock_llm_client, batches):
    """A silent fallback to rules is a bug — the merchant is told what happened."""
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        content="Settlement setl_tax_mismatch paid out ₹9,999,999.00."
    )
    ans = answer_free_text("what was paid?", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "keyword"
    assert "numeric check" in (last_llm_error() or "")


def test_correct_fee_figure_is_not_flagged_as_tax(mock_llm_client, batches):
    """"Total fee: X" after an earlier mention of tax used to be rejected as misattributed."""
    from src.agent.settlement_qa import _preloaded_evidence

    evidence = _preloaded_evidence("setl_tax_mismatch", batches)
    fee = evidence["batch_check"]["total_fee_display"]
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        content=(
            f"Razorpay deducts fees and tax before payout on setl_tax_mismatch. "
            f"Total fee: {fee}."
        )
    )
    ans = answer_free_text("why less?", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "groq", last_llm_error()
    assert fee in ans.answer_text


def test_repeated_question_is_not_paid_for_twice(mock_llm_client, batches):
    """A reload re-asking the same question must not spend the daily token budget again."""
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        content="Settlement setl_tax_mismatch is short on GST."
    )
    first = answer_free_text("explain this", "setl_tax_mismatch", batches, use_llm=True)
    calls_after_first = mock_llm_client.chat.completions.create.call_count
    second = answer_free_text("  Explain   This  ", "setl_tax_mismatch", batches, use_llm=True)
    assert first.answer_text == second.answer_text
    assert mock_llm_client.chat.completions.create.call_count == calls_after_first


def test_model_corrects_itself_when_a_figure_is_rejected(mock_llm_client, batches):
    """A mis-scaled total earns one corrective turn, not a silent drop to rules."""
    from src.agent.settlement_qa import _preloaded_evidence

    fee = _preloaded_evidence("setl_tax_mismatch", batches)["batch_check"]["total_fee_display"]
    mock_llm_client.chat.completions.create.side_effect = [
        _mock_completion(content="Total fees on setl_tax_mismatch were ₹9,999,999.00."),
        _mock_completion(content=f"Total fees on setl_tax_mismatch were {fee}."),
    ]
    ans = answer_free_text("what were the fees?", "setl_tax_mismatch", batches, use_llm=True)
    assert ans.agent_mode == "groq", last_llm_error()
    assert fee in ans.answer_text
    assert "9,999,999" not in ans.answer_text


def test_reasoning_block_never_reaches_the_merchant(mock_llm_client, batches):
    mock_llm_client.chat.completions.create.return_value = _mock_completion(
        content=(
            "<think>\nThe user is asking about setl_tax_mismatch. I should check the batch.\n</think>\n"
            "Settlement setl_tax_mismatch has a GST shortfall."
        )
    )
    ans = answer_free_text("explain", "setl_tax_mismatch", batches, use_llm=True)
    assert "<think>" not in ans.answer_text
    assert "I should check" not in ans.answer_text
    assert "GST shortfall" in ans.answer_text
