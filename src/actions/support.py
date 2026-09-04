"""Deterministic support handoff helpers for non-settlement subjects."""

from __future__ import annotations

import hashlib

from src.domain.models import AnswerEnvelope, AssistantSubjectKind


def raise_general_support_ticket(
    subject_kind: AssistantSubjectKind,
    subject_ids: list[str],
    merchant_summary: str,
    facts: list[str],
) -> AnswerEnvelope:
    """Create an idempotent simulated support record from already collected facts."""
    normalized_ids = list(dict.fromkeys(subject_ids))
    identity = f"{subject_kind.value}:{','.join(normalized_ids)}:{merchant_summary.strip().lower()}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:8]
    ticket_id = f"RZP-SUP-{digest.upper()}"

    subject_label = subject_kind.value.replace("_", " ")
    facts_text = "\n".join(f"- {fact}" for fact in facts if fact)
    text = (
        "A support ticket has been raised and escalated to the Razorpay support team.\n\n"
        f"Ticket ID: {ticket_id}\n"
        f"Subject: {subject_label}\n"
        f"Records: {', '.join(normalized_ids) if normalized_ids else 'No record selected'}\n\n"
        f"Information sent:\n{facts_text or '- Merchant requested support from the universal assistant.'}\n\n"
        "This demo creates an idempotent support record; it does not move money or change reconciliation status."
    )
    return AnswerEnvelope(
        answer_text=text,
        citations=normalized_ids,
        escalated_to_support=True,
        support_ticket_id=ticket_id,
        tool_trace=["raise_general_support_ticket"],
        agent_mode="keyword",
    )
