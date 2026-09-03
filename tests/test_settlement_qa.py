"""Settlement Q&A tests."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from src.agent.settlement_qa import (
    _build_qa_user_payload,
    answer_free_text,
    answer_pending_query,
    answer_preset,
    parse_amount_candidates,
    parse_question_date,
    raise_support_ticket,
    route_free_text,
    sanitize_question,
    unwrap_model_answer,
    validate_citations,
    validate_question_input,
)
from src.connectors.loaders import attach_lines_to_batches, load_recon_json, load_settlements_json
from src.domain.models import PendingPayment
from src.engine import ReconciliationEngine


@pytest.fixture
def batches(tmp_path: Path):
    from data.synthetic.generator import generate_demo_dataset

    generate_demo_dataset(tmp_path, repo_root=tmp_path)
    recon = load_recon_json(tmp_path / "recon.json")
    headers = load_settlements_json(tmp_path / "settlements.json")
    attached = attach_lines_to_batches(headers, recon)
    return {b.settlement_id: b for b in attached}


def test_preset_where_cites_settlement(batches):
    ans = answer_preset("where_is_settlement", "setl_merchant_d2c_000", batches)
    assert not ans.abstained
    assert "setl_merchant_d2c_000" in ans.citations
    assert "UTR" in ans.answer_text


def test_preset_breakdown_fees(batches):
    ans = answer_preset("breakdown_fees", "setl_merchant_d2c_000", batches)
    assert not ans.abstained
    assert any(c.startswith("pay_") for c in ans.citations)


def test_free_text_fee_question(batches):
    ans = answer_free_text("What are the fees and GST?", "setl_merchant_d2c_000", batches)
    assert not ans.abstained
    assert "fee" in ans.answer_text.lower() or "gst" in ans.answer_text.lower()


def test_abstention_unknown_settlement(batches):
    ans = answer_preset("where_is_settlement", "setl_does_not_exist", batches)
    assert ans.abstained


def test_abstention_unknown_utr(batches):
    ans = answer_free_text("Where is UTR UTR99999999999UNKNOWN?", None, batches)
    assert ans.abstained


def test_entity_lookup(batches):
    ans = answer_free_text("fee on pay_setl_tax_mismatch_0", "setl_tax_mismatch", batches)
    assert not ans.abstained
    assert "pay_setl_tax_mismatch_0" in ans.citations


def test_citation_validator(batches):
    assert validate_citations(["setl_merchant_d2c_000"], batches) == []
    assert validate_citations(["pay_fake_id"], batches) == ["pay_fake_id"]


def test_question_validation():
    assert validate_question_input("")[0] is False
    assert validate_question_input("x" * 600)[0] is False
    assert validate_question_input("valid question")[0] is True


def test_sanitize_strips_null():
    assert "\x00" not in sanitize_question("hello\x00world")


def test_parse_amount_variants():
    assert 4420000 in parse_amount_candidates("give me the details of 4420000 settlement.")
    assert parse_amount_candidates("give me the details of 4420000 paise settlement.") == [4420000]
    assert parse_amount_candidates("give me the details of 44,20000 paise settlement.") == [4420000]
    assert parse_amount_candidates("give me the details of 44,200.00 ruppees settlement.") == [4420000]


def test_parse_23_aug_date():
    parsed = parse_question_date("give me the details of 23 aug settlement")
    assert parsed is not None
    assert parsed.day == 23 and parsed.month == 8


def test_amount_lookup_finds_orphan_settlement(batches):
    ans = answer_free_text(
        "give me the details of 4420000 settlement.",
        "setl_merchant_d2c_000",
        batches,
        use_llm=False,
    )
    assert not ans.abstained
    assert "setl_orphan_header_drift" in ans.answer_text
    assert "pay_setl_orphan_header_drift_0" in ans.answer_text


def test_date_lookup_keyword_fallback(batches):
    question = "what is the details of 23 aug settlement?"
    assert route_free_text(question, "setl_merchant_d2c_000") == "lookup"
    ans = answer_free_text(
        question,
        "setl_merchant_d2c_000",
        batches,
        use_llm=False,
    )
    assert not ans.abstained
    assert "setl_orphan_header_drift" in ans.answer_text


def test_llm_payload_includes_related_matches_after_wrong_selection(batches):
    """Reload selects another settlement — the model must still see 23 Aug."""
    payload = _build_qa_user_payload(
        "what is the details of 23 aug settlement?",
        "setl_merchant_d2c_000",
        batches,
    )
    assert payload["selected_settlement_id"] == "setl_merchant_d2c_000"
    assert payload["evidence"]["settlement"]["settlement_id"] == "setl_merchant_d2c_000"
    related_ids = [
        card["settlement"]["settlement_id"]
        for card in payload.get("related_matches", [])
        if "settlement" in card
    ]
    assert "setl_orphan_header_drift" in related_ids


def test_unwrap_json_answer_text():
    raw = (
        '{"answer_text": "The settlement setl_orphan_header_drift processed on '
        '2026-08-23 has a total amount of ₹44,200.00.", "citations": ["setl_orphan_header_drift"]}'
    )
    assert unwrap_model_answer(raw).startswith("The settlement setl_orphan_header_drift")
    assert "{" not in unwrap_model_answer(raw)


def test_unknown_amount_shows_nearby_payments(batches):
    ans = answer_free_text(
        "give me the details of 999999999 paise settlement",
        "setl_merchant_d2c_000",
        batches,
        use_llm=False,
    )
    assert not ans.abstained
    assert "Closest items" in ans.answer_text
    assert "pay_" in ans.answer_text


def test_raise_ticket_offers_button(batches):
    from src.controls.engine import compose_settlement_integrity_decision, validate_batch_integrity, validate_tax_lines

    decision = compose_settlement_integrity_decision(
        batches["setl_tax_mismatch"],
        validate_batch_integrity(batches["setl_tax_mismatch"]),
        validate_tax_lines(batches["setl_tax_mismatch"]),
    )
    ans = answer_free_text(
        "please raise the ticket",
        "setl_tax_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
    )
    assert ans.offer_raise_ticket
    assert not ans.escalated_to_support
    assert "Raise ticket with Razorpay support" in ans.answer_text


def _needs_attention_decision(batches, settlement_id: str):
    from src.controls.engine import (
        compose_settlement_integrity_decision,
        validate_batch_integrity,
        validate_tax_lines,
    )

    batch = batches[settlement_id]
    return compose_settlement_integrity_decision(
        batch, validate_batch_integrity(batch), validate_tax_lines(batch)
    )


@pytest.mark.parametrize(
    "question",
    [
        "give me the details of 4420000 settlement.",
        "give me the details of 4420000 paise settlement.",
        "give me the details of 44,20000 paise settlement.",
        "give me the details of 44,200.00 ruppees settlement.",
    ],
)
def test_amount_phrasings_all_reach_the_same_settlement(batches, question):
    """₹44,200.00 written four ways is one settlement, not an abstention."""
    ans = answer_free_text(question, "setl_merchant_d2c_000", batches, use_llm=False)
    assert not ans.abstained
    assert "setl_orphan_header_drift" in ans.answer_text


def test_date_lookup_is_stable_whichever_settlement_is_selected(batches):
    """A page reload changes the selection; the answer must not change with it."""
    answers = {
        answer_free_text(
            "give me the details of 23 aug settlement", sid, batches, use_llm=False
        ).answer_text
        for sid in ("setl_merchant_d2c_000", "setl_messy_saas", "setl_orphan_header_drift")
    }
    assert len(answers) == 1
    assert "setl_orphan_header_drift" in answers.pop()


def test_nearest_payments_stay_within_this_merchants_data(batches):
    ans = answer_free_text(
        "give me the details of 777777 paise settlement", "setl_merchant_d2c_000", batches, use_llm=False
    )
    assert not ans.abstained
    assert "Closest items" in ans.answer_text
    known = {l.entity_id for b in batches.values() for l in b.lines} | set(batches)
    assert ans.citations and all(cite in known for cite in ans.citations)


def test_search_by_amount_orders_nearest_by_distance(batches):
    from src.agent.evidence import SettlementEvidenceTools

    found = SettlementEvidenceTools(batches).search_by_amount(4420000)
    assert [h["settlement_id"] for h in found["settlements_exact"]] == ["setl_orphan_header_drift"]
    deltas = [h["delta_paise"] for h in found["nearest"]]
    assert deltas == sorted(deltas)
    assert all(d > 0 for d in deltas)


def test_nearest_prefers_the_payment_when_a_settlement_ties_it(batches):
    """Same distance means the merchant sees the payment line, not just the header."""
    from src.agent.evidence import SettlementEvidenceTools

    batch = batches["setl_orphan_header_drift"]
    target = batch.lines[0].amount + 1  # one paise off every line and header
    found = SettlementEvidenceTools({"setl_orphan_header_drift": batch}).search_by_amount(target)
    tied = [h for h in found["nearest"] if h["delta_paise"] == found["nearest"][0]["delta_paise"]]
    assert tied[0]["kind"] == "payment"


def test_search_by_date_ignores_year_when_the_merchant_omits_it(batches):
    from src.agent.evidence import SettlementEvidenceTools

    tools = SettlementEvidenceTools(batches)
    assert [m["settlement_id"] for m in tools.search_by_date(8, 23)["matches"]] == [
        "setl_orphan_header_drift"
    ]
    assert tools.search_by_date(8, 23, 1999)["matches"] == []


@pytest.mark.parametrize(
    "question",
    [
        "file a ticket",
        "create a ticket",
        "open a case with razorpay",
        "lodge a complaint",
        "please raise this ticket",
        "contact support",
        "escalate it",
    ],
)
def test_natural_ticket_phrasings_offer_the_button(batches, question):
    decision = _needs_attention_decision(batches, "setl_tax_mismatch")
    ans = answer_free_text(
        question, "setl_tax_mismatch", batches, use_llm=False, settlement_decision=decision
    )
    assert ans.offer_raise_ticket, question


@pytest.mark.parametrize("question", ["yes", "go ahead", "do it", "raise it"])
def test_short_confirmation_only_escalates_after_we_offered(batches, question):
    decision = _needs_attention_decision(batches, "setl_tax_mismatch")
    kwargs = dict(batches=batches, use_llm=False, settlement_decision=decision)
    assert answer_free_text(
        question, "setl_tax_mismatch", ticket_offer_pending=True, **kwargs
    ).offer_raise_ticket
    assert not answer_free_text(
        question, "setl_tax_mismatch", ticket_offer_pending=False, **kwargs
    ).offer_raise_ticket


def test_asking_whether_a_settlement_is_verified_is_not_a_refusal(batches):
    """"verified" as a bare substring used to trip the prompt-injection guard."""
    assert route_free_text("is this settlement verified?", "setl_merchant_d2c_000") != "refuse"
    ans = answer_free_text(
        "is this settlement verified?", "setl_merchant_d2c_000", batches, use_llm=False
    )
    assert "cannot change verification status" not in ans.answer_text


def test_already_raised_ticket_stops_offering_the_button(batches):
    decision = _needs_attention_decision(batches, "setl_tax_mismatch")
    ans = answer_free_text(
        "raise the ticket",
        "setl_tax_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
        raised_ticket_id="RZP-SUP-setl_tax_mismatch-abcd",
    )
    assert not ans.offer_raise_ticket
    assert "RZP-SUP-setl_tax_mismatch-abcd" in ans.answer_text


def test_guidance_offers_compensation_choice_for_a_clean_shortfall(batches):
    """setl_batch_mismatch: header exceeds recon net by a clean, provable amount."""
    decision = _needs_attention_decision(batches, "setl_batch_mismatch")
    ans = answer_free_text(
        "what should i do about this",
        "setl_batch_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
    )
    assert ans.triage_verdict == "AUTO_COMPENSABLE"
    assert ans.offer_compensation
    assert ans.offer_raise_ticket
    assert ans.compensation_amount_display


def test_needs_support_settlement_never_offers_compensation(batches):
    """setl_tax_mismatch has no clean settlement-level delta — ticket only, ever."""
    decision = _needs_attention_decision(batches, "setl_tax_mismatch")
    ans = answer_free_text(
        "what should i do about this",
        "setl_tax_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
    )
    assert ans.triage_verdict == "NEEDS_SUPPORT"
    assert not ans.offer_compensation
    assert ans.offer_raise_ticket


def test_compensate_confirmation_files_a_claim(batches):
    decision = _needs_attention_decision(batches, "setl_batch_mismatch")
    ans = answer_free_text(
        "please submit the compensation claim",
        "setl_batch_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
    )
    assert ans.compensation_claim_id
    assert ans.triage_verdict == "AUTO_COMPENSABLE"
    assert not ans.escalated_to_support


def test_escalating_a_compensable_settlement_never_files_a_claim(batches):
    """The merchant can still choose support even when a claim was possible."""
    decision = _needs_attention_decision(batches, "setl_batch_mismatch")
    ans = answer_free_text(
        "raise this to razorpay support",
        "setl_batch_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
    )
    assert ans.offer_raise_ticket
    assert not ans.compensation_claim_id


def test_ambiguous_yes_with_both_offers_pending_asks_to_clarify(batches):
    """Two choices were offered — a bare 'yes' must not silently pick one."""
    decision = _needs_attention_decision(batches, "setl_batch_mismatch")
    ans = answer_free_text(
        "yes",
        "setl_batch_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
        ticket_offer_pending=True,
        compensation_offer_pending=True,
    )
    assert not ans.compensation_claim_id
    assert not ans.escalated_to_support
    assert ans.offer_compensation and ans.offer_raise_ticket


def test_yes_with_only_ticket_pending_still_escalates(batches):
    """A single-choice offer keeps its old one-word confirmation behavior."""
    decision = _needs_attention_decision(batches, "setl_tax_mismatch")
    ans = answer_free_text(
        "yes",
        "setl_tax_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
        ticket_offer_pending=True,
    )
    assert ans.offer_raise_ticket


def test_already_filed_claim_stops_reoffering(batches):
    decision = _needs_attention_decision(batches, "setl_batch_mismatch")
    first = answer_free_text(
        "submit the claim", "setl_batch_mismatch", batches, use_llm=False, settlement_decision=decision
    )
    again = answer_free_text(
        "submit the claim",
        "setl_batch_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
        raised_claim_id=first.compensation_claim_id,
    )
    assert again.compensation_claim_id == first.compensation_claim_id
    assert not again.offer_compensation


def test_claim_id_is_stable_regardless_of_question_phrasing(batches):
    """Idempotency is keyed to the exception's facts, not the exact words used."""
    decision = _needs_attention_decision(batches, "setl_batch_mismatch")
    a = answer_free_text(
        "please compensate me", "setl_batch_mismatch", batches, use_llm=False, settlement_decision=decision
    )
    b = answer_free_text(
        "go ahead and file the claim",
        "setl_batch_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
    )
    assert a.compensation_claim_id == b.compensation_claim_id


@pytest.mark.parametrize(
    "question",
    [
        "I haven't received the money in my bank",
        "the bank says they didn't receive the payment",
        "money hasn't reached my bank account",
        "no bank credit for this settlement",
        "not credited to my bank account",
        "where is my money",
    ],
)
def test_bank_non_receipt_phrasings_route_correctly(question):
    assert route_free_text(question, "setl_merchant_d2c_000") == "bank_non_receipt"


def test_curly_apostrophe_from_phone_keyboards_still_routes_correctly():
    """Browser autocorrect / mobile keyboards send ’, not a straight '."""
    q = sanitize_question("I haven’t received the money in my bank")
    assert route_free_text(q, "setl_merchant_d2c_000") == "bank_non_receipt"


def test_bank_non_receipt_escalates_even_on_a_fully_verified_settlement(batches):
    """This can never be confirmed or ruled out from settlement/recon data alone —
    it must escalate regardless of whether every control on the settlement passes."""
    decision = _needs_attention_decision(batches, "setl_merchant_d2c_000")
    ans = answer_free_text(
        "I haven't received the money in my bank even after 3 days",
        "setl_merchant_d2c_000",
        batches,
        use_llm=False,
        settlement_decision=decision,
    )
    assert ans.offer_raise_ticket
    assert not ans.escalated_to_support
    assert "bank statement" in ans.answer_text.lower()


def test_bank_non_receipt_also_works_on_a_flagged_settlement(batches):
    decision = _needs_attention_decision(batches, "setl_tax_mismatch")
    ans = answer_free_text(
        "the bank says they didn't receive the payment",
        "setl_tax_mismatch",
        batches,
        use_llm=False,
        settlement_decision=decision,
    )
    assert ans.offer_raise_ticket


def test_bank_non_receipt_without_a_settlement_selected_asks_for_one():
    ans = answer_free_text("I haven't received the money in my bank", None, {}, use_llm=False)
    assert ans.abstained
    assert not ans.offer_raise_ticket


def test_bank_non_receipt_ticket_never_fabricates_a_calc_breakdown(batches):
    """A verified settlement has no failed control — the ticket text must say so plainly,
    never invent an 'issue' or calculation it doesn't have."""
    decision = _needs_attention_decision(batches, "setl_merchant_d2c_000")
    ticket = raise_support_ticket("setl_merchant_d2c_000", decision, batches)
    assert "Calculation breakdown" not in ticket.answer_text
    assert "bank transfer status" in ticket.answer_text.lower()


def test_already_raised_bank_non_receipt_ticket_stops_reoffering(batches):
    decision = _needs_attention_decision(batches, "setl_merchant_d2c_000")
    ans = answer_free_text(
        "I haven't received the money in my bank",
        "setl_merchant_d2c_000",
        batches,
        use_llm=False,
        settlement_decision=decision,
        raised_ticket_id="RZP-SUP-setl_merchant_d2c_000-abcd",
    )
    assert not ans.offer_raise_ticket
    assert "RZP-SUP-setl_merchant_d2c_000-abcd" in ans.answer_text


def test_no_exact_match_never_goes_to_the_model(batches):
    """The closest-items list is ranked data; a model rephrasing it loses entries."""
    from unittest.mock import MagicMock, patch

    client = MagicMock()
    with patch("src.agent.settlement_qa.create_llm_client", return_value=client), patch(
        "src.agent.settlement_qa.should_use_llm", return_value=True
    ), patch("src.agent.settlement_qa.iter_llm_providers", return_value=iter(["groq"])):
        ans = answer_free_text(
            "give me the details of 777777 paise settlement",
            "setl_merchant_d2c_000",
            batches,
            use_llm=True,
        )
    client.chat.completions.create.assert_not_called()
    assert ans.agent_mode == "keyword"
    assert "Closest items" in ans.answer_text
    assert ans.answer_text.count("\n- ") >= 3


def _pending(**overrides):
    defaults = dict(
        entity_id="pay_pending_000",
        order_id="ord_pending_0",
        amount=49900,
        captured_at=datetime(2026, 8, 20, 10, 0, 0),
        cycle_type="standard",
        instant_eligible="unknown",
        expected_settlement_at=date(2026, 8, 22),
    )
    defaults.update(overrides)
    return PendingPayment(**defaults)


def test_pending_query_where_is_my_money_gives_expected_date():
    payment = _pending()
    ans = answer_pending_query(payment, "where is my money")
    assert not ans.abstained
    assert "not yet been settled" in ans.answer_text or "not settled" in ans.answer_text
    assert "22" in ans.answer_text or "Aug" in ans.answer_text
    assert ans.citations == ["pay_pending_000"]


def test_pending_query_instant_eligible_yes():
    payment = _pending(instant_eligible="yes", cycle_type="instant_eligible")
    ans = answer_pending_query(payment, "can I get this instantly?")
    assert not ans.abstained
    assert "eligible" in ans.answer_text.lower()


def test_pending_query_instant_eligible_no_falls_back_to_standard_date():
    payment = _pending(instant_eligible="no")
    ans = answer_pending_query(payment, "I need this same day")
    assert not ans.abstained
    assert "not eligible" in ans.answer_text.lower() or "isn't eligible" in ans.answer_text.lower()
    assert "22" in ans.answer_text or "Aug" in ans.answer_text


def test_pending_query_instant_eligible_unknown_abstains_honestly():
    payment = _pending(instant_eligible="unknown")
    ans = answer_pending_query(payment, "is this eligible for instant settlement now?")
    assert ans.abstained
    assert "can't confirm" in ans.answer_text.lower()


def test_pending_query_never_crashes_without_expected_date():
    payment = _pending(expected_settlement_at=None)
    ans = answer_pending_query(payment, "when will I get paid")
    assert isinstance(ans.answer_text, str)
    assert ans.answer_text
