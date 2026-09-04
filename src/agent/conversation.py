"""Pure state helpers for the universal guided assistant."""

from __future__ import annotations

import re

from src.agent.responses import action, simple_response
from src.domain.models import (
    AssistantActionKind,
    AssistantResponse,
    AssistantSession,
    AssistantSubjectKind,
    AssistantTranscriptMessage,
)

HOME = "home"
PENDING_SCOPE = "pending_scope"
PENDING_ONE = "pending_one"
PENDING_MANY = "pending_many"
PENDING_ALL = "pending_all"
SETTLEMENT_SELECT = "settlement_select"
SETTLEMENT_QUESTIONS = "settlement_questions"
SETTLEMENT_CUSTOM_QUESTION = "settlement_custom_question"
PENDING_ONE_QUESTIONS = "pending_one_questions"
PENDING_ONE_CUSTOM_QUESTION = "pending_one_custom_question"
FUNDS_SCOPE = "funds_scope"
FUNDS_ONE = "funds_one"
FUNDS_MANY = "funds_many"
FUNDS_ALL = "funds_all"
ISSUE_SUBJECT = "issue_subject"
ISSUE_SETTLEMENT = "issue_settlement"
ISSUE_PAYMENT = "issue_payment"
FREE_TEXT = "free_text"

VALID_NODES = frozenset(
    {
        HOME,
        PENDING_SCOPE,
        PENDING_ONE,
        PENDING_MANY,
        PENDING_ALL,
        SETTLEMENT_SELECT,
        SETTLEMENT_QUESTIONS,
        SETTLEMENT_CUSTOM_QUESTION,
        PENDING_ONE_QUESTIONS,
        PENDING_ONE_CUSTOM_QUESTION,
        FUNDS_SCOPE,
        FUNDS_ONE,
        FUNDS_MANY,
        FUNDS_ALL,
        ISSUE_SUBJECT,
        ISSUE_SETTLEMENT,
        ISSUE_PAYMENT,
        FREE_TEXT,
    }
)

_GREETING_RE = re.compile(
    r"^\s*(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|start|menu)\s*[!.?]*\s*$",
    re.I,
)


def _nav(target: str, label: str, icon: str) -> object:
    return action(
        f"navigate:{target}",
        AssistantActionKind.NAVIGATE,
        label,
        icon=icon,
        payload={"target": target},
    )


def home_response() -> AssistantResponse:
    return simple_response(
        "How can I help?",
        "Choose a guided path, or type any payment or settlement question below.",
        actions=(
            _nav(PENDING_SCOPE, "Track an unsettled payment", ":material/schedule:"),
            _nav(SETTLEMENT_SELECT, "Understand a settlement", ":material/receipt_long:"),
            _nav(FUNDS_SCOPE, "Get funds sooner", ":material/bolt:"),
            _nav(ISSUE_SUBJECT, "Fix or report an issue", ":material/support_agent:"),
            _nav(FREE_TEXT, "Ask something else", ":material/chat:"),
        ),
    )


def node_response(node_id: str) -> AssistantResponse:
    if node_id == HOME:
        return home_response()
    if node_id == PENDING_SCOPE:
        return simple_response(
            "Which payments do you want to check?",
            "Choose one payment, several payments, or a summary of everything currently unsettled.",
            actions=(
                _nav(PENDING_ONE, "One payment", ":material/looks_one:"),
                _nav(PENDING_MANY, "Several payments", ":material/checklist:"),
                _nav(PENDING_ALL, "All unsettled payments", ":material/select_all:"),
            ),
        )
    if node_id == SETTLEMENT_SELECT:
        return simple_response(
            "Choose a settlement",
            "Select a settlement, then choose a common question or type your own.",
        )
    if node_id == SETTLEMENT_QUESTIONS:
        return simple_response(
            "What would you like to know?",
            "Choose a common settlement question, or ask anything else in your own words.",
        )
    if node_id == SETTLEMENT_CUSTOM_QUESTION:
        return simple_response(
            "Ask anything else",
            "Your selected settlement and this conversation will be used as context.",
        )
    if node_id == PENDING_ONE:
        return simple_response(
            "Choose an unsettled payment",
            "Select one payment and tell me what you want to understand.",
        )
    if node_id == PENDING_ONE_QUESTIONS:
        return simple_response(
            "What would you like to know?",
            "Choose a common payment question, or ask anything else in your own words.",
        )
    if node_id == PENDING_ONE_CUSTOM_QUESTION:
        return simple_response(
            "Ask anything else",
            "Your selected payment and this conversation will be used as context.",
        )
    if node_id == PENDING_MANY:
        return simple_response(
            "Choose several unsettled payments",
            "Select the payments you want combined into one status summary.",
        )
    if node_id == PENDING_ALL:
        return simple_response(
            "Review all unsettled payments",
            "I can summarize their total, expected dates, and Instant Settlement eligibility.",
        )
    if node_id == FUNDS_SCOPE:
        return simple_response(
            "What amount should I evaluate?",
            "Payment selection is used only to calculate an amount. Instant Settlement draws from the available Razorpay balance, not from specific payment IDs.",
            actions=(
                _nav(FUNDS_ONE, "One payment amount", ":material/looks_one:"),
                _nav(FUNDS_MANY, "Several payment amounts", ":material/checklist:"),
                _nav(FUNDS_ALL, "All unsettled amounts", ":material/select_all:"),
            ),
        )
    if node_id in {FUNDS_ONE, FUNDS_MANY, FUNDS_ALL}:
        return simple_response(
            "Review Instant Settlement eligibility",
            "Choose the payment scope below. I will show what the loaded data can verify before offering the available next step.",
        )
    if node_id == ISSUE_SUBJECT:
        return simple_response(
            "What needs support?",
            "Choose the closest subject. I will carry its known evidence into the ticket preview.",
            actions=(
                _nav(ISSUE_SETTLEMENT, "A settlement", ":material/receipt_long:"),
                _nav(ISSUE_PAYMENT, "An unsettled payment", ":material/schedule:"),
            ),
        )
    if node_id == ISSUE_SETTLEMENT:
        return simple_response(
            "Choose the settlement to report",
            "Select a settlement to prepare a support request with its status, UTR, checks, and known issue.",
        )
    if node_id == ISSUE_PAYMENT:
        return simple_response(
            "Choose the payment to report",
            "Select an unsettled payment to prepare a support request with its amount and expected date.",
        )
    return simple_response(
        "Ask in your own words",
        "Type any question below. You can include a settlement ID, payment ID, order ID, UTR, date, or amount.",
    )


def initial_session() -> AssistantSession:
    return AssistantSession(
        messages=[AssistantTranscriptMessage(role="assistant", response=home_response())]
    )


def is_greeting(text: str) -> bool:
    return bool(_GREETING_RE.fullmatch(text))


def append_user(session: AssistantSession, content: str) -> AssistantSession:
    updated = session.model_copy(deep=True)
    updated.messages.append(AssistantTranscriptMessage(role="user", content=content))
    return updated


def append_response(session: AssistantSession, response: AssistantResponse) -> AssistantSession:
    updated = session.model_copy(deep=True)
    updated.messages.append(AssistantTranscriptMessage(role="assistant", response=response))
    return updated


def navigate(session: AssistantSession, target: str, label: str) -> AssistantSession:
    if target not in VALID_NODES:
        raise ValueError(f"Unknown assistant node: {target}")
    updated = append_user(session, label)
    if updated.node_id != target:
        updated.back_stack.append(updated.node_id)
    updated.node_id = target
    updated.pending_action = None
    updated.resolution_status = "open"
    return append_response(updated, node_response(target))


def go_home(session: AssistantSession, *, record_choice: bool = True) -> AssistantSession:
    updated = append_user(session, "Main menu") if record_choice else session.model_copy(deep=True)
    updated.node_id = HOME
    updated.back_stack = []
    updated.subject_kind = AssistantSubjectKind.NONE
    updated.subject_ids = []
    updated.subject_context_start = None
    updated.last_intent = None
    updated.context_version += 1
    updated.pending_action = None
    updated.resolution_status = "open"
    return append_response(updated, home_response())


def go_back(session: AssistantSession) -> AssistantSession:
    if not session.back_stack:
        return go_home(session)
    updated = append_user(session, "Back")
    target = updated.back_stack.pop()
    updated.node_id = target
    updated.pending_action = None
    return append_response(updated, node_response(target))


def set_subject(
    session: AssistantSession,
    kind: AssistantSubjectKind,
    subject_ids: list[str],
) -> AssistantSession:
    updated = session.model_copy(deep=True)
    ids = list(dict.fromkeys(subject_ids))
    if updated.subject_kind != kind or updated.subject_ids != ids:
        updated.subject_context_start = len(updated.messages)
        updated.last_intent = None
        updated.context_version += 1
    updated.subject_kind = kind
    updated.subject_ids = ids
    return updated


def confirm_subject_selection(
    session: AssistantSession,
    kind: AssistantSubjectKind,
    subject_ids: list[str],
    target: str,
    label: str,
) -> AssistantSession:
    """Accept a selector value and enter its question menu atomically."""
    if target not in VALID_NODES:
        raise ValueError(f"Unknown assistant node: {target}")
    updated = session.model_copy(deep=True)
    context_start = len(updated.messages)
    updated = append_user(updated, label)
    if updated.node_id != target:
        updated.back_stack.append(updated.node_id)
    updated.node_id = target
    updated.subject_kind = kind
    updated.subject_ids = list(dict.fromkeys(subject_ids))
    updated.subject_context_start = context_start
    updated.last_intent = None
    updated.context_version += 1
    updated.pending_action = None
    updated.resolution_status = "open"
    return append_response(updated, node_response(target))


def change_subject_selection(session: AssistantSession, target: str) -> AssistantSession:
    """Return to a selector without allowing its old subject context to leak."""
    if target not in VALID_NODES:
        raise ValueError(f"Unknown assistant node: {target}")
    updated = append_user(session, "Change selection")
    updated.node_id = target
    updated.back_stack = [node for node in updated.back_stack if node != target]
    updated.subject_kind = AssistantSubjectKind.NONE
    updated.subject_ids = []
    updated.subject_context_start = None
    updated.last_intent = None
    updated.context_version += 1
    updated.pending_action = None
    updated.resolution_status = "open"
    return append_response(updated, node_response(target))


def set_last_intent(session: AssistantSession, intent: str | None) -> AssistantSession:
    updated = session.model_copy(deep=True)
    updated.last_intent = intent
    return updated


def _visible_response_text(response: AssistantResponse) -> str:
    parts = [response.heading, response.summary]
    for block in response.blocks:
        if block.title:
            parts.append(block.title)
        if block.body:
            parts.append(block.body)
        parts.extend(block.items)
    return " ".join(" ".join(parts).split())


def recent_subject_context(
    session: AssistantSession,
    *,
    max_exchanges: int = 6,
    max_chars: int = 4_000,
) -> list[dict[str, str]]:
    """Return bounded merchant-visible history for the currently selected subject."""
    if session.subject_context_start is None or not session.subject_ids:
        return []
    messages = session.messages[session.subject_context_start :]
    history: list[dict[str, str]] = []
    for message in messages[-(max_exchanges * 2) :]:
        if message.role == "user":
            content = " ".join(message.content.split())
        elif message.response is not None:
            content = _visible_response_text(message.response)
        else:
            continue
        if content:
            history.append({"role": message.role, "content": content[:1_000]})

    bounded: list[dict[str, str]] = []
    remaining = max_chars
    for item in reversed(history):
        if remaining <= 0:
            break
        content = item["content"][-remaining:]
        bounded.append({"role": item["role"], "content": content})
        remaining -= len(content)
    return list(reversed(bounded))
