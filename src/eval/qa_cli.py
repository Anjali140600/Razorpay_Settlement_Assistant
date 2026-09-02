"""Q&A scorecard run. Requires a provider key for the AI column; never used by pytest.

Usage:
    python -m src.eval.qa_cli --runs 3 --data-dir data/synthetic/demo
    python -m src.eval.qa_cli --baseline-only     # no provider needed
"""

from __future__ import annotations

import src.config  # noqa: F401 — load .env

import argparse
import json
from pathlib import Path

from src.agent.llm_client import llm_providers_available
from src.connectors.loaders import (
    attach_lines_to_batches,
    load_recon_json,
    load_settlements_json,
)
from src.eval.qa_cases import load_qa_cases
from src.eval.qa_report import (
    ai_column_valid,
    flaky_cases,
    provenance,
    valid_runs,
    worst_run,
    write_report,
)
from src.eval.qa_runner import run_qa_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the settlement Q&A agent")
    parser.add_argument("--data-dir", type=Path, default=Path("data/synthetic/demo"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out-dir", type=Path, default=Path("sample-output"))
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Seconds between LLM cases. Free tiers rate-limit per minute, and every "
             "rate-limited case becomes a silent keyword answer.",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Score only the deterministic path; no provider key required.",
    )
    args = parser.parse_args()

    if not args.baseline_only and not llm_providers_available():
        raise SystemExit(
            "No LLM provider configured. Set GROQ_API_KEY (or CEREBRAS_API_KEY / "
            "OPENAI_API_KEY) in .env to score the AI column, or pass --baseline-only."
        )

    recon = load_recon_json(args.data_dir / "recon.json")
    batches = {
        b.settlement_id: b
        for b in attach_lines_to_batches(
            load_settlements_json(args.data_dir / "settlements.json"), recon
        )
    }
    cases = load_qa_cases()

    baseline = run_qa_eval(batches, use_llm=False, cases=cases)

    if args.baseline_only:
        ai_runs = [baseline]
        runs = 0
    else:
        ai_runs = [
            run_qa_eval(batches, use_llm=True, cases=cases, delay_seconds=args.delay)
            for _ in range(args.runs)
        ]
        runs = args.runs

    headline = worst_run(ai_runs)
    report = {
        "provenance": provenance(),
        "runs": runs,
        "baseline_only": args.baseline_only,
        "headline": headline["metrics"],
        "ai_column_valid": ai_column_valid(headline["metrics"], runs=runs),
        "runs_valid": len(valid_runs(ai_runs)) if runs else 0,
        "all_runs": [r["metrics"] for r in ai_runs],
        "deterministic_baseline": baseline["metrics"],
        "flaky_cases": flaky_cases(valid_runs(ai_runs)) if runs > 1 else [],
        "headline_rows": headline["rows"],
        # Every run's rows are retained so the headline can be re-selected later
        # without spending another provider budget re-measuring.
        "all_run_rows": [r["rows"] for r in ai_runs],
        "baseline_rows": baseline["rows"],
    }
    js, md = write_report(report, args.out_dir)
    print(json.dumps(report["headline"], indent=2))
    print(f"\nWrote {js} and {md}")


if __name__ == "__main__":
    main()
