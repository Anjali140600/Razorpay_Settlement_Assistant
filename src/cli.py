"""CLI entry point."""

from __future__ import annotations

import src.config  # noqa: F401 — load .env

import argparse
import json
from datetime import date
from pathlib import Path

from src.engine import ReconciliationEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Razorpay Settlement Assistant CLI")
    parser.add_argument("--data-dir", type=Path, default=Path("data/synthetic/demo"))
    parser.add_argument("--eval-date", type=str, default="2026-08-30")
    args = parser.parse_args()

    engine = ReconciliationEngine(args.data_dir, eval_date=date.fromisoformat(args.eval_date))
    engine.load_sources()
    run = engine.run()

    output = {
        "run_id": run.run_id,
        "metrics": run.metrics,
        "settlements": [
            {
                "settlement_id": d.settlement_id,
                "integrity_status": d.integrity_status.value,
                "batch_integrity": d.batch_integrity.value,
                "tax_lines": d.tax_lines.value,
                "amount_paise": d.net_amount_paise,
                "plain_issue": d.plain_issue,
            }
            for d in run.settlement_decisions
        ],
        "exceptions": engine.export_exceptions(run),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
