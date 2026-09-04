"""The fixture set must contain exactly the five designed lifecycle situations."""

from __future__ import annotations

import json
from pathlib import Path

from src.connectors.loaders import (
    attach_lines_to_batches,
    load_recon_json,
    load_settlements_json,
)

LIFECYCLE = Path("data/fixtures/lifecycle")
LABELS = Path("data/eval_lifecycle_labels.json")


def cycle(name: str):
    recon = load_recon_json(LIFECYCLE / name / "recon.json")
    batches = attach_lines_to_batches(
        load_settlements_json(LIFECYCLE / name / "settlements.json"), recon
    )
    return batches, recon


def test_both_cycles_load():
    b1, r1 = cycle("cycle1")
    b2, r2 = cycle("cycle2")
    assert b1 and r1 and b2 and r2


def test_cycle1_contains_the_flagged_settlements():
    batches, _ = cycle("cycle1")
    ids = {b.settlement_id for b in batches}
    assert {
        "setl_lc_exact",
        "setl_lc_wrong_amount",
        "setl_lc_duplicate_adjustments",
        "setl_lc_no_reference",
        "setl_lc_never_adjusted",
    } <= ids


def test_cycle2_carries_adjustment_lines():
    _, recon = cycle("cycle2")
    assert len([l for l in recon if l.line_type == "adjustment"]) >= 5


def test_only_one_adjustment_has_an_exact_reference_and_amount():
    _, recon = cycle("cycle2")
    referenced = [
        l for l in recon
        if l.line_type == "adjustment" and l.reference_settlement_id == "setl_lc_exact"
    ]
    assert len(referenced) == 1


def test_duplicate_adjustments_both_present():
    """Two identical corrections for one exception must both exist, or P6 is untested."""
    _, recon = cycle("cycle2")
    dup = [l for l in recon
           if l.reference_settlement_id == "setl_lc_duplicate_adjustments"]
    assert len(dup) == 2
    assert dup[0].credit == dup[1].credit


def test_labels_cover_every_flagged_settlement():
    doc = json.loads(LABELS.read_text())
    batches, _ = cycle("cycle1")
    flagged = {b.settlement_id for b in batches if b.settlement_id.startswith("setl_lc_")}
    assert flagged == set(doc["labels"])


def test_exactly_one_label_expects_closure():
    doc = json.loads(LABELS.read_text())
    closed = [k for k, v in doc["labels"].items()
              if v["expected_state"] == "CLOSED_COMPENSATED"]
    assert closed == ["setl_lc_exact"]


def test_labels_declare_they_are_hand_written():
    doc = json.loads(LABELS.read_text())
    assert "hand" in doc["description"].lower()
    assert doc["source"] == "manual_fixtures"


def test_cycle2_settlement_passes_its_own_controls():
    """The corrective cycle must not itself be an exception."""
    from src.controls.engine import validate_batch_integrity
    from src.domain.models import ControlStatus

    batches, _ = cycle("cycle2")
    for b in batches:
        assert validate_batch_integrity(b).status == ControlStatus.PASS
