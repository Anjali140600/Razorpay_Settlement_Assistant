"""Closure must be reported without touching the historical integrity rate."""

from __future__ import annotations

from pathlib import Path

from src.engine import ReconciliationEngine
from src.lifecycle.runner import run_lifecycle_eval


def test_metrics_match_the_hand_written_labels():
    m = run_lifecycle_eval()
    assert m["lifecycle_exceptions_total"] == 5
    assert m["lifecycle_exceptions_closed"] == 1
    assert m["lifecycle_exceptions_open"] == 4
    assert m["lifecycle_label_matches"] == m["lifecycle_label_total"] == 5


def test_closure_rate_is_honest_not_flattering():
    assert run_lifecycle_eval()["lifecycle_closure_rate"] == 0.2


def test_unmatched_adjustments_reported():
    assert len(run_lifecycle_eval()["lifecycle_unmatched_adjustments"]) == 4


def test_mean_days_to_close_computed():
    assert run_lifecycle_eval()["lifecycle_mean_days_to_close"] == 3.0


def test_source_declares_hand_written_fixtures():
    assert run_lifecycle_eval()["lifecycle_source"] == "manual_fixtures"


def test_engine_exposes_lifecycle_metrics():
    engine = ReconciliationEngine(Path("data/synthetic/demo"))
    engine.load_sources()
    assert "lifecycle_closure_rate" in engine.run().metrics


def test_integrity_rate_is_unchanged_by_closure():
    """The load-bearing invariant: compensation never repairs history."""
    engine = ReconciliationEngine(Path("data/synthetic/demo"))
    engine.load_sources()
    run = engine.run()
    assert run.metrics["settlement_integrity_rate"] == 27 / 33
    assert run.metrics["lifecycle_exceptions_closed"] == 1


def test_lifecycle_does_not_add_settlements_to_the_primary_run():
    """The fixture set is separate data; it must not inflate the demo counts."""
    engine = ReconciliationEngine(Path("data/synthetic/demo"))
    engine.load_sources()
    run = engine.run()
    assert run.metrics["total_settlements"] == 33
