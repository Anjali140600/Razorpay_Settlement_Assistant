"""Bind Razorpay adjustments to open exceptions — deterministically, or not at all.

Six predicates, all mandatory. No amount tolerance, no fuzzy identifier matching, no
"best candidate". An LLM never participates: a hallucinated binding would silently mark
a real financial exception as resolved, which is the failure mode the whole architecture
exists to prevent. rapidfuzz may rank unmatched lines for human review elsewhere; it
must never reach this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from src.domain.models import SettlementLine
from src.domain.razorpay_contract import validate_adjustment_line
from src.lifecycle.identity import extract_reference_settlement_id


class OpenException(BaseModel):
    exception_id: str
    settlement_id: str
    control_type: str
    delta_paise: int
    utr: str = ""
    flagged_at: datetime | None = None


def _as_contract_dict(line: SettlementLine) -> dict[str, Any]:
    """validate_adjustment_line works on raw recon rows, not domain models."""
    return {
        "entity_id": line.entity_id,
        "type": line.line_type,
        "debit": line.debit,
        "credit": line.credit,
        "amount": line.amount,
        "fee": line.fee,
        "tax": line.tax,
    }


def _reference_of(line: SettlementLine) -> str | None:
    if line.reference_settlement_id:
        return line.reference_settlement_id.lower()
    return extract_reference_settlement_id(line.description)


def candidate_reasons(
    exc: OpenException,
    line: SettlementLine,
    flagged_at: datetime | None,
    adjustment_at: datetime | None,
) -> list[str]:
    """Every predicate this pair fails. An empty list means all six hold."""
    reasons: list[str] = []

    # P1 — the adjustment is a well-formed adjustment line.
    errors = validate_adjustment_line(_as_contract_dict(line))
    if errors:
        reasons.append(f"invalid adjustment line: {errors[0]}")

    # P2 — currency matches and the direction compensates the delta's sign.
    if line.currency != "INR":
        reasons.append(f"currency {line.currency} is not INR")
    if exc.delta_paise > 0 and line.credit <= 0:
        reasons.append("direction: a short settlement needs a credit adjustment")
    if exc.delta_paise < 0 and line.debit <= 0:
        reasons.append("direction: an over-settlement needs a debit adjustment")

    # P3 — amount equals the delta exactly, in paise. No tolerance.
    moved = line.credit if line.credit else line.debit
    if moved != abs(exc.delta_paise):
        reasons.append(f"amount {moved} != delta {abs(exc.delta_paise)}")

    # P4 — strictly after the exception.
    if not adjustment_at:
        reasons.append("adjustment has no settled_at, so ordering cannot be proven")
    elif flagged_at and adjustment_at <= flagged_at:
        reasons.append("adjustment is not after the exception")

    # P5 — an exact reference to the original settlement or its UTR.
    ref = _reference_of(line)
    utr_named = bool(exc.utr) and exc.utr.upper() in (line.description or "").upper()
    if ref != exc.settlement_id.lower() and not utr_named:
        reasons.append("no exact reference to the original settlement or UTR")

    return reasons


def match_adjustments(
    exceptions: list[OpenException],
    adjustments: list[SettlementLine],
) -> dict[str, Any]:
    """One-to-one bindings only. Ambiguity on either side binds nothing."""
    viable: dict[str, list[str]] = {}          # entity_id -> matching exception_ids
    rejections: dict[str, list[str]] = {}

    for line in adjustments:
        matches: list[str] = []
        first_rejection: list[str] = []
        for exc in exceptions:
            reasons = candidate_reasons(exc, line, exc.flagged_at, line.settled_at)
            if reasons:
                if not first_rejection:
                    first_rejection = reasons
            else:
                matches.append(exc.exception_id)
        viable[line.entity_id] = matches
        if not matches:
            rejections[line.entity_id] = first_rejection or ["no open exception matched"]

    # P6 — exactly one exception for this adjustment, and this adjustment the only
    # candidate for that exception.
    bindings: dict[str, str] = {}
    for entity_id, matches in viable.items():
        if len(matches) != 1:
            if matches:
                rejections[entity_id] = [
                    f"ambiguous: matches {len(matches)} open exceptions"
                ]
            continue
        target = matches[0]
        rivals = [e for e, m in viable.items() if e != entity_id and target in m]
        if rivals:
            rejections[entity_id] = [
                f"ambiguous: {len(rivals) + 1} adjustments match one exception"
            ]
            continue
        bindings[target] = entity_id

    unmatched = sorted(e for e in viable if e not in bindings.values())
    return {
        "bindings": bindings,
        "unmatched_adjustments": unmatched,
        "rejections": rejections,
    }
