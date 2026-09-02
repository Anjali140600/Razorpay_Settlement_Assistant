"""The projection is recomputed from feeds; it must never rewrite settlement history."""

from __future__ import annotations

from pathlib import Path

from src.connectors.loaders import (
    attach_lines_to_batches,
    load_recon_json,
    load_settlements_json,
)
from src.lifecycle.projection import (
    LifecycleState,
    dispute_packet,
    open_exceptions_from,
    project,
)

LIFECYCLE = Path("data/fixtures/lifecycle")


def load_cycle(name: str):
    recon = load_recon_json(LIFECYCLE / name / "recon.json")
    batches = attach_lines_to_batches(
        load_settlements_json(LIFECYCLE / name / "settlements.json"), recon
    )
    return batches, recon


def test_five_open_exceptions_found_in_cycle1():
    batches, _ = load_cycle("cycle1")
    assert len(open_exceptions_from(batches)) == 5


def test_dispute_packet_carries_delta_and_evidence_hash():
    batches, _ = load_cycle("cycle1")
    batch = next(b for b in batches if b.settlement_id == "setl_lc_exact")
    exc = next(e for e in open_exceptions_from(batches)
               if e.settlement_id == "setl_lc_exact")
    packet = dispute_packet(exc, batch)
    assert packet.delta_paise == 2000
    assert "20.00" in packet.delta_display
    assert len(packet.evidence_hash) == 16
    assert packet.citations


def test_evidence_hash_is_stable():
    batches, _ = load_cycle("cycle1")
    batch = next(b for b in batches if b.settlement_id == "setl_lc_exact")
    exc = next(e for e in open_exceptions_from(batches)
               if e.settlement_id == "setl_lc_exact")
    assert dispute_packet(exc, batch).evidence_hash == dispute_packet(exc, batch).evidence_hash


def test_only_the_exact_case_closes():
    b1, _ = load_cycle("cycle1")
    _, r2 = load_cycle("cycle2")
    states = {e["settlement_id"]: e["state"] for e in project(b1, r2)["exceptions"]}
    assert states["setl_lc_exact"] == LifecycleState.CLOSED_COMPENSATED
    for sid in (
        "setl_lc_wrong_amount",
        "setl_lc_duplicate_adjustments",
        "setl_lc_no_reference",
        "setl_lc_never_adjusted",
    ):
        assert states[sid] == LifecycleState.OPEN, sid


def test_closed_exception_records_days_to_close():
    b1, _ = load_cycle("cycle1")
    _, r2 = load_cycle("cycle2")
    closed = next(e for e in project(b1, r2)["exceptions"]
                  if e["state"] == LifecycleState.CLOSED_COMPENSATED)
    assert closed["days_to_close"] == 3
    assert closed["matched_adjustment"] == "adj_lc_exact"


def test_open_exceptions_have_no_days_to_close():
    b1, _ = load_cycle("cycle1")
    _, r2 = load_cycle("cycle2")
    for e in project(b1, r2)["exceptions"]:
        if e["state"] == LifecycleState.OPEN:
            assert e["days_to_close"] is None


def test_unmatched_adjustments_reported():
    b1, _ = load_cycle("cycle1")
    _, r2 = load_cycle("cycle2")
    assert set(project(b1, r2)["unmatched_adjustments"]) == {
        "adj_lc_wrong", "adj_lc_dup_1", "adj_lc_dup_2", "adj_lc_noref"
    }


def test_every_exception_carries_a_dispute_packet():
    b1, _ = load_cycle("cycle1")
    _, r2 = load_cycle("cycle2")
    for e in project(b1, r2)["exceptions"]:
        assert e["dispute_packet"]["evidence_hash"]


def test_projection_is_idempotent():
    b1, _ = load_cycle("cycle1")
    _, r2 = load_cycle("cycle2")
    first, second = project(b1, r2), project(b1, r2)
    assert [e["exception_id"] for e in first["exceptions"]] == [
        e["exception_id"] for e in second["exceptions"]
    ]


def test_projection_never_mutates_the_batches():
    b1, _ = load_cycle("cycle1")
    _, r2 = load_cycle("cycle2")
    before = [(b.settlement_id, b.amount, len(b.lines)) for b in b1]
    project(b1, r2)
    assert [(b.settlement_id, b.amount, len(b.lines)) for b in b1] == before


def test_payment_lines_in_cycle2_are_ignored():
    """Only adjustment lines can compensate an exception."""
    b1, _ = load_cycle("cycle1")
    _, r2 = load_cycle("cycle2")
    payments = [l for l in r2 if l.line_type == "payment"]
    result = project(b1, [l for l in r2 if l.line_type == "adjustment"] + payments)
    assert result["exceptions"]
