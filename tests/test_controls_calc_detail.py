"""Expected vs actual calculation detail on control failures."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.controls.engine import validate_batch_integrity, validate_tax_lines
from src.domain.models import ControlStatus, SettlementLine
from src.domain.models import SettlementBatch
from src.engine import ReconciliationEngine


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    from data.synthetic.generator import generate_demo_dataset

    generate_demo_dataset(tmp_path, repo_root=tmp_path)
    return tmp_path


def test_batch_mismatch_has_calc_detail(demo_dir: Path):
    engine = ReconciliationEngine(demo_dir, eval_date=date(2026, 8, 30))
    engine.load_sources()
    batch = next(b for b in engine.batches if b.settlement_id == "setl_batch_mismatch")
    ctrl = validate_batch_integrity(batch)
    assert ctrl.status == ControlStatus.FAIL
    assert ctrl.calculation_detail is not None
    d = ctrl.calculation_detail
    assert "header" in d.expected_display.lower()
    assert "recon" in d.actual_display.lower()
    assert d.delta_display is not None
    assert "₹" in d.delta_display


def test_tax_mismatch_has_calc_detail(demo_dir: Path):
    engine = ReconciliationEngine(demo_dir, eval_date=date(2026, 8, 30))
    engine.load_sources()
    batch = next(b for b in engine.batches if b.settlement_id == "setl_tax_mismatch")
    ctrl = validate_tax_lines(batch)
    assert ctrl.status == ControlStatus.FAIL
    assert ctrl.calculation_detail is not None
    d = ctrl.calculation_detail
    assert d.line_id is not None
    assert "pay_" in d.line_id
    assert "₹" in d.expected_display
    assert "₹" in d.actual_display


def test_pass_has_no_calc_detail():
    batch = SettlementBatch(
        settlement_id="s1",
        amount=9700,
        lines=[
            SettlementLine(
                entity_id="p1",
                line_type="payment",
                debit=0,
                credit=9700,
                amount=10000,
                fee=300,
                tax=46,
                settlement_id="s1",
            )
        ],
    )
    batch_ctrl = validate_batch_integrity(batch)
    tax_ctrl = validate_tax_lines(batch)
    assert batch_ctrl.status == ControlStatus.PASS
    assert batch_ctrl.calculation_detail is None
    assert tax_ctrl.calculation_detail is None
