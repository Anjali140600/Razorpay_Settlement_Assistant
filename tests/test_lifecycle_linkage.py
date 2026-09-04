"""An adjustment must be able to name the settlement it corrects."""

from __future__ import annotations

import json

from src.connectors.loaders import load_recon_json


def test_reference_settlement_id_loaded(tmp_path):
    path = tmp_path / "recon.json"
    path.write_text(json.dumps({"items": [{
        "entity_id": "adj_1", "type": "adjustment", "debit": 0, "credit": 5000,
        "amount": 5000, "fee": 0, "tax": 0, "settlement_id": "setl_cycle2",
        "reference_settlement_id": "setl_cycle1", "description": "Recon correction",
    }]}))
    assert load_recon_json(path)[0].reference_settlement_id == "setl_cycle1"


def test_reference_defaults_to_none_when_absent(tmp_path):
    path = tmp_path / "recon.json"
    path.write_text(json.dumps({"items": [{
        "entity_id": "pay_1", "type": "payment", "debit": 0, "credit": 9800,
        "amount": 10000, "fee": 200, "tax": 31, "settlement_id": "setl_a",
    }]}))
    assert load_recon_json(path)[0].reference_settlement_id is None
