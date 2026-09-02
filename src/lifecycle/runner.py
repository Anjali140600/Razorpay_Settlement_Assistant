"""Run the lifecycle projection over the hand-written fixture set.

Self-contained, exactly like run_holdout_eval: it never reads the engine's data_dir, so
the closure metric can never be confused with the primary demo dataset's integrity rate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.connectors.loaders import (
    attach_lines_to_batches,
    load_recon_json,
    load_settlements_json,
)
from src.lifecycle.projection import LifecycleState, project

_ROOT = Path(__file__).resolve().parent.parent.parent
LIFECYCLE_DIR = _ROOT / "data" / "fixtures" / "lifecycle"
LIFECYCLE_LABELS = _ROOT / "data" / "eval_lifecycle_labels.json"


def _load_cycle(base: Path, name: str):
    recon = load_recon_json(base / name / "recon.json")
    batches = attach_lines_to_batches(
        load_settlements_json(base / name / "settlements.json"), recon
    )
    return batches, recon


def run_lifecycle_eval(lifecycle_dir: Path | None = None) -> dict[str, Any]:
    base = lifecycle_dir or LIFECYCLE_DIR
    cycle1_batches, _ = _load_cycle(base, "cycle1")
    _, cycle2_lines = _load_cycle(base, "cycle2")

    result = project(cycle1_batches, cycle2_lines)
    rows = result["exceptions"]

    closed = [r for r in rows if r["state"] == LifecycleState.CLOSED_COMPENSATED]
    open_rows = [r for r in rows if r["state"] == LifecycleState.OPEN]
    days = [r["days_to_close"] for r in closed if r["days_to_close"] is not None]

    labels_doc = json.loads(LIFECYCLE_LABELS.read_text()) if LIFECYCLE_LABELS.exists() else {}
    labels = labels_doc.get("labels", {})
    matches = sum(
        1 for r in rows
        if labels.get(r["settlement_id"], {}).get("expected_state") == r["state"].value
    )

    return {
        "lifecycle_exceptions_total": len(rows),
        "lifecycle_exceptions_open": len(open_rows),
        "lifecycle_exceptions_closed": len(closed),
        "lifecycle_closure_rate": len(closed) / len(rows) if rows else 0.0,
        "lifecycle_unmatched_adjustments": result["unmatched_adjustments"],
        "lifecycle_mean_days_to_close": sum(days) / len(days) if days else None,
        "lifecycle_label_matches": matches,
        "lifecycle_label_total": len(labels),
        "lifecycle_rows": rows,
        "lifecycle_source": labels_doc.get("source", "manual_fixtures"),
        "lifecycle_description": labels_doc.get("description", ""),
    }
