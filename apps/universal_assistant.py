"""Universal guided and free-text assistant UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

from src.actions.support import raise_general_support_ticket
from src.agent.conversation import (
    FREE_TEXT,
    FUNDS_ALL,
    FUNDS_MANY,
    FUNDS_ONE,
    HOME,
    ISSUE_PAYMENT,
    ISSUE_SETTLEMENT,
    ISSUE_SUBJECT,
    PENDING_ALL,
    PENDING_MANY,
    PENDING_ONE,
    PENDING_ONE_CUSTOM_QUESTION,
    PENDING_ONE_QUESTIONS,
    SETTLEMENT_SELECT,
    SETTLEMENT_CUSTOM_QUESTION,
    SETTLEMENT_QUESTIONS,
    append_response,
    append_user,
    change_subject_selection,
    confirm_subject_selection,
    go_back,
    go_home,
    initial_session,
    is_greeting,
    navigate,
    node_response,
    recent_subject_context,
    set_last_intent,
    set_subject,
)
from src.agent.responses import action, response_from_envelope, simple_response
from src.agent.settlement_qa import (
    PRESET_INTENTS,
    answer_free_text,
    answer_pending_query,
    answer_preset,
    filter_response_text,
    last_llm_error,
    resolve_conversation_intent,
    route_pending_query,
    raise_support_ticket,
    route_free_text,
    submit_compensation_claim,
)
from src.agent.triage import TriageVerdict, classify as classify_triage
from src.domain.formatting import format_inr
from src.domain.models import (
    AnswerEnvelope,
    AssistantAction,
    AssistantActionKind,
    AssistantResponse,
    AssistantResponseBlock,
    AssistantResponseBlockKind,
    AssistantSession,
    AssistantSubjectKind,
    AssistantTranscriptMessage,
    PendingPayment,
    SettlementBatch,
    SettlementCloseDecision,
    SettlementIntegrityStatus,
)

SESSION_KEY = "universal_assistant_session"
OPEN_KEY = "universal_assistant_open"


@dataclass(frozen=True)
class AssistantDataContext:
    batches: dict[str, SettlementBatch]
    decisions: dict[str, SettlementCloseDecision]
    pending_payments: dict[str, PendingPayment]
    use_llm: bool


def _session() -> AssistantSession:
    current = st.session_state.get(SESSION_KEY)
    if isinstance(current, AssistantSession):
        return current
    if isinstance(current, dict):
        current = AssistantSession.model_validate(current)
    else:
        current = initial_session()
    st.session_state[SESSION_KEY] = current
    return current


def _save(session: AssistantSession) -> None:
    st.session_state[SESSION_KEY] = session


def _dialog_rerun() -> None:
    # A full rerun is intentional: OPEN_KEY reopens the dialog, and this works both
    # during an initial app run and during later dialog-fragment interactions.
    st.rerun(scope="app")


def _close_assistant() -> None:
    st.session_state[OPEN_KEY] = False


def _clean_envelope(envelope: AnswerEnvelope) -> AnswerEnvelope:
    return envelope.model_copy(update={"answer_text": filter_response_text(envelope.answer_text)})


def _append_exchange(
    question: str,
    response: AssistantResponse,
    *,
    subject_kind: AssistantSubjectKind | None = None,
    subject_ids: list[str] | None = None,
    last_intent: str | None = None,
) -> None:
    session = append_user(_session(), question)
    if subject_kind is not None:
        session = set_subject(session, subject_kind, subject_ids or [])
    if last_intent is not None:
        session = set_last_intent(session, last_intent)
    session = append_response(session, response)
    _save(session)


def _decision_for(context: AssistantDataContext, settlement_id: str) -> SettlementCloseDecision | None:
    return context.decisions.get(settlement_id)


def _settlement_status_and_date(
    context: AssistantDataContext,
    settlement_id: str,
) -> tuple[str, str]:
    """Return the merchant-facing reconciliation status and settlement date."""
    batch = context.batches[settlement_id]
    decision = _decision_for(context, settlement_id)
    status = (
        "Verified"
        if decision and decision.integrity_status == SettlementIntegrityStatus.VERIFIED
        else "Needs attention"
    )
    processed_at = (decision.processed_at if decision else None) or batch.processed_at
    date_label = processed_at.strftime("%d %b %Y") if processed_at else "Date unavailable"
    return status, date_label


def _settlement_option_label(context: AssistantDataContext, settlement_id: str) -> str:
    status, date_label = _settlement_status_and_date(context, settlement_id)
    batch = context.batches[settlement_id]
    status_indicator = "🟢 Verified" if status == "Verified" else "🔴 Needs attention"
    return f"{format_inr(batch.amount)} · {date_label} · {status_indicator} · {settlement_id}"


def _sorted_settlement_ids(context: AssistantDataContext) -> list[str]:
    """Show attention items first, then newest settlement date within each group."""

    def sort_key(settlement_id: str) -> tuple[bool, int, str]:
        status, _ = _settlement_status_and_date(context, settlement_id)
        batch = context.batches[settlement_id]
        decision = _decision_for(context, settlement_id)
        processed_at = (decision.processed_at if decision else None) or batch.processed_at
        date_ordinal = processed_at.date().toordinal() if processed_at else 0
        return status == "Verified", -date_ordinal, settlement_id

    return sorted(context.batches, key=sort_key)


def _with_settlement_context(
    response: AssistantResponse,
    context: AssistantDataContext,
    settlement_id: str,
) -> AssistantResponse:
    """Put identity, status, and date at the top of every settlement answer."""
    status, date_label = _settlement_status_and_date(context, settlement_id)
    status_badge = ":green-badge[Verified]" if status == "Verified" else ":red-badge[Needs attention]"
    enriched = response.model_copy(deep=True)
    enriched.blocks.insert(
        0,
        AssistantResponseBlock(
            kind=AssistantResponseBlockKind.DETAILS,
            title="Settlement details",
            items=[
                f"Settlement: {settlement_id}",
                f"Status: {status_badge}",
                f"Date: {date_label}",
            ],
        ),
    )
    return enriched


def _settlement_response(
    context: AssistantDataContext,
    settlement_id: str,
    question: str,
    preset_id: str | None = None,
    conversation_context: list[dict[str, str]] | None = None,
    previous_intent: str | None = None,
    ticket_offer_pending: bool = False,
    compensation_offer_pending: bool = False,
) -> AssistantResponse:
    decision = _decision_for(context, settlement_id)
    raised = st.session_state.get("raised_tickets", {}).get(settlement_id)
    filed = st.session_state.get("filed_claims", {}).get(settlement_id)
    if preset_id:
        envelope = answer_preset(preset_id, settlement_id, context.batches)
        force_ticket = False
    else:
        envelope = answer_free_text(
            question,
            settlement_id,
            context.batches,
            use_llm=context.use_llm,
            settlement_decision=decision,
            raised_ticket_id=getattr(raised, "support_ticket_id", None),
            ticket_offer_pending=ticket_offer_pending,
            raised_claim_id=getattr(filed, "compensation_claim_id", None),
            compensation_offer_pending=compensation_offer_pending,
            conversation_context=conversation_context,
            previous_intent=previous_intent,
        )
        force_ticket = resolve_conversation_intent(
            question,
            settlement_id,
            previous_intent,
            ticket_offer_pending,
            compensation_offer_pending,
        ) == "escalate"

    updates: dict[str, Any] = {}
    if getattr(filed, "compensation_claim_id", None):
        updates["compensation_claim_id"] = filed.compensation_claim_id
    elif getattr(raised, "support_ticket_id", None):
        updates["support_ticket_id"] = raised.support_ticket_id
    elif decision and settlement_id in context.batches:
        triage = classify_triage(
            settlement_id,
            context.batches[settlement_id],
            decision,
            context.batches,
        )
        updates["triage_verdict"] = triage.verdict.value
        if triage.verdict == TriageVerdict.AUTO_COMPENSABLE:
            updates["offer_compensation"] = True
            updates["offer_raise_ticket"] = True
            updates["compensation_amount_display"] = triage.delta_display
        elif triage.verdict == TriageVerdict.NEEDS_SUPPORT:
            updates["offer_raise_ticket"] = True
    if updates:
        envelope = envelope.model_copy(update=updates)

    response = response_from_envelope(
        _clean_envelope(envelope),
        AssistantSubjectKind.SETTLEMENT,
        [settlement_id],
        force_ticket=force_ticket,
    )
    fallback = last_llm_error() if context.use_llm and envelope.agent_mode == "keyword" else None
    if fallback:
        response.blocks.append(
            _warning_block(
                "AI fallback",
                f"The model answer was not used ({fallback}). This answer came from verified rules.",
            )
        )
    return _with_settlement_context(response, context, settlement_id)


def _warning_block(title: str, body: str):
    return AssistantResponseBlock(
        kind=AssistantResponseBlockKind.WARNING,
        title=title,
        body=body,
    )


def _pending_response(
    payment: PendingPayment,
    question: str,
    *,
    previous_intent: str | None = None,
) -> AssistantResponse:
    direct_ticket = route_free_text(question, None) == "escalate"
    if direct_ticket:
        envelope = AnswerEnvelope(
            answer_text=(
                f"I can prepare a support request for payment {payment.entity_id}. "
                "Its loaded payment facts will be attached automatically."
            ),
            citations=[payment.entity_id],
            offer_raise_ticket=True,
            agent_mode="keyword",
        )
    else:
        envelope = answer_pending_query(payment, question, previous_intent=previous_intent)
    return response_from_envelope(
        _clean_envelope(envelope),
        AssistantSubjectKind.PENDING_PAYMENT,
        [payment.entity_id],
        force_ticket=direct_ticket,
        instant_quote_available=payment.instant_eligible == "yes" and "instant" in question.lower(),
    )


def _aggregate_pending_response(
    payments: list[PendingPayment],
    *,
    instant_focus: bool,
) -> AssistantResponse:
    ids = [payment.entity_id for payment in payments]
    total = sum(payment.amount for payment in payments)
    eligible = sum(payment.instant_eligible == "yes" for payment in payments)
    unknown = sum(payment.instant_eligible == "unknown" for payment in payments)
    dated = [p.expected_settlement_at for p in payments if p.expected_settlement_at]
    details = [
        f"Payments selected: {len(payments)}",
        f"Combined captured amount: {format_inr(total)}",
        f"Instant Settlement eligible in loaded data: {eligible}",
    ]
    if unknown:
        details.append(f"Eligibility unknown: {unknown}")
    if dated:
        details.append(f"Latest loaded expected date: {max(dated).strftime('%d %b %Y')}")
    if not payments:
        return simple_response(
            "No unsettled payments found",
            "There are no payments in this scope to summarize.",
            actions=(
                action(
                    "raise-ticket:empty-pending",
                    AssistantActionKind.RAISE_TICKET,
                    "Raise ticket",
                    icon=":material/support_agent:",
                    requires_confirmation=True,
                    payload={"subject_kind": AssistantSubjectKind.ACCOUNT.value, "subject_ids": []},
                ),
            ),
        )

    envelope = AnswerEnvelope(
        answer_text=(
            f"{len(payments)} unsettled payments total {format_inr(total)}. "
            "The selected payment IDs are only an amount basis; Instant Settlement uses your available Razorpay balance."
            if instant_focus
            else f"{len(payments)} payments are currently unsettled with a combined captured amount of {format_inr(total)}."
        ),
        citations=ids,
        agent_mode="keyword",
    )
    response = response_from_envelope(
        envelope,
        AssistantSubjectKind.PENDING_PAYMENT_SET,
        ids,
        instant_quote_available=instant_focus and eligible > 0,
    )
    response.blocks.insert(
        0,
        _details_block(details),
    )
    return response


def _details_block(items: list[str]):
    return AssistantResponseBlock(
        kind=AssistantResponseBlockKind.DETAILS,
        title="Summary",
        items=items,
    )


def _resolve_subject_from_text(
    question: str,
    context: AssistantDataContext,
) -> tuple[AssistantSubjectKind, list[str]] | None:
    query = question.lower()
    settlement_hits = [
        sid
        for sid, batch in context.batches.items()
        if sid.lower() in query or (batch.utr and batch.utr.lower() in query)
    ]
    payment_hits = [
        payment.entity_id
        for payment in context.pending_payments.values()
        if payment.entity_id.lower() in query
        or bool(payment.order_id and payment.order_id.lower() in query)
    ]
    if len(settlement_hits) == 1 and not payment_hits:
        return AssistantSubjectKind.SETTLEMENT, settlement_hits
    if len(payment_hits) == 1 and not settlement_hits:
        return AssistantSubjectKind.PENDING_PAYMENT, payment_hits
    return None


def _latest_offer_flags(session: AssistantSession) -> tuple[bool, bool]:
    """Return typed offers from the latest assistant answer for short follow-ups."""
    for message in reversed(session.messages):
        if message.role != "assistant" or message.response is None:
            continue
        kinds = {choice.kind for choice in message.response.actions if choice.enabled}
        return (
            AssistantActionKind.RAISE_TICKET in kinds,
            AssistantActionKind.SUBMIT_CLAIM in kinds,
        )
    return False, False


def _handle_free_text(question: str, context: AssistantDataContext) -> None:
    session = _session()
    if is_greeting(question):
        updated = append_user(session, question)
        updated = go_home(updated, record_choice=False)
        _save(updated)
        return

    resolved = _resolve_subject_from_text(question, context)
    active = (session.subject_kind, session.subject_ids)
    if (
        resolved
        and session.subject_kind != AssistantSubjectKind.NONE
        and resolved != active
    ):
        current = ", ".join(session.subject_ids)
        mentioned = ", ".join(resolved[1])
        response = simple_response(
            "Confirm the record change",
            (
                f"You’re currently asking about {current}, but this message mentions {mentioned}. "
                "Choose Change selection before switching records so earlier context is not mixed."
            ),
        )
        _append_exchange(question, response)
        return
    if resolved:
        kind, ids = resolved
    else:
        kind, ids = session.subject_kind, session.subject_ids

    if kind == AssistantSubjectKind.SETTLEMENT and ids and ids[0] in context.batches:
        conversation_context = recent_subject_context(session)
        ticket_pending, compensation_pending = _latest_offer_flags(session)
        response = _settlement_response(
            context,
            ids[0],
            question,
            conversation_context=conversation_context,
            previous_intent=session.last_intent,
            ticket_offer_pending=ticket_pending,
            compensation_offer_pending=compensation_pending,
        )
        _append_exchange(
            question,
            response,
            subject_kind=kind,
            subject_ids=ids,
            last_intent=resolve_conversation_intent(
                question,
                ids[0],
                session.last_intent,
                ticket_pending,
                compensation_pending,
            ),
        )
        return
    if kind == AssistantSubjectKind.PENDING_PAYMENT and ids and ids[0] in context.pending_payments:
        response = _pending_response(
            context.pending_payments[ids[0]],
            question,
            previous_intent=session.last_intent,
        )
        _append_exchange(
            question,
            response,
            subject_kind=kind,
            subject_ids=ids,
            last_intent=route_pending_query(question, session.last_intent),
        )
        return

    direct_support = route_free_text(question, None) == "escalate"
    response = simple_response(
        "Choose a record first",
        (
            "Tell me which settlement or unsettled payment this support request concerns."
            if direct_support
            else "I could not identify a unique payment or settlement from that message. Choose a path below, or include its ID."
        ),
        actions=(
            action(
                "navigate:settlement_select",
                AssistantActionKind.NAVIGATE,
                "Choose settlement",
                icon=":material/receipt_long:",
                payload={"target": SETTLEMENT_SELECT},
            ),
            action(
                "navigate:pending_one",
                AssistantActionKind.NAVIGATE,
                "Choose unsettled payment",
                icon=":material/schedule:",
                payload={"target": PENDING_ONE},
            ),
        ),
    )
    _append_exchange(question, response)


def _ticket_preview(session: AssistantSession, context: AssistantDataContext) -> AssistantResponse:
    subject_label = session.subject_kind.value.replace("_", " ")
    records = ", ".join(session.subject_ids) if session.subject_ids else "No record selected"
    response = simple_response(
        "Review support request",
        "I will attach the facts already loaded for this conversation. Nothing is sent until you confirm.",
        details=(f"Subject: {subject_label}", f"Records: {records}"),
        actions=(
            action(
                "confirm-ticket",
                AssistantActionKind.CONFIRM_TICKET,
                "Confirm and raise ticket",
                style="primary",
                icon=":material/send:",
            ),
            action(
                "cancel-ticket",
                AssistantActionKind.CANCEL,
                "Cancel",
                style="tertiary",
            ),
        ),
    )
    if session.subject_kind == AssistantSubjectKind.SETTLEMENT and session.subject_ids:
        sid = session.subject_ids[0]
        if sid in context.batches:
            return _with_settlement_context(response, context, sid)
    return response


def _claim_preview(session: AssistantSession, context: AssistantDataContext) -> AssistantResponse:
    sid = session.subject_ids[0] if session.subject_ids else ""
    decision = context.decisions.get(sid)
    triage = (
        classify_triage(sid, context.batches[sid], decision, context.batches)
        if sid in context.batches and decision
        else None
    )
    if triage is None or triage.verdict != TriageVerdict.AUTO_COMPENSABLE:
        response = simple_response(
            "Claim is not currently available",
            "The latest deterministic checks do not show an auto-compensable shortfall.",
            next_step="You can still ask support to review the issue.",
            actions=(
                action(
                    f"raise-ticket:{sid or 'general'}",
                    AssistantActionKind.RAISE_TICKET,
                    "Raise ticket",
                    style="primary",
                    icon=":material/support_agent:",
                    requires_confirmation=True,
                ),
            ),
        )
        return (
            _with_settlement_context(response, context, sid)
            if sid in context.batches
            else response
        )
    response = simple_response(
        "Review compensation claim",
        "This files a claim with Razorpay; it does not move money or change your ledger.",
        details=(f"Confirmed shortfall: {triage.delta_display}", triage.detail),
        actions=(
            action(
                "confirm-claim",
                AssistantActionKind.CONFIRM_CLAIM,
                "Confirm and submit claim",
                style="primary",
                icon=":material/send:",
            ),
            action("cancel-claim", AssistantActionKind.CANCEL, "Cancel", style="tertiary"),
        ),
    )
    return _with_settlement_context(response, context, sid)


def _ticket_facts(session: AssistantSession, context: AssistantDataContext) -> list[str]:
    if session.subject_kind == AssistantSubjectKind.PENDING_PAYMENT and session.subject_ids:
        payment = context.pending_payments.get(session.subject_ids[0])
        if payment:
            return [
                f"Amount: {format_inr(payment.amount)}",
                f"Captured: {payment.captured_at.strftime('%d %b %Y')}",
                f"Expected settlement: {payment.expected_settlement_at.strftime('%d %b %Y') if payment.expected_settlement_at else 'Unknown'}",
                f"Instant eligibility: {payment.instant_eligible}",
            ]
    if session.subject_kind == AssistantSubjectKind.PENDING_PAYMENT_SET:
        payments = [context.pending_payments[sid] for sid in session.subject_ids if sid in context.pending_payments]
        return [
            f"Payments: {len(payments)}",
            f"Combined amount: {format_inr(sum(p.amount for p in payments))}",
        ]
    return ["Merchant requested support from the universal assistant."]


def _confirm_ticket(context: AssistantDataContext) -> None:
    session = _session()
    if session.subject_kind == AssistantSubjectKind.SETTLEMENT and session.subject_ids:
        sid = session.subject_ids[0]
        decision = context.decisions.get(sid)
        if sid in context.batches and decision:
            envelope = raise_support_ticket(sid, decision, context.batches)
        else:
            envelope = raise_general_support_ticket(
                session.subject_kind, session.subject_ids, "Universal assistant handoff", []
            )
    else:
        envelope = raise_general_support_ticket(
            session.subject_kind,
            session.subject_ids,
            "Universal assistant handoff",
            _ticket_facts(session, context),
        )
    key = session.subject_ids[0] if session.subject_ids else "account"
    st.session_state.setdefault("raised_tickets", {})[key] = envelope
    updated = append_user(session, "Confirm and raise ticket")
    updated.pending_action = None
    response = response_from_envelope(envelope, session.subject_kind, session.subject_ids)
    if (
        session.subject_kind == AssistantSubjectKind.SETTLEMENT
        and session.subject_ids
        and session.subject_ids[0] in context.batches
    ):
        response = _with_settlement_context(response, context, session.subject_ids[0])
    updated = append_response(
        updated,
        response,
    )
    _save(updated)


def _confirm_claim(context: AssistantDataContext) -> None:
    session = _session()
    sid = session.subject_ids[0] if session.subject_ids else ""
    decision = context.decisions.get(sid)
    if not sid or sid not in context.batches or not decision:
        response = simple_response("Claim could not be submitted", "The selected settlement is no longer available.")
    else:
        triage = classify_triage(sid, context.batches[sid], decision, context.batches)
        if triage.verdict != TriageVerdict.AUTO_COMPENSABLE:
            response = simple_response(
                "Claim is no longer available",
                "The latest reconciliation evidence no longer permits an automatic compensation claim.",
            )
            response = _with_settlement_context(response, context, sid)
        else:
            envelope = submit_compensation_claim(sid, triage, context.batches)
            st.session_state.setdefault("filed_claims", {})[sid] = envelope
            response = response_from_envelope(
                envelope, AssistantSubjectKind.SETTLEMENT, [sid]
            )
            response = _with_settlement_context(response, context, sid)
    updated = append_user(session, "Confirm and submit claim")
    updated.pending_action = None
    _save(append_response(updated, response))


def _handle_action(chosen: AssistantAction, context: AssistantDataContext) -> None:
    session = _session()
    kind = chosen.kind
    if kind == AssistantActionKind.NAVIGATE:
        _save(navigate(session, str(chosen.payload.get("target", HOME)), chosen.label))
        _dialog_rerun()
    if kind == AssistantActionKind.RAISE_TICKET:
        if session.subject_kind == AssistantSubjectKind.NONE:
            _save(navigate(session, ISSUE_SUBJECT, "Talk to support"))
        else:
            updated = append_user(session, chosen.label)
            updated.pending_action = chosen
            _save(append_response(updated, _ticket_preview(updated, context)))
        _dialog_rerun()
    if kind == AssistantActionKind.CONFIRM_TICKET:
        _confirm_ticket(context)
        _dialog_rerun()
    if kind == AssistantActionKind.SUBMIT_CLAIM:
        updated = append_user(session, chosen.label)
        updated.pending_action = chosen
        _save(append_response(updated, _claim_preview(updated, context)))
        _dialog_rerun()
    if kind == AssistantActionKind.CONFIRM_CLAIM:
        _confirm_claim(context)
        _dialog_rerun()
    if kind == AssistantActionKind.CANCEL:
        updated = append_user(session, "Cancel")
        updated.pending_action = None
        updated = append_response(
            updated,
            simple_response("Action cancelled", "Nothing was submitted. You can keep asking questions."),
        )
        _save(updated)
        _dialog_rerun()
    if kind in {AssistantActionKind.VIEW_SETTLEMENT, AssistantActionKind.VIEW_PAYMENT}:
        st.session_state["assistant_focus_request"] = {
            "kind": "settlement" if kind == AssistantActionKind.VIEW_SETTLEMENT else "payment",
            "subject_id": chosen.payload.get("subject_id"),
        }
        st.session_state[OPEN_KEY] = False
        st.rerun(scope="app")
    if kind == AssistantActionKind.GET_INSTANT_SETTLEMENT_QUOTE:
        updated = append_user(session, chosen.label)
        response = simple_response(
            "Live Instant Settlement quote is not connected",
            "The loaded data can show eligibility and an amount basis, but this app does not yet have account balance, limit, fee, or create access.",
            next_step="Use Razorpay's Instant Settlements area, or raise a support request if the option is unavailable there.",
            actions=(
                action(
                    "raise-ticket:instant-settlement",
                    AssistantActionKind.RAISE_TICKET,
                    "Raise ticket",
                    style="primary",
                    icon=":material/support_agent:",
                    requires_confirmation=True,
                ),
            ),
        )
        _save(append_response(updated, response))
        _dialog_rerun()
    if kind == AssistantActionKind.TRACK_STATUS:
        record_id = str(chosen.payload.get("record_id", ""))
        record_type = str(chosen.payload.get("record_type", "request"))
        updated = append_user(session, chosen.label)
        response = simple_response(
            f"{record_type.capitalize()} status",
            f"{record_id} is submitted in this demo session.",
            next_step="Keep this ID when following up with Razorpay support.",
        )
        _save(append_response(updated, response))
        _dialog_rerun()
    if kind == AssistantActionKind.MARK_RESOLVED:
        updated = append_user(session, "Yes, resolved")
        updated.resolution_status = "resolved"
        response = simple_response(
            "Glad that helped",
            "You can return to the main menu or type another question at any time.",
        )
        _save(append_response(updated, response))
        _dialog_rerun()
    if kind == AssistantActionKind.NEED_MORE_HELP:
        updated = append_user(session, "No, I still need help")
        response = simple_response(
            "Let’s get more help",
            "You can send the current subject and evidence to support without entering it again.",
            actions=(
                action(
                    f"raise-ticket:{','.join(session.subject_ids) or 'general'}",
                    AssistantActionKind.RAISE_TICKET,
                    "Raise ticket",
                    style="primary",
                    icon=":material/support_agent:",
                    requires_confirmation=True,
                ),
            ),
        )
        _save(append_response(updated, response))
        _dialog_rerun()


def _render_block(block) -> None:
    if block.kind == AssistantResponseBlockKind.WARNING:
        st.warning(block.body or "", icon=":material/warning:")
        return
    if block.title:
        st.markdown(f"**{block.title}**")
    if block.body:
        st.write(block.body)
    if block.items:
        if block.kind == AssistantResponseBlockKind.EVIDENCE:
            st.caption(" · ".join(block.items))
        else:
            st.markdown("\n".join(f"- {item}" for item in block.items))
    if block.rows:
        st.table(block.rows)


def _render_response(
    response: AssistantResponse,
    *,
    interactive: bool,
    context: AssistantDataContext,
) -> None:
    st.markdown(f"#### {response.heading}")
    st.write(response.summary)
    for block in response.blocks:
        _render_block(block)
    if response.agent_mode in {"groq", "gemini", "openrouter"}:
        st.badge("AI explanation", icon=":material/smart_toy:", color="blue")
    else:
        st.badge("Rules answer", icon=":material/verified:", color="gray")

    if not interactive:
        return
    if response.actions:
        st.caption("Available actions")
        with st.container(horizontal=True, wrap=True, gap="small"):
            for choice in response.actions:
                if st.button(
                    choice.label,
                    key=f"assistant_action_{response.response_id}_{choice.action_id}",
                    type=choice.style,
                    icon=choice.icon,
                    disabled=not choice.enabled,
                    help=choice.disabled_reason,
                    wrap=True,
                ):
                    _handle_action(choice, context)
    if response.ask_resolution and _session().pending_action is None:
        st.caption("Did this solve your question?")
        with st.container(horizontal=True, wrap=True, gap="small"):
            resolved = action(
                f"resolved:{response.response_id}",
                AssistantActionKind.MARK_RESOLVED,
                "Yes, resolved",
                icon=":material/check_circle:",
            )
            more = action(
                f"more-help:{response.response_id}",
                AssistantActionKind.NEED_MORE_HELP,
                "No, I still need help",
                icon=":material/support_agent:",
            )
            if st.button(
                resolved.label,
                key=f"assistant_feedback_yes_{response.response_id}",
                icon=resolved.icon,
            ):
                _handle_action(resolved, context)
            if st.button(
                more.label,
                key=f"assistant_feedback_no_{response.response_id}",
                icon=more.icon,
            ):
                _handle_action(more, context)


def _selectbox_payment(context: AssistantDataContext, key: str) -> PendingPayment | None:
    if not context.pending_payments:
        st.info("There are no unsettled payments in the loaded data.")
        return None
    payment_ids = list(context.pending_payments)
    selected = st.selectbox(
        "Unsettled payment",
        payment_ids,
        key=key,
        format_func=lambda pid: (
            f"{format_inr(context.pending_payments[pid].amount)} · "
            f"{context.pending_payments[pid].order_id or pid} · {pid}"
        ),
    )
    return context.pending_payments[selected]


def _render_settlement_controls(context: AssistantDataContext) -> None:
    if not context.batches:
        st.info("There are no settlements in the loaded data.")
        return
    sid = st.selectbox(
        "Settlement",
        _sorted_settlement_ids(context),
        key="assistant_settlement_select",
        format_func=lambda value: _settlement_option_label(context, value),
    )
    if st.button(
        "Continue",
        type="primary",
        key=f"assistant_confirm_settlement_{sid}",
        icon=":material/arrow_forward:",
    ):
        _save(
            confirm_subject_selection(
                _session(),
                AssistantSubjectKind.SETTLEMENT,
                [sid],
                SETTLEMENT_QUESTIONS,
                f"Selected settlement {sid}",
            )
        )
        _dialog_rerun()


def _render_subject_context(
    context: AssistantDataContext,
    *,
    selector_node: str,
) -> str | None:
    session = _session()
    subject_id = session.subject_ids[0] if session.subject_ids else None
    available = (
        subject_id in context.batches
        if session.subject_kind == AssistantSubjectKind.SETTLEMENT
        else subject_id in context.pending_payments
    )
    if not subject_id or not available:
        st.warning("The selected record is no longer available. Choose it again.")
        if st.button("Choose a record", key=f"assistant_missing_subject_{selector_node}"):
            _save(change_subject_selection(session, selector_node))
            _dialog_rerun()
        return None
    label = "settlement" if session.subject_kind == AssistantSubjectKind.SETTLEMENT else "payment"
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.caption(f"Asking about {label} `{subject_id}`")
        if st.button(
            "Change selection",
            key=f"assistant_change_subject_{selector_node}_{session.context_version}",
            icon=":material/swap_horiz:",
        ):
            _save(change_subject_selection(session, selector_node))
            _dialog_rerun()
    return subject_id


def _render_settlement_question_controls(context: AssistantDataContext) -> None:
    sid = _render_subject_context(context, selector_node=SETTLEMENT_SELECT)
    if sid is None:
        return
    with st.container(horizontal=True, wrap=True, gap="small"):
        for preset_id, preset in PRESET_INTENTS.items():
            if st.button(
                preset["label"],
                key=f"assistant_preset_{sid}_{preset_id}",
                wrap=True,
            ):
                response = _settlement_response(context, sid, preset["label"], preset_id)
                _append_exchange(
                    preset["label"],
                    response,
                    subject_kind=AssistantSubjectKind.SETTLEMENT,
                    subject_ids=[sid],
                    last_intent=preset_id,
                )
                _dialog_rerun()
        if st.button(
            "Ask anything else",
            key=f"assistant_settlement_custom_{sid}",
            icon=":material/chat:",
            wrap=True,
        ):
            _save(navigate(_session(), SETTLEMENT_CUSTOM_QUESTION, "Ask anything else"))
            _dialog_rerun()


def _render_pending_one_controls(context: AssistantDataContext, *, instant_focus: bool) -> None:
    payment = _selectbox_payment(
        context,
        "assistant_funds_payment" if instant_focus else "assistant_pending_payment",
    )
    if payment is None:
        return
    if not instant_focus:
        if st.button(
            "Continue",
            type="primary",
            key=f"assistant_confirm_payment_{payment.entity_id}",
            icon=":material/arrow_forward:",
        ):
            _save(
                confirm_subject_selection(
                    _session(),
                    AssistantSubjectKind.PENDING_PAYMENT,
                    [payment.entity_id],
                    PENDING_ONE_QUESTIONS,
                    f"Selected payment {payment.entity_id}",
                )
            )
            _dialog_rerun()
        return
    questions = (
        ("Check Instant Settlement eligibility", "Can I get this instantly?"),
    ) if instant_focus else (
        ("Where is my money?", "Where is my money?"),
        ("When will this settle?", "When will this settle?"),
        ("Can I get this instantly?", "Can I get this instantly?"),
        ("Why is it still pending?", "Why is it still pending?"),
    )
    with st.container(horizontal=True, wrap=True, gap="small"):
        for index, (label, question) in enumerate(questions):
            if st.button(label, key=f"assistant_pending_question_{payment.entity_id}_{index}", wrap=True):
                response = _pending_response(payment, question)
                _append_exchange(
                    label,
                    response,
                    subject_kind=AssistantSubjectKind.PENDING_PAYMENT,
                    subject_ids=[payment.entity_id],
                )
                _dialog_rerun()


def _render_pending_question_controls(context: AssistantDataContext) -> None:
    payment_id = _render_subject_context(context, selector_node=PENDING_ONE)
    if payment_id is None:
        return
    payment = context.pending_payments[payment_id]
    questions = (
        ("Where is my money?", "Where is my money?"),
        ("When will this settle?", "When will this settle?"),
        ("Can I get this instantly?", "Can I get this instantly?"),
        ("Why is it still pending?", "Why is it still pending?"),
    )
    with st.container(horizontal=True, wrap=True, gap="small"):
        for index, (label, question) in enumerate(questions):
            if st.button(
                label,
                key=f"assistant_pending_menu_{payment.entity_id}_{index}",
                wrap=True,
            ):
                intent = route_pending_query(question)
                response = _pending_response(payment, question)
                _append_exchange(
                    label,
                    response,
                    subject_kind=AssistantSubjectKind.PENDING_PAYMENT,
                    subject_ids=[payment.entity_id],
                    last_intent=intent,
                )
                _dialog_rerun()
        if st.button(
            "Ask anything else",
            key=f"assistant_payment_custom_{payment.entity_id}",
            icon=":material/chat:",
            wrap=True,
        ):
            _save(navigate(_session(), PENDING_ONE_CUSTOM_QUESTION, "Ask anything else"))
            _dialog_rerun()


def _render_pending_many_controls(context: AssistantDataContext, *, instant_focus: bool) -> None:
    ids = st.multiselect(
        "Unsettled payments",
        list(context.pending_payments),
        key="assistant_funds_many" if instant_focus else "assistant_pending_many",
        format_func=lambda pid: f"{format_inr(context.pending_payments[pid].amount)} · {pid}",
    )
    if st.button(
        "Check eligibility" if instant_focus else "Summarize selected",
        type="primary",
        key="assistant_check_many_funds" if instant_focus else "assistant_summarize_many",
        disabled=not ids,
    ):
        payments = [context.pending_payments[pid] for pid in ids]
        response = _aggregate_pending_response(payments, instant_focus=instant_focus)
        _append_exchange(
            "Check selected payments" if instant_focus else "Summarize selected payments",
            response,
            subject_kind=AssistantSubjectKind.PENDING_PAYMENT_SET,
            subject_ids=ids,
        )
        _dialog_rerun()


def _render_all_pending_control(context: AssistantDataContext, *, instant_focus: bool) -> None:
    if st.button(
        "Check all unsettled amounts" if instant_focus else "Summarize all unsettled payments",
        type="primary",
        key="assistant_check_all_funds" if instant_focus else "assistant_summarize_all",
    ):
        payments = list(context.pending_payments.values())
        response = _aggregate_pending_response(payments, instant_focus=instant_focus)
        _append_exchange(
            "Check all unsettled amounts" if instant_focus else "Summarize all unsettled payments",
            response,
            subject_kind=AssistantSubjectKind.PENDING_PAYMENT_SET,
            subject_ids=[payment.entity_id for payment in payments],
        )
        _dialog_rerun()


def _render_issue_controls(context: AssistantDataContext, *, settlement: bool) -> None:
    if settlement:
        if not context.batches:
            st.info("There are no settlements in the loaded data.")
            return
        sid = st.selectbox(
            "Settlement",
            _sorted_settlement_ids(context),
            key="assistant_issue_settlement",
            format_func=lambda value: _settlement_option_label(context, value),
        )
        kind = AssistantSubjectKind.SETTLEMENT
        ids = [sid]
    else:
        payment = _selectbox_payment(context, "assistant_issue_payment")
        if payment is None:
            return
        kind = AssistantSubjectKind.PENDING_PAYMENT
        ids = [payment.entity_id]
    if st.button("Review support request", type="primary", key=f"assistant_issue_review_{ids[0]}"):
        session = set_subject(_session(), kind, ids)
        chosen = action(
            f"raise-ticket:{ids[0]}",
            AssistantActionKind.RAISE_TICKET,
            "Raise ticket",
            requires_confirmation=True,
        )
        session = append_user(session, "Review support request")
        session.pending_action = chosen
        _save(append_response(session, _ticket_preview(session, context)))
        _dialog_rerun()


def _render_guided_controls(context: AssistantDataContext) -> None:
    node = _session().node_id
    if node == SETTLEMENT_SELECT:
        _render_settlement_controls(context)
    elif node == SETTLEMENT_QUESTIONS:
        _render_settlement_question_controls(context)
    elif node == SETTLEMENT_CUSTOM_QUESTION:
        _render_subject_context(context, selector_node=SETTLEMENT_SELECT)
    elif node == PENDING_ONE:
        _render_pending_one_controls(context, instant_focus=False)
    elif node == PENDING_ONE_QUESTIONS:
        _render_pending_question_controls(context)
    elif node == PENDING_ONE_CUSTOM_QUESTION:
        _render_subject_context(context, selector_node=PENDING_ONE)
    elif node == PENDING_MANY:
        _render_pending_many_controls(context, instant_focus=False)
    elif node == PENDING_ALL:
        _render_all_pending_control(context, instant_focus=False)
    elif node == FUNDS_ONE:
        _render_pending_one_controls(context, instant_focus=True)
    elif node == FUNDS_MANY:
        _render_pending_many_controls(context, instant_focus=True)
    elif node == FUNDS_ALL:
        _render_all_pending_control(context, instant_focus=True)
    elif node == ISSUE_SETTLEMENT:
        _render_issue_controls(context, settlement=True)
    elif node == ISSUE_PAYMENT:
        _render_issue_controls(context, settlement=False)


def _render_transcript(context: AssistantDataContext) -> None:
    messages = _session().messages
    latest_assistant = max(
        (index for index, message in enumerate(messages) if message.role == "assistant"),
        default=-1,
    )
    with st.container(height=460, border=True, key="universal_assistant_thread", autoscroll=True):
        for index, message in enumerate(messages):
            with st.chat_message(
                message.role,
                avatar=":material/support_agent:" if message.role == "assistant" else None,
            ):
                if message.role == "user":
                    st.write(message.content)
                elif message.response is not None:
                    _render_response(
                        message.response,
                        interactive=index == latest_assistant,
                        context=context,
                    )


def _render_escape_controls(context: AssistantDataContext) -> None:
    session = _session()
    st.caption("Guided navigation")
    with st.container(horizontal=True, wrap=True, gap="small"):
        if session.back_stack and st.button("Back", icon=":material/arrow_back:", key="assistant_back"):
            _save(go_back(session))
            _dialog_rerun()
        if st.button("Main menu", icon=":material/home:", key="assistant_home"):
            _save(go_home(session))
            _dialog_rerun()
        if st.button(
            "Talk to support",
            icon=":material/support_agent:",
            key="assistant_support_escape",
        ):
            chosen = action(
                f"raise-ticket:{','.join(session.subject_ids) or 'general'}",
                AssistantActionKind.RAISE_TICKET,
                "Talk to support",
                requires_confirmation=True,
            )
            _handle_action(chosen, context)


@st.dialog(
    "Payment and settlement assistant",
    width="medium",
    icon=":material/support_agent:",
    on_dismiss=_close_assistant,
)
def _assistant_dialog(context: AssistantDataContext) -> None:
    _session()
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        st.caption("Guided help and free-text AI in one conversation")
        if st.button("New chat", icon=":material/refresh:", key="assistant_new_chat"):
            _save(initial_session())
            _dialog_rerun()

    _render_transcript(context)
    _render_guided_controls(context)
    _render_escape_controls(context)

    session = _session()
    prompt = None
    if session.node_id in {FREE_TEXT, SETTLEMENT_CUSTOM_QUESTION, PENDING_ONE_CUSTOM_QUESTION}:
        subject_id = session.subject_ids[0] if session.subject_ids else None
        if session.node_id == SETTLEMENT_CUSTOM_QUESTION and subject_id:
            placeholder = f"Ask anything about settlement {subject_id}…"
        elif session.node_id == PENDING_ONE_CUSTOM_QUESTION and subject_id:
            placeholder = f"Ask anything about payment {subject_id}…"
        else:
            placeholder = "Ask about a payment, settlement, ticket, fee, GST, UTR, or expected date…"
        prompt = st.chat_input(
            placeholder,
            key=f"universal_assistant_input_{session.node_id}_{session.context_version}",
            max_chars=1200,
            submit_mode="disable",
        )
    if prompt:
        with st.spinner("Checking your loaded Razorpay data…"):
            _handle_free_text(prompt, context)
        _dialog_rerun()


def render_universal_assistant_launcher(
    *,
    batches: dict[str, SettlementBatch],
    decisions: list[SettlementCloseDecision],
    pending_payments: list[PendingPayment],
    use_llm: bool,
) -> None:
    """Render the single app-wide launcher and open the assistant dialog."""
    context = AssistantDataContext(
        batches=batches,
        decisions={decision.settlement_id: decision for decision in decisions},
        pending_payments={payment.entity_id: payment for payment in pending_payments},
        use_llm=use_llm,
    )
    st.session_state.setdefault(OPEN_KEY, False)
    if st.button(
        ":material/support_agent:",
        key="universal_assistant_launcher",
        type="primary",
        help="Open payment and settlement assistant",
    ):
        st.session_state[OPEN_KEY] = True
    if st.session_state[OPEN_KEY]:
        _assistant_dialog(context)
