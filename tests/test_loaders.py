"""Loader tests for the pending-payment path."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from src.connectors.loaders import load_pending_payments


def test_load_pending_payments_computes_expected_date(tmp_path: Path):
    recon_path = tmp_path / "recon.json"
    manifest_path = tmp_path / "manifest.json"
    recon_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "entity_id": "pay_pending_000",
                        "type": "payment",
                        "amount": 49900,
                        "fee": 0,
                        "tax": 0,
                        "currency": "INR",
                        "settlement_id": None,
                        "order_id": "ord_pending_0",
                        "method": "upi",
                        "captured_at": "2026-08-30T10:00:00",
                        "cycle_type": "standard",
                        "instant_eligible": "no",
                    },
                    {
                        "entity_id": "pay_settled_000",
                        "type": "payment",
                        "amount": 100000,
                        "fee": 2000,
                        "tax": 300,
                        "currency": "INR",
                        "settlement_id": "setl_x",
                        "order_id": "ord_1",
                        "method": "card",
                        "settled": True,
                    },
                ]
            }
        )
    )
    manifest_path.write_text(json.dumps({"settlement_cycle": {"standard_days": 2, "instant_available": True}}))

    pending = load_pending_payments(recon_path, manifest_path)

    assert len(pending) == 1
    p = pending[0]
    assert p.entity_id == "pay_pending_000"
    assert p.amount == 49900
    assert p.order_id == "ord_pending_0"
    assert p.cycle_type == "standard"
    assert p.instant_eligible == "no"
    assert p.expected_settlement_at == date(2026, 8, 30) + timedelta(days=2)
