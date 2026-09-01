"""Holdout and independent verification tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.eval.holdout_runner import run_holdout_eval
from src.eval.independent_verifier import compute_expected_label, verify_labels_against_contract


def test_holdout_fixtures_exist():
    root = Path(__file__).resolve().parents[1]
    assert (root / "data/fixtures/holdout/settlements.json").exists()
    assert (root / "data/fixtures/holdout/recon.json").exists()
    assert (root / "data/eval_holdout_labels.json").exists()


def test_holdout_labels_match_independent_verifier():
    root = Path(__file__).resolve().parents[1]
    settlements = json.loads((root / "data/fixtures/holdout/settlements.json").read_text())["items"]
    recon = json.loads((root / "data/fixtures/holdout/recon.json").read_text())["items"]
    labels = json.loads((root / "data/eval_holdout_labels.json").read_text())["labels"]
    matches, total, errors = verify_labels_against_contract(settlements, recon, labels)
    assert not errors, errors
    assert matches == total == 8


def test_holdout_shows_both_pass_and_fail():
    result = run_holdout_eval()
    assert result["holdout_verified"] >= 4
    assert result["holdout_needs_attention"] >= 3
    assert result["holdout_integrity_rate"] < 1.0


def test_independent_verifier_detects_tax_fail():
    lines = [
        {
            "entity_id": "pay_x",
            "type": "payment",
            "settlement_id": "setl_x",
            "debit": 0,
            "credit": 19600,
            "amount": 20000,
            "fee": 400,
            "tax": 500,
        }
    ]
    label = compute_expected_label("setl_x", 19600, lines)
    assert label["status"] == "needs_attention"
    assert label["tax_lines"] == "fail"
