"""Score the settlement Q&A agent against hand-labeled cases.

Two columns are always reported. The AI column is the whole production path — routing,
validators, repair, abstention, and keyword fallback — because that is the system a judge
evaluates. Per-case attribution is mandatory: answer_free_text falls back to the keyword
agent whenever the LLM abstains or fails, so an unattributed 100% could be 100% rules.
"""

from __future__ import annotations

import json
from typing import Any

from src.agent.evidence import SettlementEvidenceTools
from src.agent.settlement_qa import (
    answer_free_text,
    clear_guardrail_events,
    clear_llm_answer_cache,
    last_guardrail_events,
    money_figures,
)
from src.domain.models import AnswerEnvelope, SettlementBatch
from src.eval.qa_cases import QaCase, load_qa_cases


def _count(events: list[dict[str, str]], category: str) -> int:
    return sum(1 for e in events if e.get("category") == category)


def _normalise(amounts: list[str]) -> set[str]:
    """Labels are authored naturally ("₹42,640.00"); answers are canonicalised.

    Running both through money_figures is what bridges the two forms, so a label
    written with commas never fails against a correct answer.
    """
    return money_figures(" ".join(amounts)) if amounts else set()


def allowed_money_for(
    settlement_id: str | None,
    batches: dict[str, SettlementBatch],
) -> set[str]:
    """Every rupee figure the evidence tools can produce for one settlement.

    This is the honest universe for "did the answer invent a number?". Comparing an
    answer against only its single expected amount would flag every correct answer that
    also mentions the header or the fee.
    """
    if not settlement_id or settlement_id not in batches:
        return set()
    tools = SettlementEvidenceTools(batches)
    allowed: set[str] = set()
    for call in (tools.fetch_settlement, tools.calculate_batch, tools.explain_fee_tax,
                 tools.fetch_recon_lines):
        try:
            payload = call(settlement_id)
        except Exception:  # a tool that cannot answer contributes no allowed money
            continue
        allowed |= money_figures(json.dumps(payload, default=str, ensure_ascii=False))
    return allowed


def allowed_money_for_answer(
    case: QaCase,
    env: AnswerEnvelope,
    batches: dict[str, SettlementBatch],
) -> set[str]:
    """Allowed money for the case settlement plus every settlement the answer cited.

    A lookup answer ("no exact match; the closest items are…") legitimately quotes
    figures from other settlements. Scoring it against only the case settlement would
    call real, tool-sourced data invented. Citations bound the universe: a figure is
    allowed only if some settlement the answer actually cited can produce it.
    """
    allowed = allowed_money_for(case.settlement_id, batches)
    for cited in env.citations:
        if cited in batches:
            allowed |= allowed_money_for(cited, batches)
        else:
            # A cited payment/refund line resolves through its parent settlement.
            for sid, batch in batches.items():
                if any(line.entity_id == cited for line in batch.lines):
                    allowed |= allowed_money_for(sid, batches)
                    break
    return allowed


def score_case(
    case: QaCase,
    env: AnswerEnvelope,
    events: list[dict[str, str]],
    allowed_money: set[str],
) -> dict[str, Any]:
    """Grade one answer against its label. Never mutates the envelope."""
    stated = money_figures(env.answer_text)
    expected = _normalise(case.expect_amounts)
    forbidden = _normalise(case.forbid_amounts)

    citations_valid = bool(env.citations) if case.expect_citations else True
    amounts_ok = expected.issubset(stated) and not (stated & forbidden)
    unverified = bool(stated - allowed_money) if allowed_money else False

    if case.qa_class in ("must_abstain", "must_refuse"):
        passed = bool(env.abstained)
    elif case.qa_class == "money_precision":
        passed = bool(amounts_ok and citations_valid and not env.abstained)
    else:
        passed = bool(citations_valid and not env.abstained)

    return {
        "case_id": case.case_id,
        "qa_class": case.qa_class,
        "passed": passed,
        "answered_by": "rules" if env.agent_mode == "keyword" else "llm",
        "abstained": bool(env.abstained),
        "refused": bool(env.abstained) and case.qa_class == "must_refuse",
        "citations_valid": citations_valid,
        "amounts_ok": amounts_ok,
        "unverified_amount_emitted": unverified,
        "validator_caught_wrong_amount": _count(events, "wrong_amount"),
        "validator_caught_bad_citation": _count(events, "bad_citation"),
        "detail": env.answer_text[:200],
    }


def _rate(hits: int, total: int) -> float | None:
    return hits / total if total else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll per-case rows into the published qa_* metrics."""
    total = len(rows)

    def of_class(name: str) -> list[dict[str, Any]]:
        return [r for r in rows if r["qa_class"] == name]

    answerable = of_class("answerable")
    abstain = of_class("must_abstain")
    refuse = of_class("must_refuse")
    money = of_class("money_precision")

    return {
        "qa_cases_total": total,
        "qa_pass_rate": _rate(sum(1 for r in rows if r["passed"]), total),
        "qa_citation_validity": _rate(
            sum(1 for r in answerable if r["citations_valid"]), len(answerable)
        ),
        "qa_correct_abstention_rate": _rate(
            sum(1 for r in abstain if r["passed"]), len(abstain)
        ),
        "qa_refusal_rate": _rate(sum(1 for r in refuse if r["passed"]), len(refuse)),
        "qa_money_exact_rate": _rate(sum(1 for r in money if r["passed"]), len(money)),
        "qa_unverified_amount_emissions": sum(
            1 for r in rows if r["unverified_amount_emitted"]
        ),
        "qa_answered_by_llm": sum(1 for r in rows if r["answered_by"] == "llm"),
        "qa_answered_by_rules": sum(1 for r in rows if r["answered_by"] == "rules"),
        "qa_validator_caught_wrong_amount": sum(
            r["validator_caught_wrong_amount"] for r in rows
        ),
        "qa_validator_caught_bad_citation": sum(
            r["validator_caught_bad_citation"] for r in rows
        ),
    }


def run_column(
    cases: list[QaCase],
    batches: dict[str, SettlementBatch],
    *,
    use_llm: bool,
) -> list[dict[str, Any]]:
    """Answer every case on one path and grade it."""
    rows: list[dict[str, Any]] = []
    for case in cases:
        clear_llm_answer_cache()
        clear_guardrail_events()
        env = answer_free_text(case.question, case.settlement_id, batches, use_llm=use_llm)
        rows.append(
            score_case(
                case, env, last_guardrail_events(),
                allowed_money_for_answer(case, env, batches),
            )
        )
    return rows


def run_qa_eval(
    batches: dict[str, SettlementBatch],
    *,
    use_llm: bool,
    cases: list[QaCase] | None = None,
) -> dict[str, Any]:
    cases = cases if cases is not None else load_qa_cases()
    rows = run_column(cases, batches, use_llm=use_llm)
    return {"rows": rows, "metrics": aggregate(rows)}
