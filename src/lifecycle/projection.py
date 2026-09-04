"""Deterministic lifecycle projection over two immutable Razorpay cycles.

Recomputed on every run — there is no journal and no mutable state. A settlement's
historical integrity_status is never rewritten: its control genuinely failed at the time.
Only the operational exception closes, as compensated.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel

from src.controls.engine import validate_batch_integrity
from src.domain.formatting import format_inr
from src.domain.models import ControlStatus, ExceptionCode, SettlementBatch, SettlementLine
from src.lifecycle.identity import exception_id, signed_delta_paise
from src.lifecycle.matcher import OpenException, match_adjustments


class LifecycleState(str, Enum):
    OPEN = "OPEN"
    DISPUTED = "DISPUTED"
    CLOSED_COMPENSATED = "CLOSED_COMPENSATED"


class DisputePacket(BaseModel):
    exception_id: str
    settlement_id: str
    control_type: str
    delta_paise: int
    delta_display: str
    citations: list[str]
    evidence_hash: str


def open_exceptions_from(batches: list[SettlementBatch]) -> list[OpenException]:
    """Every batch-integrity failure with a clean signed delta, as an open exception."""
    out: list[OpenException] = []
    for batch in batches:
        if batch.status != "processed":
            continue
        ctrl = validate_batch_integrity(batch)
        if ctrl.status == ControlStatus.PASS:
            continue
        # Only total mismatches carry a compensable monetary delta. Semantic failures are
        # detected but not closable, and that limit is reported rather than hidden.
        if ctrl.exception_code != ExceptionCode.SETTLEMENT_TOTAL_MISMATCH:
            continue
        delta = signed_delta_paise(batch)
        if delta == 0:
            continue
        out.append(
            OpenException(
                exception_id=exception_id(batch.settlement_id, "batch_integrity", delta),
                settlement_id=batch.settlement_id,
                control_type="batch_integrity",
                delta_paise=delta,
                utr=batch.utr,
                flagged_at=batch.processed_at,
            )
        )
    return out


def dispute_packet(exc: OpenException, batch: SettlementBatch) -> DisputePacket:
    """Evidence a merchant can hand Razorpay support, hashed so it cannot drift."""
    citations = [batch.settlement_id] + [l.entity_id for l in batch.lines]
    payload = json.dumps(
        {
            "exception_id": exc.exception_id,
            "settlement_id": exc.settlement_id,
            "delta_paise": exc.delta_paise,
            "citations": citations,
        },
        sort_keys=True,
    )
    return DisputePacket(
        exception_id=exc.exception_id,
        settlement_id=exc.settlement_id,
        control_type=exc.control_type,
        delta_paise=exc.delta_paise,
        delta_display=format_inr(abs(exc.delta_paise)),
        citations=citations,
        evidence_hash=hashlib.sha256(payload.encode()).hexdigest()[:16],
    )


def project(
    cycle1_batches: list[SettlementBatch],
    cycle2_lines: list[SettlementLine],
) -> dict[str, Any]:
    """Replay both cycles into exception states. Never mutates its inputs."""
    exceptions = open_exceptions_from(cycle1_batches)
    by_id = {b.settlement_id: b for b in cycle1_batches}
    adjustments = [l for l in cycle2_lines if l.line_type == "adjustment"]

    result = match_adjustments(exceptions, adjustments)
    bindings = result["bindings"]
    lines_by_id = {l.entity_id: l for l in adjustments}

    rows: list[dict[str, Any]] = []
    for exc in exceptions:
        packet = dispute_packet(exc, by_id[exc.settlement_id])
        entity_id = bindings.get(exc.exception_id)
        days: int | None = None
        if entity_id:
            adj = lines_by_id[entity_id]
            if adj.settled_at and exc.flagged_at:
                days = (adj.settled_at.date() - exc.flagged_at.date()).days
        rows.append(
            {
                "exception_id": exc.exception_id,
                "settlement_id": exc.settlement_id,
                "control_type": exc.control_type,
                "delta_paise": exc.delta_paise,
                "delta_display": packet.delta_display,
                "state": (
                    LifecycleState.CLOSED_COMPENSATED if entity_id else LifecycleState.OPEN
                ),
                "matched_adjustment": entity_id,
                "days_to_close": days,
                "dispute_packet": packet.model_dump(),
            }
        )

    return {
        "exceptions": rows,
        "unmatched_adjustments": result["unmatched_adjustments"],
        "rejections": result["rejections"],
    }
