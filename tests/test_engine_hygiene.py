"""Run metadata must be truthful, and a render must not write repo files."""

from __future__ import annotations

from pathlib import Path

from src.engine import ReconciliationEngine


def run_once():
    engine = ReconciliationEngine(Path("data/synthetic/demo"))
    engine.load_sources()
    return engine.run()


def test_completed_at_reflects_real_completion():
    """Aliasing completed_at to started_at satisfies '>=' while reporting a lie."""
    run = run_once()
    assert run.completed_at is not None
    elapsed = (run.completed_at - run.started_at).total_seconds()
    assert elapsed >= run.runtime_seconds * 0.5, (
        f"completed_at spans {elapsed}s but the run measured "
        f"{run.runtime_seconds}s of work"
    )


def test_label_source_does_not_overstate_independence():
    """The verifier shares razorpay_contract with the controls; say so."""
    assert run_once().metrics["label_source"] == (
        "contract_verifier_independent_of_generator"
    )
