"""Run controls on independent holdout fixtures (not generator output)."""

from __future__ import annotations

import json
from pathlib import Path

from src.connectors.loaders import attach_lines_to_batches, load_recon_json, load_settlements_json
from src.controls.engine import compose_settlement_integrity_decision, validate_batch_integrity, validate_tax_lines
from src.domain.models import SettlementIntegrityStatus

HOLDOUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures" / "holdout"
HOLDOUT_LABELS = Path(__file__).resolve().parent.parent.parent / "data" / "eval_holdout_labels.json"


def run_holdout_eval(holdout_dir: Path | None = None) -> dict:
    holdout_dir = holdout_dir or HOLDOUT_DIR
    recon = load_recon_json(holdout_dir / "recon.json")
    batches = attach_lines_to_batches(load_settlements_json(holdout_dir / "settlements.json"), recon)

    labels_doc = json.loads(HOLDOUT_LABELS.read_text()) if HOLDOUT_LABELS.exists() else {}
    labels = labels_doc.get("labels", {})

    verified = 0
    label_matches = 0
    exceptions: list[dict] = []
    decisions = []

    for batch in batches:
        if batch.status != "processed":
            continue
        batch_ctrl = validate_batch_integrity(batch)
        tax_ctrl = validate_tax_lines(batch)
        decision = compose_settlement_integrity_decision(batch, batch_ctrl, tax_ctrl)
        decisions.append(decision)

        if decision.integrity_status == SettlementIntegrityStatus.VERIFIED:
            verified += 1
        else:
            for ctrl in decision.control_decisions:
                if ctrl.status.value != "PASS":
                    exceptions.append(
                        {
                            "settlement_id": batch.settlement_id,
                            "control_type": ctrl.control_type,
                            "message": ctrl.message,
                            "plain_issue": decision.plain_issue,
                        }
                    )

        label = labels.get(batch.settlement_id)
        if label:
            expected = label.get("status") == "verified"
            actual = decision.integrity_status == SettlementIntegrityStatus.VERIFIED
            if expected == actual:
                label_matches += 1

    processed = len([b for b in batches if b.status == "processed"])
    return {
        "holdout_settlements": processed,
        "holdout_recon_lines": len(recon),
        "holdout_verified": verified,
        "holdout_needs_attention": processed - verified,
        "holdout_integrity_rate": verified / processed if processed else 0.0,
        "holdout_labeled_accuracy": label_matches / len(labels) if labels else None,
        "holdout_labeled_count": len(labels),
        "holdout_exceptions": exceptions,
        "holdout_source": "independent_handcrafted_fixtures",
        "holdout_description": labels_doc.get("description", ""),
    }
