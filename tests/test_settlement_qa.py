"""Settlement Q&A tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.agent.settlement_qa import (
    answer_free_text,
    answer_preset,
    sanitize_question,
    validate_citations,
    validate_question_input,
)
from src.connectors.loaders import attach_lines_to_batches, load_recon_json, load_settlements_json
from src.engine import ReconciliationEngine


@pytest.fixture
def batches(tmp_path: Path):
    from data.synthetic.generator import generate_demo_dataset

    generate_demo_dataset(tmp_path, repo_root=tmp_path)
    recon = load_recon_json(tmp_path / "recon.json")
    headers = load_settlements_json(tmp_path / "settlements.json")
    attached = attach_lines_to_batches(headers, recon)
    return {b.settlement_id: b for b in attached}


def test_preset_where_cites_settlement(batches):
    ans = answer_preset("where_is_settlement", "setl_merchant_d2c_000", batches)
    assert not ans.abstained
    assert "setl_merchant_d2c_000" in ans.citations
    assert "UTR" in ans.answer_text


def test_preset_breakdown_fees(batches):
    ans = answer_preset("breakdown_fees", "setl_merchant_d2c_000", batches)
    assert not ans.abstained
    assert any(c.startswith("pay_") for c in ans.citations)


def test_free_text_fee_question(batches):
    ans = answer_free_text("What are the fees and GST?", "setl_merchant_d2c_000", batches)
    assert not ans.abstained
    assert "fee" in ans.answer_text.lower() or "gst" in ans.answer_text.lower()


def test_abstention_unknown_settlement(batches):
    ans = answer_preset("where_is_settlement", "setl_does_not_exist", batches)
    assert ans.abstained


def test_abstention_unknown_utr(batches):
    ans = answer_free_text("Where is UTR UTR99999999999UNKNOWN?", None, batches)
    assert ans.abstained


def test_entity_lookup(batches):
    ans = answer_free_text("fee on pay_setl_tax_mismatch_0", "setl_tax_mismatch", batches)
    assert not ans.abstained
    assert "pay_setl_tax_mismatch_0" in ans.citations


def test_citation_validator(batches):
    assert validate_citations(["setl_merchant_d2c_000"], batches) == []
    assert validate_citations(["pay_fake_id"], batches) == ["pay_fake_id"]


def test_question_validation():
    assert validate_question_input("")[0] is False
    assert validate_question_input("x" * 600)[0] is False
    assert validate_question_input("valid question")[0] is True


def test_sanitize_strips_null():
    assert "\x00" not in sanitize_question("hello\x00world")
