"""Every predicate must be able to reject a binding on its own."""

from __future__ import annotations

from datetime import datetime

from src.domain.models import SettlementLine
from src.lifecycle.matcher import OpenException, candidate_reasons, match_adjustments

FLAGGED = datetime(2026, 8, 28, 10, 0, 0)
LATER = datetime(2026, 8, 31, 10, 0, 0)


def exc(delta=2000, sid="setl_lc_exact", utr="UTRLC0001", eid="exc_test") -> OpenException:
    return OpenException(
        exception_id=eid,
        settlement_id=sid,
        control_type="batch_integrity",
        delta_paise=delta,
        utr=utr,
        flagged_at=FLAGGED,
    )


def adj(**kw) -> SettlementLine:
    base = dict(
        entity_id="adj_1", line_type="adjustment", debit=0, credit=2000, amount=2000,
        fee=0, tax=0, currency="INR", settlement_id="setl_lc_cycle2",
        reference_settlement_id="setl_lc_exact", settled_at=LATER,
        description="Recon correction for setl_lc_exact",
    )
    base.update(kw)
    return SettlementLine(**base)


def test_clean_candidate_has_no_rejections():
    assert candidate_reasons(exc(), adj(), FLAGGED, LATER) == []


def test_p1_invalid_adjustment_line_rejected():
    reasons = candidate_reasons(exc(), adj(debit=2000, credit=2000), FLAGGED, LATER)
    assert any("invalid adjustment line" in r for r in reasons)


def test_p1_adjustment_with_fee_rejected():
    reasons = candidate_reasons(exc(), adj(fee=100), FLAGGED, LATER)
    assert any("invalid adjustment line" in r for r in reasons)


def test_p2_wrong_direction_rejected():
    """A short settlement needs a credit; a debit cannot compensate it."""
    reasons = candidate_reasons(exc(), adj(debit=2000, credit=0), FLAGGED, LATER)
    assert any("direction" in r for r in reasons)


def test_p2_wrong_currency_rejected():
    reasons = candidate_reasons(exc(), adj(currency="USD"), FLAGGED, LATER)
    assert any("currency" in r for r in reasons)


def test_p3_amount_must_be_exact():
    reasons = candidate_reasons(exc(delta=2000), adj(credit=1999, amount=1999),
                                FLAGGED, LATER)
    assert any("amount" in r for r in reasons)


def test_p3_no_tolerance_even_one_paisa():
    assert candidate_reasons(exc(delta=2000), adj(credit=2001, amount=2001),
                             FLAGGED, LATER)


def test_p4_adjustment_must_come_after_the_exception():
    reasons = candidate_reasons(exc(), adj(settled_at=FLAGGED), FLAGGED, FLAGGED)
    assert any("after" in r for r in reasons)


def test_p4_missing_timestamp_rejected():
    reasons = candidate_reasons(exc(), adj(settled_at=None), FLAGGED, None)
    assert any("ordering" in r for r in reasons)


def test_p5_missing_reference_rejected():
    reasons = candidate_reasons(
        exc(), adj(reference_settlement_id=None, description="Goodwill credit"),
        FLAGGED, LATER,
    )
    assert any("reference" in r for r in reasons)


def test_p5_reference_from_description_accepted():
    line = adj(reference_settlement_id=None,
               description="Recon correction for setl_lc_exact")
    assert candidate_reasons(exc(), line, FLAGGED, LATER) == []


def test_p5_reference_to_a_different_settlement_rejected():
    reasons = candidate_reasons(exc(), adj(reference_settlement_id="setl_other",
                                           description="Correction"), FLAGGED, LATER)
    assert any("reference" in r for r in reasons)


def test_p5_utr_named_in_description_accepted():
    line = adj(reference_settlement_id=None, description="Correction for UTRLC0001")
    assert candidate_reasons(exc(), line, FLAGGED, LATER) == []


def test_p6_one_adjustment_two_matching_exceptions_binds_nothing():
    """Reachable only when both exceptions belong to the SAME settlement, because P5
    requires an exact reference and a reference names exactly one settlement."""
    a = OpenException(exception_id="exc_a", settlement_id="setl_lc_exact",
                      control_type="batch_integrity", delta_paise=2000,
                      utr="UTRLC0001", flagged_at=FLAGGED)
    b = OpenException(exception_id="exc_b", settlement_id="setl_lc_exact",
                      control_type="tax_lines", delta_paise=2000,
                      utr="UTRLC0001", flagged_at=FLAGGED)
    result = match_adjustments([a, b], [adj(entity_id="adj_amb")])
    assert result["bindings"] == {}
    assert result["unmatched_adjustments"] == ["adj_amb"]


def test_p6_one_exception_two_matching_adjustments_binds_nothing():
    """The reachable ambiguity: Razorpay posts the same correction twice."""
    result = match_adjustments([exc()], [adj(entity_id="adj_x"), adj(entity_id="adj_y")])
    assert result["bindings"] == {}
    assert set(result["unmatched_adjustments"]) == {"adj_x", "adj_y"}


def test_exact_case_binds():
    result = match_adjustments([exc()], [adj()])
    assert result["bindings"] == {"exc_test": "adj_1"}
    assert result["unmatched_adjustments"] == []


def test_wrong_amount_leaves_exception_open_and_adjustment_unmatched():
    result = match_adjustments(
        [exc(delta=4000, sid="setl_lc_wrong_amount")],
        [adj(entity_id="adj_wrong", credit=3500, amount=3500,
             reference_settlement_id="setl_lc_wrong_amount", description="Partial")],
    )
    assert result["bindings"] == {}
    assert result["unmatched_adjustments"] == ["adj_wrong"]


def test_rejection_reasons_are_reported_for_review():
    result = match_adjustments(
        [exc(delta=4000, sid="setl_lc_wrong_amount")],
        [adj(entity_id="adj_wrong", credit=3500, amount=3500,
             reference_settlement_id="setl_lc_wrong_amount", description="Partial")],
    )
    assert result["rejections"]["adj_wrong"]


def test_over_settlement_needs_a_debit():
    """A negative delta means too much was paid; only a debit compensates it."""
    e = exc(delta=-2000)
    credit_line = adj(description="Correction for setl_lc_exact")
    assert any("direction" in r for r in candidate_reasons(e, credit_line, FLAGGED, LATER))
    debit_line = adj(debit=2000, credit=0, description="Correction for setl_lc_exact")
    assert candidate_reasons(e, debit_line, FLAGGED, LATER) == []


def test_no_open_exceptions_means_every_adjustment_unmatched():
    result = match_adjustments([], [adj()])
    assert result["bindings"] == {}
    assert result["unmatched_adjustments"] == ["adj_1"]


def test_no_adjustments_binds_nothing():
    result = match_adjustments([exc()], [])
    assert result["bindings"] == {}
    assert result["unmatched_adjustments"] == []


def test_rejection_reason_reports_the_closest_near_miss():
    """The review list must explain the near-miss, not whichever exception came first."""
    unrelated = exc(delta=2000, sid="setl_other", utr="UTROTHER", eid="exc_unrelated")
    referenced = exc(delta=4000, sid="setl_lc_wrong_amount", utr="UTRLC0002",
                     eid="exc_referenced")
    line = adj(entity_id="adj_wrong", credit=3500, amount=3500,
               reference_settlement_id="setl_lc_wrong_amount",
               description="Partial recon correction")
    result = match_adjustments([unrelated, referenced], [line])
    reasons = result["rejections"]["adj_wrong"]
    # Against the referenced exception only the amount is wrong (one reason).
    # Against the unrelated one both amount and reference are wrong (two reasons).
    assert reasons == ["amount 3500 != delta 4000"], reasons
