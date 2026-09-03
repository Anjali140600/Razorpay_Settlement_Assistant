"""Synthetic generator tests for the pending-payment dataset extension."""

from __future__ import annotations

import json
from pathlib import Path

from data.synthetic.generator import generate_demo_dataset


def test_generator_emits_pending_payments(tmp_path: Path):
    generate_demo_dataset(tmp_path, repo_root=tmp_path)

    recon = json.loads((tmp_path / "recon.json").read_text())
    items = recon["items"] if isinstance(recon, dict) else recon
    pending = [r for r in items if r.get("settlement_id") is None]

    assert len(pending) >= 3
    eligibilities = {r["instant_eligible"] for r in pending}
    assert eligibilities == {"yes", "no", "unknown"}
    for row in pending:
        assert row["settled"] is False
        assert row["settlement_utr"] is None
        assert row["settled_at"] is None
        assert "captured_at" in row
        assert row["cycle_type"] in ("standard", "instant_eligible")

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["pending_payment_lines"] == len(pending)
    assert manifest["settlement_cycle"] == {"standard_days": 2, "instant_available": True}
