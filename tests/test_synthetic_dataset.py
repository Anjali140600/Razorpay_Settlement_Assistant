"""Validate synthetic dataset meets Razorpay Buildathon Track 04 requirements."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.synthetic.generator import generate_demo_dataset
from src.domain.razorpay_contract import batch_net_paise, validate_line


@pytest.fixture
def demo_dir(tmp_path: Path) -> Path:
    generate_demo_dataset(tmp_path, repo_root=tmp_path)
    return tmp_path


@pytest.fixture
def repo_demo() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "synthetic" / "demo"


def test_hackathon_minimum_record_counts(demo_dir: Path):
    recon = json.loads((demo_dir / "recon.json").read_text())["items"]
    settlements = json.loads((demo_dir / "settlements.json").read_text())["items"]
    assert len(recon) >= 50, "Track 04 requires 50+ transaction records"
    assert len(settlements) >= 25, "Plan requires 25+ settlements"


def test_exception_scenarios_present(demo_dir: Path):
    labels = json.loads((demo_dir / "data" / "eval_labels.json").read_text())["labels"]
    assert "setl_tax_mismatch" in labels
    assert "setl_batch_mismatch" in labels
    assert labels["setl_tax_mismatch"]["tax_lines"] == "fail"
    assert labels["setl_batch_mismatch"]["batch_integrity"] == "fail"


def test_clean_settlements_pass_contract(demo_dir: Path):
    recon = json.loads((demo_dir / "recon.json").read_text())["items"]
    labels = json.loads((demo_dir / "data" / "eval_labels.json").read_text())["labels"]
    verified_ids = {sid for sid, v in labels.items() if v["status"] == "verified"}
    for sid in verified_ids:
        lines = [l for l in recon if l["settlement_id"] == sid]
        for line in lines:
            assert validate_line(line) == [], f"{sid}/{line['entity_id']} violates contract"


def test_batch_integrity_on_verified(demo_dir: Path):
    recon = json.loads((demo_dir / "recon.json").read_text())["items"]
    settlements = {s["id"]: s for s in json.loads((demo_dir / "settlements.json").read_text())["items"]}
    labels = json.loads((demo_dir / "data" / "eval_labels.json").read_text())["labels"]
    for sid, label in labels.items():
        if label["batch_integrity"] != "pass":
            continue
        lines = [l for l in recon if l["settlement_id"] == sid]
        assert batch_net_paise(lines) == settlements[sid]["amount"]


def test_mixed_line_types_present(demo_dir: Path):
    recon = json.loads((demo_dir / "recon.json").read_text())["items"]
    types = {l["type"] for l in recon}
    assert "payment" in types
    assert "refund" in types
    assert "transfer" in types
    assert "adjustment" in types


def test_golden_fixture_independent_of_generator():
    golden_path = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "recon_golden.json"
    golden = json.loads(golden_path.read_text())
    assert golden["source"].startswith("https://razorpay.com/docs")
    transfer = next(i for i in golden["items"] if i["type"] == "transfer")
    assert transfer["debit"] == transfer["amount"] + transfer["fee"]


def test_committed_demo_meets_minimums(repo_demo: Path):
    if not (repo_demo / "recon.json").exists():
        pytest.skip("Run generator to create committed demo data")
    recon = json.loads((repo_demo / "recon.json").read_text())["items"]
    settlements = json.loads((repo_demo / "settlements.json").read_text())["items"]
    assert len(recon) >= 50
    assert len(settlements) >= 25
