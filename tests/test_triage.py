"""Triage classifier — every verdict/reason pair, built from first principles."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.agent.triage import TriageReason, TriageVerdict, classify
from src.connectors.loaders import attach_lines_to_batches, load_recon_json, load_settlements_json
from src.controls.engine import compose_settlement_integrity_decision, validate_batch_integrity, validate_tax_lines
from src.domain.models import SettlementBatch, SettlementLine
from src.domain.razorpay_contract import expected_tax_paise

PROC = datetime(2026, 8, 12, 10, 0, 0)
LATER = datetime(2026, 8, 20, 10, 0, 0)
EARLIER = datetime(2026, 8, 1, 10, 0, 0)


def payment_line(sid: str, entity_id: str, amount: int, fee: int = 0, tax: int = 0) -> SettlementLine:
    return SettlementLine(
        entity_id=entity_id,
        line_type="payment",
        debit=0,
        credit=amount - fee,
        amount=amount,
        fee=fee,
        tax=tax,
        settlement_id=sid,
        created_at=PROC,
        settled_at=PROC,
    )


def adjustment_line(sid_owner: str, entity_id: str, credit: int, **kw) -> SettlementLine:
    base = dict(
        entity_id=entity_id,
        line_type="adjustment",
        debit=0,
        credit=credit,
        amount=credit,
        fee=0,
        tax=0,
        settlement_id=sid_owner,
        settled_at=LATER,
        description="",
    )
    base.update(kw)
    return SettlementLine(**base)


def batch(sid: str, amount: int, lines: list[SettlementLine], status: str = "processed") -> SettlementBatch:
    return SettlementBatch(settlement_id=sid, amount=amount, utr=f"UTR{sid}", status=status, processed_at=PROC, lines=lines)


def decision_for(b: SettlementBatch):
    return compose_settlement_integrity_decision(b, validate_batch_integrity(b), validate_tax_lines(b))


@pytest.fixture
def demo_dataset_batches():
    root = Path(__file__).resolve().parent.parent
    recon = load_recon_json(root / "data" / "synthetic" / "demo" / "recon.json")
    headers = load_settlements_json(root / "data" / "synthetic" / "demo" / "settlements.json")
    return {b.settlement_id: b for b in attach_lines_to_batches(headers, recon)}


def test_verified_settlement_is_no_issue():
    lines = [payment_line("setl_ok", "pay_1", 10000)]
    b = batch("setl_ok", 10000, lines)
    result = classify("setl_ok", b, decision_for(b), {"setl_ok": b})
    assert result.verdict == TriageVerdict.NO_ISSUE
    assert result.reason == TriageReason.NONE


def test_clean_positive_delta_is_auto_compensable():
    """Header bigger than lines net: the merchant is short, and it's provable to the paise."""
    lines = [payment_line("setl_short", "pay_1", 10000)]
    b = batch("setl_short", 10000 + 5000, lines)  # header 15000, lines net 10000
    result = classify("setl_short", b, decision_for(b), {"setl_short": b})
    assert result.verdict == TriageVerdict.AUTO_COMPENSABLE
    assert result.reason == TriageReason.CLEAN_SHORTFALL
    assert result.delta_paise == 5000
    assert result.exception_id


def test_negative_delta_is_over_settlement_recovery_not_compensable():
    """Lines net bigger than header: merchant received extra — Razorpay's recovery, not a claim."""
    lines = [payment_line("setl_over", "pay_1", 10000)]
    b = batch("setl_over", 10000 - 3000, lines)  # header 7000, lines net 10000
    result = classify("setl_over", b, decision_for(b), {"setl_over": b})
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.OVER_SETTLEMENT_RECOVERY


def test_settlement_failed_needs_support():
    lines = [payment_line("setl_failed", "pay_1", 10000)]
    b = batch("setl_failed", 10000, lines, status="failed")
    result = classify("setl_failed", b, decision_for(b), {"setl_failed": b})
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.SETTLEMENT_FAILED


def test_empty_recon_lines_never_auto_compensable():
    b = batch("setl_empty", 5000, [])
    result = classify("setl_empty", b, decision_for(b), {"setl_empty": b})
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.NO_CLEAN_DELTA


def test_tax_only_failure_needs_support():
    lines = [payment_line("setl_tax", "pay_1", 10000, fee=200, tax=999)]  # wrong GST
    b = batch("setl_tax", 10000 - 200, lines)  # header matches net so batch_integrity passes
    result = classify("setl_tax", b, decision_for(b), {"setl_tax": b})
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.TAX_LINE_FAILURE


def test_combined_batch_and_tax_failure_needs_support():
    lines = [payment_line("setl_multi", "pay_1", 10000, fee=200, tax=999)]
    b = batch("setl_multi", 10000 - 200 + 5000, lines)  # header off AND tax wrong
    result = classify("setl_multi", b, decision_for(b), {"setl_multi": b})
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.MULTI_CONTROL_FAILURE


def test_semantic_line_error_is_not_auto_compensable():
    """Payment credit != amount - fee trips both checks at once here (both compare credit) —
    it must never fall through to AUTO_COMPENSABLE regardless of which reason wins."""
    bad = payment_line("setl_sem", "pay_1", 10000, fee=200, tax=expected_tax_paise(200))
    bad.credit = 9700  # should be 9800
    b = batch("setl_sem", bad.credit, [bad])  # header matches the (wrong) line so only semantics fail
    result = classify("setl_sem", b, decision_for(b), {"setl_sem": b})
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.MULTI_CONTROL_FAILURE


def test_already_compensated_by_a_clean_adjustment():
    lines = [payment_line("setl_paid", "pay_1", 10000)]
    b = batch("setl_paid", 10000 + 2000, lines)
    adj = adjustment_line(
        "setl_other_batch", "adj_1", 2000,
        reference_settlement_id="setl_paid", settled_at=LATER,
        description="Recon correction for setl_paid",
    )
    adj_batch = batch("setl_other_batch", 2000, [adj])
    all_batches = {"setl_paid": b, "setl_other_batch": adj_batch}
    result = classify("setl_paid", b, decision_for(b), all_batches)
    assert result.verdict == TriageVerdict.ALREADY_COMPENSATED
    assert result.matched_adjustment_id == "adj_1"


def test_ambiguous_when_two_adjustments_cleanly_match_the_same_shortfall():
    lines = [payment_line("setl_amb", "pay_1", 10000)]
    b = batch("setl_amb", 10000 + 2000, lines)
    adj1 = adjustment_line(
        "carrier1", "adj_1", 2000, reference_settlement_id="setl_amb", settled_at=LATER, description=""
    )
    adj2 = adjustment_line(
        "carrier2", "adj_2", 2000, reference_settlement_id="setl_amb", settled_at=LATER, description=""
    )
    all_batches = {
        "setl_amb": b,
        "carrier1": batch("carrier1", 2000, [adj1]),
        "carrier2": batch("carrier2", 2000, [adj2]),
    }
    result = classify("setl_amb", b, decision_for(b), all_batches)
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.AMBIGUOUS_MATCH


def test_attempted_adjustment_that_does_not_cleanly_reconcile():
    """An adjustment names this settlement but the amount is off — needs a human, not an auto-claim."""
    lines = [payment_line("setl_near", "pay_1", 10000)]
    b = batch("setl_near", 10000 + 2000, lines)
    adj = adjustment_line(
        "carrier", "adj_1", 1999,  # one paise short of the real delta
        reference_settlement_id="setl_near", settled_at=LATER, description="",
    )
    all_batches = {"setl_near": b, "carrier": batch("carrier", 1999, [adj])}
    result = classify("setl_near", b, decision_for(b), all_batches)
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.ATTEMPTED_ADJUSTMENT_UNRECONCILED
    assert result.matched_adjustment_id == "adj_1"


def test_unrelated_adjustments_elsewhere_do_not_block_auto_compensable():
    lines = [payment_line("setl_clean", "pay_1", 10000)]
    b = batch("setl_clean", 10000 + 2000, lines)
    unrelated = adjustment_line(
        "other", "adj_unrelated", 500, reference_settlement_id="setl_someone_else", settled_at=LATER
    )
    all_batches = {"setl_clean": b, "other": batch("other", 500, [unrelated])}
    result = classify("setl_clean", b, decision_for(b), all_batches)
    assert result.verdict == TriageVerdict.AUTO_COMPENSABLE


DEMO_TRIAGE_EXPECTATIONS = {
    "setl_tax_mismatch": (TriageVerdict.NEEDS_SUPPORT, TriageReason.TAX_LINE_FAILURE),
    "setl_batch_mismatch": (TriageVerdict.AUTO_COMPENSABLE, TriageReason.CLEAN_SHORTFALL),
    "setl_fee_semantic_error": (TriageVerdict.NEEDS_SUPPORT, TriageReason.MULTI_CONTROL_FAILURE),
    "setl_refund_wrong_amount": (TriageVerdict.NEEDS_SUPPORT, TriageReason.TAX_LINE_FAILURE),
    "setl_transfer_tax_wrong": (TriageVerdict.NEEDS_SUPPORT, TriageReason.TAX_LINE_FAILURE),
    "setl_orphan_header_drift": (TriageVerdict.AUTO_COMPENSABLE, TriageReason.CLEAN_SHORTFALL),
    "setl_short_compensated": (TriageVerdict.ALREADY_COMPENSATED, TriageReason.BOUND_ADJUSTMENT),
    "setl_ambiguous_shortfall": (TriageVerdict.NEEDS_SUPPORT, TriageReason.AMBIGUOUS_MATCH),
    "setl_unreconciled_shortfall": (TriageVerdict.NEEDS_SUPPORT, TriageReason.ATTEMPTED_ADJUSTMENT_UNRECONCILED),
    "setl_over_settled": (TriageVerdict.NEEDS_SUPPORT, TriageReason.OVER_SETTLEMENT_RECOVERY),
    "setl_no_recon_lines": (TriageVerdict.NEEDS_SUPPORT, TriageReason.NO_CLEAN_DELTA),
}


@pytest.mark.parametrize("settlement_id,expected", DEMO_TRIAGE_EXPECTATIONS.items())
def test_ui_demo_dataset_covers_every_triage_scenario(settlement_id, expected, demo_dataset_batches):
    """Every triage verdict/reason must be reachable by clicking through the demo UI,
    not only in these hand-built fixtures — this is the contract that keeps them in sync."""
    batch = demo_dataset_batches[settlement_id]
    decision = decision_for(batch)
    result = classify(settlement_id, batch, decision, demo_dataset_batches)
    assert (result.verdict, result.reason) == expected


def test_adjustment_before_the_exception_does_not_count_as_evidence():
    lines = [payment_line("setl_order", "pay_1", 10000)]
    b = batch("setl_order", 10000 + 2000, lines)
    early_adj = adjustment_line(
        "carrier", "adj_1", 2000, reference_settlement_id="setl_order", settled_at=EARLIER
    )
    all_batches = {"setl_order": b, "carrier": batch("carrier", 2000, [early_adj])}
    result = classify("setl_order", b, decision_for(b), all_batches)
    # Ordering fails (P4) but reference resolves (P5 holds) -> attempted, not silently auto-compensable.
    assert result.verdict == TriageVerdict.NEEDS_SUPPORT
    assert result.reason == TriageReason.ATTEMPTED_ADJUSTMENT_UNRECONCILED
