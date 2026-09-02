"""Render the committed scorecard artifact.

Publishes the WORST of N runs, never the mean and never the best. A safety number that
moves between runs is only honest if the published figure is the floor.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agent.settlement_qa import _build_qa_system_prompt
from src.eval.qa_cases import QA_EVAL_PATH


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def provenance(cases_path: Path | None = None) -> dict[str, Any]:
    """Everything needed to reproduce or challenge a published number."""
    from src.agent.llm_client import get_llm_model, llm_provider

    cases_path = cases_path or QA_EVAL_PATH
    # get_llm_model raises when nothing is configured, which is the normal state for an
    # offline baseline-only run. Provenance must still be recordable.
    provider = llm_provider()
    return {
        "dataset_sha256": _sha256(cases_path.read_text()),
        "prompt_sha256": _sha256(_build_qa_system_prompt()),
        "git_commit": _git_commit(),
        "provider": provider or "none",
        "model": get_llm_model(provider) if provider else "none",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def worst_run(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return min(
        runs,
        key=lambda r: (
            r["metrics"].get("qa_pass_rate") or 0.0,
            -(r["metrics"].get("qa_unverified_amount_emissions") or 0),
        ),
    )


def flaky_cases(runs: list[dict[str, Any]]) -> list[str]:
    """Cases whose verdict was not stable across runs."""
    seen: dict[str, set[bool]] = {}
    for r in runs:
        for row in r["rows"]:
            seen.setdefault(row["case_id"], set()).add(bool(row["passed"]))
    return sorted(cid for cid, verdicts in seen.items() if len(verdicts) > 1)


def ai_column_valid(metrics: dict[str, Any], *, runs: int) -> bool:
    """False when the AI column is really rules fallback forced by a dead provider.

    A quota-exhausted run produces a full set of plausible-looking numbers that are
    pure keyword output. Publishing those as model performance would be the exact
    kind of false claim this scorecard exists to prevent.
    """
    if runs < 1:
        return False
    return not metrics.get("qa_llm_unavailable")


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _num(value: Any) -> str:
    return "n/a" if value is None else str(value)


def render_markdown(report: dict[str, Any]) -> str:
    p = report["provenance"]
    h = report["headline"]
    b = report["deterministic_baseline"]
    only_baseline = bool(report.get("baseline_only"))
    runs = report.get("runs") or 0
    published = (
        "deterministic path only, no AI run"
        if only_baseline
        else f"worst of {runs} run(s)"
    )
    model_line = (
        "not used in this run"
        if only_baseline
        else f"{p['provider']} / {p['model']}"
    )
    lines = [
        "# Q&A Trust Scorecard",
        "",
        f"**Cases:** {h['qa_cases_total']} hand-labeled  ",
        f"**Published figure:** {published}  ",
        f"**Model:** {model_line}  ",
        f"**Commit:** {p['git_commit']} · **Dataset:** `{p['dataset_sha256'][:12]}` · "
        f"**Prompt:** `{p['prompt_sha256'][:12]}`  ",
        f"**Generated:** {p['generated_at']}",
        "",
    ]
    if only_baseline:
        lines += [
            "> **The AI column was not measured in this run.** Only the deterministic",
            "> path was scored, so no figure here describes model behaviour.",
            "",
            "| Metric | Deterministic baseline |",
            "|---|---|",
        ]
        lines += [
            f"| Pass rate | {_pct(b.get('qa_pass_rate'))} |",
            f"| Citation validity | {_pct(b.get('qa_citation_validity'))} |",
            f"| Correct abstention | {_pct(b.get('qa_correct_abstention_rate'))} |",
            f"| Refusal (system guardrail) | {_pct(b.get('qa_refusal_rate'))} |",
            f"| Money exact | {_pct(b.get('qa_money_exact_rate'))} |",
            f"| **Unverified amounts emitted** | "
            f"{_num(b.get('qa_unverified_amount_emissions'))} |",
            f"| Answered by rules | {_num(b.get('qa_answered_by_rules'))} |",
        ]
        return "\n".join(lines + _how_to_read(report)) + "\n"

    if report.get("ai_column_valid") is False:
        lines += [
            "> **The AI column below is NOT a measurement of the model.**  ",
            f"> The provider was unavailable on {_num(h.get('qa_llm_unavailable'))} of "
            f"{h['qa_cases_total']} cases, so those answers are deterministic keyword "
            "output, not model output. Re-run once a provider is available before "
            "quoting any AI figure from this table.",
            "",
        ]
    lines += [
        "| Metric | Deterministic baseline | AI enabled (end to end) |",
        "|---|---|---|",
        f"| Pass rate | {_pct(b.get('qa_pass_rate'))} | {_pct(h.get('qa_pass_rate'))} |",
        f"| Citation validity | {_pct(b.get('qa_citation_validity'))} | "
        f"{_pct(h.get('qa_citation_validity'))} |",
        f"| Correct abstention | {_pct(b.get('qa_correct_abstention_rate'))} | "
        f"{_pct(h.get('qa_correct_abstention_rate'))} |",
        f"| Refusal (system guardrail) | {_pct(b.get('qa_refusal_rate'))} | "
        f"{_pct(h.get('qa_refusal_rate'))} |",
        f"| Money exact | {_pct(b.get('qa_money_exact_rate'))} | "
        f"{_pct(h.get('qa_money_exact_rate'))} |",
        f"| **Unverified amounts emitted** | "
        f"{_num(b.get('qa_unverified_amount_emissions'))} | "
        f"{_num(h.get('qa_unverified_amount_emissions'))} |",
        f"| Answered by LLM | {_num(b.get('qa_answered_by_llm'))} | "
        f"{_num(h.get('qa_answered_by_llm'))} |",
        f"| Answered by rules | {_num(b.get('qa_answered_by_rules'))} | "
        f"{_num(h.get('qa_answered_by_rules'))} |",
        f"| Validator caught wrong amount | "
        f"{_num(b.get('qa_validator_caught_wrong_amount'))} | "
        f"{_num(h.get('qa_validator_caught_wrong_amount'))} |",
        f"| Validator caught bad citation | "
        f"{_num(b.get('qa_validator_caught_bad_citation'))} | "
        f"{_num(h.get('qa_validator_caught_bad_citation'))} |",
        f"| Provider unavailable on | — | "
        f"{_num(h.get('qa_llm_unavailable'))} case(s) |",
    ]
    return "\n".join(lines + _how_to_read(report)) + "\n"


def _how_to_read(report: dict[str, Any]) -> list[str]:
    lines = [
        "",
        "## How to read this",
        "",
        "- The AI column is the **whole production path**: intent routing, tool use, the",
        "  money validators, the repair pass, abstention, and keyword fallback. It is not",
        "  a bare model score.",
        "- **Answered by rules** in the AI column means the LLM produced nothing usable",
        "  and the deterministic agent answered instead. Read the pass rate together",
        "  with it, or a high score could be pure fallback.",
        "- Prompt-injection refusal is a **system guardrail**, not model judgment: the",
        "  router refuses those questions before the model is invoked.",
        "- The money guard covers currency-marked amounts (`₹`, `Rs`, `INR`, `rupees`).",
        "  Bare numerals are deliberately not treated as money, because '18% GST' and",
        "  '50 records' would otherwise be read as figures.",
        "- Citation validity means every cited ID resolves to loaded data. It does not",
        "  assert that the citation semantically supports the sentence.",
        "- Unverified amounts are measured against the figures the evidence tools can",
        "  produce for the case settlement plus every settlement the answer cited.",
    ]
    if report.get("flaky_cases"):
        lines += ["", "## Cases that were not stable across runs", ""]
        lines += [f"- `{cid}`" for cid in report["flaky_cases"]]
    return lines


def write_report(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    js = out_dir / "qa_scorecard.json"
    md = out_dir / "qa_scorecard.md"
    js.write_text(json.dumps(report, indent=2, default=str))
    md.write_text(render_markdown(report))
    return js, md
