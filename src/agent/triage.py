"""Query triage — decide what a settlement query needs, before the merchant asks.

Four verdicts, in order of narrowing evidence:

- NO_ISSUE            settlement is verified; nothing to do.
- ALREADY_COMPENSATED a later adjustment already binds to the shortfall (lifecycle
                       matcher, six predicates, uniquely) — nothing to file.
- AUTO_COMPENSABLE    a clean, provable shortfall with no attempted or bound
                       adjustment yet. The agent may OFFER a compensation claim, but
                       every action still waits on an explicit merchant consent turn.
- NEEDS_SUPPORT       everything else: tax/semantic failures with no clean delta,
                       a settlement that never processed, an over-settlement (that's
                       Razorpay's recovery, not a merchant claim), or an adjustment
                       that references this settlement but doesn't cleanly reconcile.

A SETTLEMENT_TOTAL_MISMATCH proves the header disagrees with the recon lines — it
does not by itself prove Razorpay owes the merchant. AUTO_COMPENSABLE additionally
requires: exactly one failing control, real recon lines to compute the delta from, a
positive delta (the lines are short of the header), and no adjustment — bound,
ambiguous, or attempted-but-unreconciled — already in evidence for this settlement.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from src.domain.formatting import format_inr
from src.domain.models import (
    ControlStatus,
    ExceptionCode,
    SettlementBatch,
    SettlementCloseDecision,
    SettlementIntegrityStatus,
)
from src.lifecycle.identity import exception_id as make_exception_id
from src.lifecycle.matcher import candidate_reasons, match_adjustments
from src.lifecycle.projection import open_exceptions_from

_NO_REFERENCE_REASON = "no exact reference to the original settlement or UTR"


class TriageVerdict(str, Enum):
    NO_ISSUE = "NO_ISSUE"
    ALREADY_COMPENSATED = "ALREADY_COMPENSATED"
    AUTO_COMPENSABLE = "AUTO_COMPENSABLE"
    NEEDS_SUPPORT = "NEEDS_SUPPORT"


class TriageReason(str, Enum):
    NONE = "NONE"
    BOUND_ADJUSTMENT = "BOUND_ADJUSTMENT"
    CLEAN_SHORTFALL = "CLEAN_SHORTFALL"
    SETTLEMENT_FAILED = "SETTLEMENT_FAILED"
    MULTI_CONTROL_FAILURE = "MULTI_CONTROL_FAILURE"
    TAX_LINE_FAILURE = "TAX_LINE_FAILURE"
    NO_CLEAN_DELTA = "NO_CLEAN_DELTA"
    OVER_SETTLEMENT_RECOVERY = "OVER_SETTLEMENT_RECOVERY"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    ATTEMPTED_ADJUSTMENT_UNRECONCILED = "ATTEMPTED_ADJUSTMENT_UNRECONCILED"


class TriageResult(BaseModel):
    verdict: TriageVerdict
    reason: TriageReason
    settlement_id: str
    detail: str
    exception_id: str | None = None
    delta_paise: int = 0
    delta_display: str = ""
    matched_adjustment_id: str | None = None
    citations: list[str] = Field(default_factory=list)


def _needs_support(settlement_id: str, reason: TriageReason, detail: str, **kw) -> TriageResult:
    return TriageResult(
        verdict=TriageVerdict.NEEDS_SUPPORT,
        reason=reason,
        settlement_id=settlement_id,
        detail=detail,
        citations=kw.pop("citations", [settlement_id]),
        **kw,
    )


def _adjustment_evidence(
    settlement_id: str,
    exc_id: str,
    delta: int,
    all_batches: dict[str, SettlementBatch],
) -> TriageResult | None:
    """None means no adjustment evidence exists yet — the shortfall is untouched."""
    exceptions = open_exceptions_from(list(all_batches.values()))
    exc = next((e for e in exceptions if e.settlement_id == settlement_id), None)
    if exc is None:
        return None

    adjustments = [
        line
        for batch in all_batches.values()
        for line in batch.lines
        if line.line_type == "adjustment"
    ]
    bindings = match_adjustments(exceptions, adjustments)["bindings"]
    bound_entity = bindings.get(exc.exception_id)
    if bound_entity:
        return TriageResult(
            verdict=TriageVerdict.ALREADY_COMPENSATED,
            reason=TriageReason.BOUND_ADJUSTMENT,
            settlement_id=settlement_id,
            detail=f"This shortfall is already compensated by adjustment {bound_entity}.",
            exception_id=exc_id,
            delta_paise=delta,
            delta_display=format_inr(abs(delta)),
            matched_adjustment_id=bound_entity,
            citations=[settlement_id, bound_entity],
        )

    reasons_by_line = {
        line.entity_id: candidate_reasons(exc, line, exc.flagged_at, line.settled_at)
        for line in adjustments
    }
    full_matches = [eid for eid, reasons in reasons_by_line.items() if not reasons]
    if full_matches:
        return _needs_support(
            settlement_id,
            TriageReason.AMBIGUOUS_MATCH,
            "More than one adjustment cleanly matches this shortfall — needs a person to pick the right one.",
            exception_id=exc_id,
            delta_paise=delta,
            delta_display=format_inr(abs(delta)),
            citations=[settlement_id] + full_matches,
        )

    referencing = [
        (eid, reasons) for eid, reasons in reasons_by_line.items() if _NO_REFERENCE_REASON not in reasons
    ]
    if referencing:
        best_id, best_reasons = min(referencing, key=lambda pair: len(pair[1]))
        return _needs_support(
            settlement_id,
            TriageReason.ATTEMPTED_ADJUSTMENT_UNRECONCILED,
            f"An adjustment ({best_id}) references this settlement but doesn't cleanly reconcile: "
            f"{best_reasons[0]}.",
            exception_id=exc_id,
            delta_paise=delta,
            delta_display=format_inr(abs(delta)),
            matched_adjustment_id=best_id,
            citations=[settlement_id, best_id],
        )
    return None


def classify(
    settlement_id: str,
    batch: SettlementBatch,
    decision: SettlementCloseDecision,
    all_batches: dict[str, SettlementBatch],
) -> TriageResult:
    """Deterministic triage for one settlement's query, given every batch in scope.

    `all_batches` must include every settlement whose adjustment lines might reference
    this one — the caller's full dataset, not just this settlement's own batch.
    """
    if decision.integrity_status == SettlementIntegrityStatus.VERIFIED:
        return TriageResult(
            verdict=TriageVerdict.NO_ISSUE,
            reason=TriageReason.NONE,
            settlement_id=settlement_id,
            detail="This settlement is verified from your Razorpay data.",
            citations=[settlement_id],
        )

    controls = decision.control_decisions
    batch_ctrl = next((c for c in controls if c.control_type == "batch_integrity"), None)
    tax_ctrl = next((c for c in controls if c.control_type == "tax_lines"), None)
    failing = [c for c in controls if c.status != ControlStatus.PASS]

    if batch_ctrl is not None and batch_ctrl.exception_code == ExceptionCode.SETTLEMENT_FAILED:
        return _needs_support(
            settlement_id,
            TriageReason.SETTLEMENT_FAILED,
            "This settlement failed to process — no cash movement occurred.",
        )

    if len(failing) > 1:
        return _needs_support(
            settlement_id,
            TriageReason.MULTI_CONTROL_FAILURE,
            "More than one control failed on this settlement — needs a manual review.",
        )

    if tax_ctrl is not None and tax_ctrl.status != ControlStatus.PASS:
        return _needs_support(
            settlement_id,
            TriageReason.TAX_LINE_FAILURE,
            f"Fee/GST issue: {tax_ctrl.message}",
        )

    if batch_ctrl is None or batch_ctrl.status == ControlStatus.PASS:
        return _needs_support(settlement_id, TriageReason.NO_CLEAN_DELTA, decision.plain_issue or "Needs attention")

    if batch_ctrl.exception_code != ExceptionCode.SETTLEMENT_TOTAL_MISMATCH:
        return _needs_support(
            settlement_id,
            TriageReason.NO_CLEAN_DELTA,
            f"Batch issue without a clean settlement amount: {batch_ctrl.message}",
        )

    if not batch.lines:
        return _needs_support(
            settlement_id, TriageReason.NO_CLEAN_DELTA, "No recon lines to compute a compensable amount from."
        )

    delta = batch.amount - batch.net_from_lines
    if delta == 0:
        return _needs_support(settlement_id, TriageReason.NO_CLEAN_DELTA, "No numeric gap to compensate.")

    if delta < 0:
        return _needs_support(
            settlement_id,
            TriageReason.OVER_SETTLEMENT_RECOVERY,
            f"Your Razorpay data shows {format_inr(abs(delta))} more was settled than the header states — "
            "this needs Razorpay support to review; it isn't a claim the agent can file for you.",
        )

    exc_id = make_exception_id(settlement_id, "batch_integrity", delta)
    evidence = _adjustment_evidence(settlement_id, exc_id, delta, all_batches)
    if evidence is not None:
        return evidence

    return TriageResult(
        verdict=TriageVerdict.AUTO_COMPENSABLE,
        reason=TriageReason.CLEAN_SHORTFALL,
        settlement_id=settlement_id,
        detail=f"Confirmed short by {format_inr(delta)} against your Razorpay settlement header.",
        exception_id=exc_id,
        delta_paise=delta,
        delta_display=format_inr(delta),
        citations=[settlement_id] + [l.entity_id for l in batch.lines],
    )
