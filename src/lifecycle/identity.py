"""Stable identity for exceptions and adjustment references.

The lifecycle is recomputed from immutable feeds on every run, so an exception's identity
must be a function of its business facts. A uuid4 would produce a different id every run
and no transition could be tracked.
"""

from __future__ import annotations

import hashlib
import re

from src.domain.models import SettlementBatch

_SETTLEMENT_ID_RE = re.compile(r"\bsetl_[a-z0-9_]+\b", re.I)


def exception_id(settlement_id: str, control_type: str, delta_paise: int) -> str:
    """Deterministic identity from the facts that define the exception."""
    key = f"{settlement_id}|{control_type}|{delta_paise}"
    return "exc_" + hashlib.sha256(key.encode()).hexdigest()[:12]


def signed_delta_paise(batch: SettlementBatch) -> int:
    """Header minus recon lines. Positive means the lines are short of the header."""
    return batch.amount - batch.net_from_lines


def extract_reference_settlement_id(text: str | None) -> str | None:
    """The one settlement id named in free text, or None if zero or several are named."""
    found = {m.lower() for m in _SETTLEMENT_ID_RE.findall(text or "")}
    return next(iter(found)) if len(found) == 1 else None
