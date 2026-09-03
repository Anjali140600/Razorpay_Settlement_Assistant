"""Razorpay Settlement Assistant integration tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.connectors.loaders import load_recon_json
from src.controls.engine import (
    compose_settlement_integrity_decision,
    validate_batch_integrity,
    validate_tax_lines,
)
from src.domain.models import (
    ControlStatus,
    SettlementBatch,
    SettlementIntegrityStatus,
    SettlementLine,
)
from src.engine import ReconciliationEngine


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    from data.synthetic.generator import generate_demo_dataset

    generate_demo_dataset(tmp_path, repo_root=tmp_path)
    return tmp_path


def test_batch_integrity_pass():
    batch = SettlementBatch(
        settlement_id="s1",
        amount=9700,
        lines=[
            SettlementLine(
                entity_id="p1", line_type="payment", debit=0, credit=9700,
                amount=10000, fee=300, tax=46, settlement_id="s1",
            )
        ],
    )
    ctrl = validate_batch_integrity(batch)
    assert ctrl.status == ControlStatus.PASS


def test_batch_integrity_fail():
    batch = SettlementBatch(
        settlement_id="s1",
        amount=9000,
        lines=[
            SettlementLine(
                entity_id="p1", line_type="payment", debit=0, credit=9700,
                amount=10000, fee=300, tax=46, settlement_id="s1",
            )
        ],
    )
    ctrl = validate_batch_integrity(batch)
    assert ctrl.status == ControlStatus.FAIL


def test_tax_lines_pass():
    batch = SettlementBatch(
        settlement_id="s1",
        amount=9700,
        lines=[
            SettlementLine(
                entity_id="p1", line_type="payment", debit=0, credit=9700,
                amount=10000, fee=300, tax=46, settlement_id="s1",
            )
        ],
    )
    ctrl = validate_tax_lines(batch)
    assert ctrl.status == ControlStatus.PASS


def test_tax_lines_fail():
    batch = SettlementBatch(
        settlement_id="s1",
        amount=9700,
        lines=[
            SettlementLine(
                entity_id="p1", line_type="payment", debit=0, credit=9700,
                amount=10000, fee=300, tax=200, settlement_id="s1",
            )
        ],
    )
    ctrl = validate_tax_lines(batch)
    assert ctrl.status == ControlStatus.FAIL


def test_compose_verified():
    batch = SettlementBatch(
        settlement_id="s1",
        amount=9700,
        lines=[SettlementLine(entity_id="p1", line_type="payment", debit=0, credit=9700, amount=10000, fee=300, tax=46, settlement_id="s1")],
    )
    batch_ctrl = validate_batch_integrity(batch)
    tax_ctrl = validate_tax_lines(batch)
    decision = compose_settlement_integrity_decision(batch, batch_ctrl, tax_ctrl)
    assert decision.integrity_status == SettlementIntegrityStatus.VERIFIED


def test_50_plus_records(demo_dir: Path):
    recon = load_recon_json(demo_dir / "recon.json")
    assert len(recon) >= 50


def test_settlement_integrity_on_demo(demo_dir: Path):
    engine = ReconciliationEngine(demo_dir, eval_date=date(2026, 8, 30))
    engine.load_sources()
    run = engine.run()
    assert run.metrics["total_recon_lines"] >= 50
    assert run.metrics["processed_settlements"] >= 25
    assert run.metrics["verified_settlements"] >= 20
    assert run.metrics["needs_attention_settlements"] >= 4
    assert 0.65 <= run.metrics["settlement_integrity_rate"] <= 0.90


def test_tax_mismatch_flagged(demo_dir: Path):
    engine = ReconciliationEngine(demo_dir, eval_date=date(2026, 8, 30))
    engine.load_sources()
    run = engine.run()
    tax_case = next(d for d in run.settlement_decisions if d.settlement_id == "setl_tax_mismatch")
    assert tax_case.integrity_status == SettlementIntegrityStatus.NEEDS_ATTENTION
    assert tax_case.tax_lines == ControlStatus.FAIL


def test_batch_mismatch_flagged(demo_dir: Path):
    engine = ReconciliationEngine(demo_dir, eval_date=date(2026, 8, 30))
    engine.load_sources()
    run = engine.run()
    batch_case = next(d for d in run.settlement_decisions if d.settlement_id == "setl_batch_mismatch")
    assert batch_case.integrity_status == SettlementIntegrityStatus.NEEDS_ATTENTION
    assert batch_case.batch_integrity == ControlStatus.FAIL


def test_labeled_accuracy(demo_dir: Path):
    engine = ReconciliationEngine(demo_dir, eval_date=date(2026, 8, 30))
    engine.load_sources()
    run = engine.run()
    assert run.metrics["labeled_control_accuracy"] == 1.0


def test_export_exceptions(demo_dir: Path):
    engine = ReconciliationEngine(demo_dir, eval_date=date(2026, 8, 30))
    engine.load_sources()
    run = engine.run()
    exceptions = engine.export_exceptions(run)
    assert len(exceptions) >= 4
    sids = {e["settlement_id"] for e in exceptions}
    assert "setl_tax_mismatch" in sids
    assert "setl_batch_mismatch" in sids


def test_holdout_eval_independent():
    from src.eval.holdout_runner import run_holdout_eval

    result = run_holdout_eval()
    assert result["holdout_settlements"] == 8
    assert result["holdout_verified"] == 5
    assert result["holdout_needs_attention"] == 3
    assert result["holdout_labeled_accuracy"] == 1.0
    assert len(result["holdout_exceptions"]) >= 3


def test_false_auto_closes_zero(demo_dir: Path):
    engine = ReconciliationEngine(demo_dir, eval_date=date(2026, 8, 30))
    engine.load_sources()
    run = engine.run()
    assert run.metrics["false_auto_closes"] == 0
