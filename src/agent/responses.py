"""Structured assistant responses and deterministic contextual actions."""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.domain.models import (
    AnswerEnvelope,
    AssistantAction,
    AssistantActionKind,
    AssistantResponse,
    AssistantResponseBlock,
    AssistantResponseBlockKind,
    AssistantSubjectKind,
)

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z₹])")


def action(
    action_id: str,
    kind: AssistantActionKind,
    label: str,
    *,
    style: str = "secondary",
    icon: str | None = None,
    enabled: bool = True,
    disabled_reason: str | None = None,
    requires_confirmation: bool = False,
    payload: dict | None = None,
) -> AssistantAction:
    """Build a typed action with a stable, caller-owned identifier."""
    return AssistantAction(
        action_id=action_id,
        kind=kind,
        label=label,
        style=style,
        icon=icon,
        enabled=enabled,
        disabled_reason=disabled_reason,
        requires_confirmation=requires_confirmation,
        payload=payload or {},
    )


def _text_parts(text: str) -> tuple[str, list[str]]:
    """Turn legacy paragraph output into a direct answer plus scannable details."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return "I could not build an answer from the available data.", []

    first_sentences = [p.strip() for p in _SENTENCE_BOUNDARY.split(paragraphs[0]) if p.strip()]
    summary = first_sentences[0]
    details = first_sentences[1:] + paragraphs[1:]

    expanded: list[str] = []
    for detail in details:
        lines = [line.strip(" -") for line in detail.splitlines() if line.strip(" -")]
        expanded.extend(lines)
    return summary, expanded


def _heading(envelope: AnswerEnvelope, subject_kind: AssistantSubjectKind) -> str:
    if envelope.support_ticket_id:
        return "Support ticket raised"
    if envelope.compensation_claim_id:
        return "Compensation claim submitted"
    if envelope.offer_compensation:
        return "Confirmed shortfall found"
    if envelope.offer_raise_ticket:
        return "Support can take this forward"
    if envelope.abstained:
        return "I need more information"
    if subject_kind == AssistantSubjectKind.PENDING_PAYMENT:
        return "Payment update"
    if subject_kind == AssistantSubjectKind.PENDING_PAYMENT_SET:
        return "Unsettled payments summary"
    return "Settlement update"


def _subject_action(
    subject_kind: AssistantSubjectKind,
    subject_ids: list[str],
) -> AssistantAction | None:
    if not subject_ids:
        return None
    subject_id = subject_ids[0]
    if subject_kind == AssistantSubjectKind.SETTLEMENT:
        return action(
            f"view-settlement:{subject_id}",
            AssistantActionKind.VIEW_SETTLEMENT,
            "View settlement",
            icon=":material/visibility:",
            payload={"subject_id": subject_id},
        )
    if subject_kind == AssistantSubjectKind.PENDING_PAYMENT:
        return action(
            f"view-payment:{subject_id}",
            AssistantActionKind.VIEW_PAYMENT,
            "View payment",
            icon=":material/visibility:",
            payload={"subject_id": subject_id},
        )
    return None


def _contextual_actions(
    envelope: AnswerEnvelope,
    subject_kind: AssistantSubjectKind,
    subject_ids: list[str],
    *,
    force_ticket: bool,
    instant_quote_available: bool,
) -> list[AssistantAction]:
    subject_key = ",".join(subject_ids) or "general"
    actions: list[AssistantAction] = []

    if envelope.compensation_claim_id:
        actions.append(
            action(
                f"track-claim:{envelope.compensation_claim_id}",
                AssistantActionKind.TRACK_STATUS,
                "Track claim",
                icon=":material/track_changes:",
                payload={"record_id": envelope.compensation_claim_id, "record_type": "claim"},
            )
        )
    elif envelope.support_ticket_id:
        actions.append(
            action(
                f"track-ticket:{envelope.support_ticket_id}",
                AssistantActionKind.TRACK_STATUS,
                "Track ticket",
                icon=":material/track_changes:",
                payload={"record_id": envelope.support_ticket_id, "record_type": "ticket"},
            )
        )
    else:
        if envelope.offer_compensation:
            actions.append(
                action(
                    f"submit-claim:{subject_key}",
                    AssistantActionKind.SUBMIT_CLAIM,
                    "Submit claim",
                    style="primary",
                    icon=":material/request_quote:",
                    requires_confirmation=True,
                    payload={"subject_ids": subject_ids},
                )
            )
        if envelope.offer_raise_ticket or envelope.abstained or force_ticket:
            actions.append(
                action(
                    f"raise-ticket:{subject_key}",
                    AssistantActionKind.RAISE_TICKET,
                    "Raise ticket",
                    style="primary" if not actions else "secondary",
                    icon=":material/support_agent:",
                    requires_confirmation=True,
                    payload={"subject_kind": subject_kind.value, "subject_ids": subject_ids},
                )
            )
        if instant_quote_available:
            actions.append(
                action(
                    f"instant-quote:{subject_key}",
                    AssistantActionKind.GET_INSTANT_SETTLEMENT_QUOTE,
                    "Review instant settlement",
                    style="primary" if not actions else "secondary",
                    icon=":material/bolt:",
                    payload={"subject_ids": subject_ids},
                )
            )

    view_action = _subject_action(subject_kind, subject_ids)
    if view_action is not None and len(actions) < 3:
        actions.append(view_action)
    return actions[:3]


def response_from_envelope(
    envelope: AnswerEnvelope,
    subject_kind: AssistantSubjectKind,
    subject_ids: Iterable[str] = (),
    *,
    force_ticket: bool = False,
    instant_quote_available: bool = False,
) -> AssistantResponse:
    """Adapt a validated legacy answer without inferring actions from its prose."""
    ids = list(subject_ids)
    summary, details = _text_parts(envelope.answer_text)
    blocks: list[AssistantResponseBlock] = []
    if details:
        blocks.append(
            AssistantResponseBlock(
                kind=AssistantResponseBlockKind.DETAILS,
                title="Details",
                items=details,
            )
        )
    if envelope.citations:
        blocks.append(
            AssistantResponseBlock(
                kind=AssistantResponseBlockKind.EVIDENCE,
                title="Evidence used",
                items=list(dict.fromkeys(envelope.citations)),
            )
        )

    contextual_actions = _contextual_actions(
        envelope,
        subject_kind,
        ids,
        force_ticket=force_ticket,
        instant_quote_available=instant_quote_available,
    )
    next_step: str | None = None
    if any(a.kind == AssistantActionKind.SUBMIT_CLAIM for a in contextual_actions):
        next_step = "Review the confirmed shortfall, then choose whether to submit a claim or contact support."
    elif any(a.kind == AssistantActionKind.RAISE_TICKET for a in contextual_actions):
        next_step = "Review a prefilled support request. Nothing is sent until you confirm it."
    elif any(a.kind == AssistantActionKind.GET_INSTANT_SETTLEMENT_QUOTE for a in contextual_actions):
        next_step = "Review availability and amount semantics before requesting an Instant Settlement."
    if next_step:
        blocks.append(
            AssistantResponseBlock(
                kind=AssistantResponseBlockKind.NEXT_STEP,
                title="Recommended next step",
                body=next_step,
            )
        )

    return AssistantResponse(
        heading=_heading(envelope, subject_kind),
        summary=summary,
        blocks=blocks,
        citations=list(dict.fromkeys(envelope.citations)),
        actions=contextual_actions,
        agent_mode=envelope.agent_mode,
        ask_resolution=not bool(envelope.support_ticket_id or envelope.compensation_claim_id),
    )


def simple_response(
    heading: str,
    summary: str,
    *,
    details: Iterable[str] = (),
    next_step: str | None = None,
    actions: Iterable[AssistantAction] = (),
    ask_resolution: bool = False,
    agent_mode: str = "keyword",
) -> AssistantResponse:
    blocks: list[AssistantResponseBlock] = []
    detail_items = [item for item in details if item]
    if detail_items:
        blocks.append(
            AssistantResponseBlock(
                kind=AssistantResponseBlockKind.DETAILS,
                title="Details",
                items=detail_items,
            )
        )
    if next_step:
        blocks.append(
            AssistantResponseBlock(
                kind=AssistantResponseBlockKind.NEXT_STEP,
                title="Next step",
                body=next_step,
            )
        )
    return AssistantResponse(
        heading=heading,
        summary=summary,
        blocks=blocks,
        actions=list(actions),
        ask_resolution=ask_resolution,
        agent_mode=agent_mode,
    )
