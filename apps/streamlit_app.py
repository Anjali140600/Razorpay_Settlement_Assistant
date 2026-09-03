"""Razorpay Settlement Assistant — merchant-facing settlement verification and Q&A."""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.config  # noqa: F401

from data.synthetic.generator import generate_demo_dataset
from src.agent.llm_client import should_use_llm, get_llm_model, llm_providers_available
from src.agent.settlement_qa import (
    MAX_QUESTIONS_PER_SESSION,
    PRESET_INTENTS,
    answer_free_text,
    answer_preset,
    filter_response_text,
    last_llm_error,
    needs_support_ticket,
    question_hash,
    raise_support_ticket,
    sanitize_question,
    validate_question_input,
)
from src.domain.models import SettlementIntegrityStatus
from src.engine import ReconciliationEngine

DEMO_DIR = ROOT / "data" / "synthetic" / "demo"
SAMPLE_OUTPUT = ROOT / "sample-output"

CSS = """
<style>
  :root {
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --text-muted: #64748b;
    --page-bg: #eef2f7;
    --card-bg: #ffffff;
    --card-border: #cbd5e1;
    --accent: #2563eb;
    --accent-soft: #dbeafe;
    --success-bg: #ecfdf5;
    --success-text: #047857;
    --success-border: #6ee7b7;
    --warn-bg: #fffbeb;
    --warn-text: #b45309;
    --warn-border: #fcd34d;
    --fail-bg: #fef2f2;
    --fail-text: #b91c1c;
    --fail-border: #fca5a5;
    --support-bg: #f5f3ff;
    --support-border: #c4b5fd;
    --support-text: #5b21b6;
  }

  .stApp {
    background-color: var(--page-bg) !important;
  }

  html, body, [class*="css"], .stMarkdown, p, label, span {
    color: var(--text-primary);
    font-family: "Inter", "Segoe UI", Roboto, sans-serif;
    font-size: 17px;
    line-height: 1.6;
  }

  h1 {
    font-size: 2.1rem !important;
    font-weight: 700 !important;
    color: var(--text-primary) !important;
    margin-bottom: 0.15rem !important;
  }

  h2, h3, [data-testid="stHeadingWithAction"] {
    font-size: 1.35rem !important;
    font-weight: 700 !important;
    color: var(--text-primary) !important;
  }

  .page-header {
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
    color: #ffffff;
    padding: 1.35rem 1.5rem;
    border-radius: 14px;
    margin-bottom: 1.25rem;
    box-shadow: 0 4px 14px rgba(37, 99, 235, 0.18);
  }

  .page-header h1, .page-header p {
    color: #ffffff !important;
    margin: 0 !important;
  }

  .page-subtitle {
    font-size: 1.05rem;
    color: #e2e8f0 !important;
    margin-top: 0.35rem !important;
    opacity: 0.95;
  }

  div[data-testid="stVerticalBlockBorderWrapper"] {
    padding: 1.35rem 1.5rem !important;
    margin-bottom: 1.1rem !important;
    border-radius: 14px !important;
    background: var(--card-bg) !important;
    border: 1px solid var(--card-border) !important;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06) !important;
  }

  .section-label {
    display: inline-block;
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.85rem;
    padding: 0.35rem 0.65rem;
    background: var(--accent-soft);
    border-radius: 6px;
  }

  .stMetric label {
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    color: var(--text-secondary) !important;
  }

  .stMetric [data-testid="stMetricValue"] {
    font-size: 1.85rem !important;
    font-weight: 800 !important;
    color: var(--text-primary) !important;
  }

  .stRadio > label, .stSelectbox label, .stTextInput label {
    font-size: 1rem !important;
    font-weight: 600 !important;
    color: var(--text-secondary) !important;
  }

  div[data-testid="stButton"] button {
    font-size: 1rem !important;
    font-weight: 600 !important;
    padding: 0.55rem 1rem !important;
    min-height: 2.75rem;
    border-radius: 8px !important;
  }

  div[data-testid="stButton"] button[kind="secondary"] {
    background: #f8fafc !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--card-border) !important;
  }

  .stCaption, small {
    font-size: 0.95rem !important;
    color: var(--text-muted) !important;
  }

  .status-pill {
    display: inline-block;
    font-weight: 700;
    font-size: 1.05rem;
    padding: 0.55rem 1rem;
    border-radius: 8px;
    margin: 0.65rem 0 1rem;
  }

  .verified {
    background: var(--success-bg);
    color: var(--success-text);
    border: 1px solid var(--success-border);
  }

  .attention {
    background: var(--warn-bg);
    color: var(--warn-text);
    border: 1px solid var(--warn-border);
  }

  .check-row {
    padding: 0.65rem 0.85rem;
    border-radius: 10px;
    margin: 0.45rem 0;
  }

  .check-pass {
    background: var(--success-bg);
    color: var(--success-text);
    border: 1px solid var(--success-border);
    font-size: 1.02rem;
    font-weight: 700;
    margin: 0;
  }

  .check-fail {
    background: var(--fail-bg);
    color: var(--fail-text);
    border: 1px solid var(--fail-border);
    font-size: 1.02rem;
    font-weight: 700;
    margin: 0;
  }

  .check-detail {
    color: var(--text-primary);
    font-size: 0.98rem;
    margin: 0.55rem 0 0.85rem 0;
    padding: 0.85rem 1rem;
    background: #fff7ed;
    border: 1px solid #fdba74;
    border-left: 4px solid #ea580c;
    border-radius: 0 10px 10px 0;
    line-height: 1.65;
  }

  .check-detail strong {
    color: #9a3412;
    font-weight: 700;
  }

  .support-panel {
    background: var(--support-bg);
    border: 1px solid var(--support-border);
    border-radius: 12px;
    padding: 1rem 1.15rem;
    margin-top: 1rem;
  }

  .support-panel .section-label {
    background: #ede9fe;
    color: var(--support-text);
  }

  .support-panel p, .support-panel .stCaption {
    color: var(--support-text) !important;
  }

  .ticket-raised {
    background: #ecfdf5;
    border: 1px solid var(--success-border);
    color: var(--success-text);
    padding: 0.75rem 1rem;
    border-radius: 10px;
    font-weight: 600;
    margin-top: 0.5rem;
  }

  .answer-box {
    font-size: 1.02rem;
    color: var(--text-primary);
    padding: 1rem 1.2rem;
    background: var(--accent-soft);
    border: 1px solid #93c5fd;
    border-left: 4px solid var(--accent);
    border-radius: 0 10px 10px 0;
    margin-top: 0.85rem;
    line-height: 1.65;
  }

  .answer-box strong {
    color: #1d4ed8;
  }

  .badge {
    display: inline-block;
    padding: 5px 11px;
    border-radius: 999px;
    font-size: 0.88rem;
    font-weight: 700;
    margin-right: 8px;
    margin-bottom: 6px;
    border: 1px solid transparent;
  }

  .badge-groq { background: #dcfce7; color: #166534; border-color: #86efac; }
  .badge-gemini { background: #dbeafe; color: #1e40af; border-color: #93c5fd; }
  .badge-openrouter { background: #ede9fe; color: #5b21b6; border-color: #c4b5fd; }
  .badge-keyword { background: #f1f5f9; color: #334155; border-color: #cbd5e1; }
  .badge-escalated { background: #ffedd5; color: #c2410c; border-color: #fdba74; }

  div[data-testid="stExpander"] details summary {
    font-size: 1.02rem !important;
    font-weight: 700 !important;
    color: var(--text-primary) !important;
  }

  div[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid var(--card-border) !important;
  }

  div[data-testid="stSidebar"] .section-label {
    margin-top: 0.25rem;
  }

  hr {
    margin: 1.5rem 0 !important;
    border-color: var(--card-border) !important;
  }

  /* ---------- Settlement assistant ---------- */

  .chat-header {
    display: flex;
    align-items: center;
    gap: 0.8rem;
  }

  .chat-avatar {
    flex: 0 0 44px;
    width: 44px;
    height: 44px;
    border-radius: 13px;
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
    color: #ffffff;
    font-size: 1.15rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(37, 99, 235, 0.28);
  }

  .chat-name {
    font-size: 1.08rem !important;
    font-weight: 700 !important;
    line-height: 1.3 !important;
    margin: 0 !important;
  }

  .chat-presence {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.88rem !important;
    color: var(--text-muted) !important;
    margin: 0.15rem 0 0 !important;
  }

  .presence-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.18);
  }

  /* Conversation thread */
  div[class*="st-key-chat_thread"] {
    background: #f8fafc !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 14px !important;
    padding: 0.7rem 0.9rem !important;
    box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.05) !important;
  }

  div[data-testid="stChatMessage"] {
    background: transparent !important;
    padding: 0.15rem 0 !important;
    gap: 0.6rem !important;
    font-size: 1rem !important;
    line-height: 1.6 !important;
  }

  div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
    margin-bottom: 0.3rem !important;
  }

  div[data-testid="stChatMessageAvatarCustom"] {
    background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%) !important;
    color: #ffffff !important;
    border: none !important;
  }

  div[data-testid="stChatMessageAvatarUser"] {
    background: #dbeafe !important;
    color: #1d4ed8 !important;
    border: none !important;
  }

  /* Assistant bubble */
  div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarCustom"])
    div[data-testid="stChatMessageContent"] {
    width: fit-content;
    max-width: 90%;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 4px 14px 14px 14px;
    padding: 0.75rem 1rem;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
  }

  /* User bubble, mirrored to the right */
  div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) {
    flex-direction: row-reverse !important;
  }

  div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"])
    div[data-testid="stChatMessageContent"] {
    width: fit-content;
    max-width: 82%;
    margin-left: auto;
    background: var(--accent);
    border-radius: 14px 4px 14px 14px;
    padding: 0.7rem 1rem;
    box-shadow: 0 1px 3px rgba(37, 99, 235, 0.25);
  }

  div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"])
    div[data-testid="stChatMessageContent"] p {
    color: #ffffff !important;
  }

  /* Thinking / evidence panel inside a message */
  div[data-testid="stChatMessage"] div[data-testid="stExpander"] details {
    background: #f8fafc !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
  }

  div[data-testid="stChatMessage"] div[data-testid="stExpander"] details summary {
    font-size: 0.92rem !important;
    font-weight: 600 !important;
    color: var(--text-secondary) !important;
  }

  div[data-testid="stChatMessage"] div[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p {
    font-size: 0.94rem !important;
    color: var(--text-secondary) !important;
  }

  /* Quick-reply chips */
  div[class*="st-key-chip_"] button {
    min-height: 2.2rem !important;
    padding: 0.35rem 0.9rem !important;
    border-radius: 999px !important;
    background: #ffffff !important;
    border: 1px solid var(--card-border) !important;
    color: #1e3a5f !important;
    font-size: 0.93rem !important;
    font-weight: 600 !important;
  }

  div[class*="st-key-chip_"] button:hover {
    background: var(--accent-soft) !important;
    border-color: #93c5fd !important;
    color: #1d4ed8 !important;
  }

  /* Composer */
  div[data-testid="stChatInput"] {
    border-radius: 12px !important;
    border: 1px solid var(--card-border) !important;
    background: #ffffff !important;
  }

  div[data-testid="stChatInput"]:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12) !important;
  }

  .chat-hint {
    font-size: 0.88rem;
    color: var(--text-muted) !important;
    margin: 0.5rem 0 0 !important;
  }
</style>
"""


def ensure_demo_data() -> None:
    if not (DEMO_DIR / "recon.json").exists():
        generate_demo_dataset(DEMO_DIR, repo_root=ROOT)


def format_inr(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def format_date(dt) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%b %-d") if hasattr(dt, "strftime") else str(dt)[:10]


def run_check() -> None:
    engine = ReconciliationEngine(DEMO_DIR, eval_date=date(2026, 8, 30), use_llm=False)
    engine.load_sources()
    run = engine.run()
    st.session_state["engine"] = engine
    st.session_state["run"] = run
    if "qa_count" not in st.session_state:
        st.session_state["qa_count"] = 0


def check_name(ctrl) -> str:
    if ctrl.control_type == "batch_integrity":
        return "Settlement batch amounts add up"
    if ctrl.control_type == "tax_lines":
        return "Fees & GST lines"
    return ctrl.control_type.replace("_", " ").title()


def render_check(ctrl) -> None:
    name = check_name(ctrl)
    if ctrl.status.value == "PASS":
        st.markdown(
            f'<div class="check-row"><p class="check-pass">✓ {name}</p></div>',
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        f'<div class="check-row"><p class="check-fail">✗ {name}</p></div>',
        unsafe_allow_html=True,
    )
    detail = ctrl.calculation_detail
    if detail:
        lines = [
            f"<strong>Formula:</strong> {detail.formula}",
            f"<strong>Expected:</strong> {detail.expected_display}",
            f"<strong>Actual:</strong> {detail.actual_display}",
        ]
        if detail.delta_display:
            lines.append(f"<strong>Gap:</strong> {detail.delta_display}")
        if detail.line_id:
            lines.append(f"<strong>Line:</strong> {detail.line_id}")
        lines.append(f"<strong>Error:</strong> {detail.error}")
        st.markdown(
            '<div class="check-detail">' + "<br>".join(lines) + "</div>",
            unsafe_allow_html=True,
        )
    elif ctrl.message:
        st.markdown(f'<div class="check-detail">{ctrl.message}</div>', unsafe_allow_html=True)


def agent_mode_badge(mode: str) -> str:
    labels = {
        "groq": ("Answered via Groq", "badge-groq"),
        "gemini": ("Answered via Gemini", "badge-gemini"),
        "openrouter": ("Answered via OpenRouter", "badge-openrouter"),
        "keyword": ("Answered via rules", "badge-keyword"),
    }
    label, css = labels.get(mode, ("Answered via rules", "badge-keyword"))
    return f'<span class="badge {css}">{label}</span>'


ASSISTANT_AVATAR = ":material/support_agent:"
STEP_PACING_SECONDS = 0.18
STREAM_WORD_DELAY = 0.014

WELCOME_MESSAGE = (
    "Hi — I'm your settlement assistant.\n\n"
    "Ask me why your payout differs from your sales, how fees and GST were charged, "
    "or whether this settlement adds up. I answer only from your Razorpay settlement "
    "data and show the evidence behind every answer."
)

TOOL_STEP_LABELS = {
    "fetch_settlement": "Read the settlement header and UTR",
    "fetch_recon_lines": "Pulled every recon line in this batch",
    "calculate_batch": "Recomputed batch totals from the recon lines",
    "explain_fee_tax": "Checked fee and GST on each payment line",
    "search_settlements": "Searched your settlements",
    "search_by_amount": "Searched settlements and payments by amount",
    "search_by_date": "Searched settlements by date",
    "get_policy": "Applied the settlement verification policy",
    "support_guidance": "Checked what support can do here",
    "escalate_to_support": "Prepared a support escalation",
    "finish_answer": "Wrote the answer from the evidence",
    "plain_text_answer": "Wrote the answer from the evidence",
}


def get_chat_history(settlement_id: str) -> list[dict]:
    if "chat_histories" not in st.session_state:
        st.session_state["chat_histories"] = {}
    histories = st.session_state["chat_histories"]
    if settlement_id not in histories:
        histories[settlement_id] = [{"role": "assistant", "content": WELCOME_MESSAGE, "meta": {"welcome": True}}]
    return histories[settlement_id]


def append_chat_message(settlement_id: str, role: str, content: str, meta: dict | None = None) -> None:
    get_chat_history(settlement_id).append({"role": role, "content": content, "meta": meta or {}})


def ticket_offer_pending(settlement_id: str) -> bool:
    """True when our last reply offered the Raise-ticket button and it is still unused."""
    if settlement_id in st.session_state["raised_tickets"]:
        return False
    for msg in reversed(get_chat_history(settlement_id)):
        if msg["role"] != "assistant":
            continue
        return bool((msg.get("meta") or {}).get("offer_raise_ticket"))
    return False


def envelope_to_meta(ans, *, ai_requested: bool = False) -> dict:
    mode = getattr(ans, "agent_mode", "keyword")
    return {
        "agent_mode": mode,
        "escalated_to_support": getattr(ans, "escalated_to_support", False),
        "offer_raise_ticket": getattr(ans, "offer_raise_ticket", False),
        "support_ticket_id": getattr(ans, "support_ticket_id", None),
        "citations": getattr(ans, "citations", None) or [],
        "tool_trace": getattr(ans, "tool_trace", None),
        "abstained": getattr(ans, "abstained", False),
        "fallback_reason": last_llm_error() if (ai_requested and mode == "keyword") else None,
    }


def apply_raised_ticket(settlement_id: str, decision, batches: dict) -> None:
    """Raise one ticket and keep the header + chat buttons in the same state."""
    ticket_env = raise_support_ticket(settlement_id, decision, batches)
    st.session_state["raised_tickets"][settlement_id] = ticket_env
    append_chat_message(
        settlement_id,
        "assistant",
        ticket_env.answer_text,
        envelope_to_meta(ticket_env),
    )
    st.rerun()


def render_raise_ticket_button(settlement_id: str, decision, batches: dict, key: str) -> None:
    if st.button("Raise ticket with Razorpay support", type="primary", key=key, width="stretch"):
        apply_raised_ticket(settlement_id, decision, batches)


def render_ticket_cta(meta: dict, settlement_id: str, decision, batches: dict, key: str) -> None:
    if not meta.get("offer_raise_ticket") or not needs_support_ticket(decision):
        return
    raised = st.session_state["raised_tickets"].get(settlement_id)
    if raised:
        st.markdown(
            f'<div class="ticket-raised">Ticket raised — <code>{raised.support_ticket_id}</code></div>',
            unsafe_allow_html=True,
        )
        return
    render_raise_ticket_button(settlement_id, decision, batches, key)


def resolve_answer(
    settlement_id: str,
    question: str,
    preset_id: str | None,
    decision,
    batches: dict,
) -> tuple[str, dict]:
    """Run the Q&A pipeline and return the merchant-facing answer plus its metadata."""
    if preset_id:
        ans = answer_preset(preset_id, settlement_id, batches)
        return filter_response_text(ans.answer_text), envelope_to_meta(ans)

    ok, err = validate_question_input(question)
    if not ok:
        return err, {"abstained": True, "agent_mode": "keyword"}

    raised_ticket_id = (
        st.session_state["raised_tickets"][settlement_id].support_ticket_id
        if settlement_id in st.session_state["raised_tickets"]
        else None
    )
    ans = answer_free_text(
        question,
        settlement_id,
        batches,
        use_llm=st.session_state["use_llm_qa"],
        settlement_decision=decision,
        raised_ticket_id=raised_ticket_id,
        ticket_offer_pending=ticket_offer_pending(settlement_id),
    )
    _ = question_hash(sanitize_question(question))
    ai_requested = bool(st.session_state["use_llm_qa"])
    return filter_response_text(ans.answer_text), envelope_to_meta(ans, ai_requested=ai_requested)


def planned_steps(preset_id: str | None, use_llm: bool) -> list[str]:
    """Work the assistant is about to do, shown live so the wait is explainable."""
    steps = [
        ":material/receipt_long: Opening the settlement header and UTR",
        ":material/calculate: Recomputing the batch total from recon lines",
    ]
    if preset_id in (None, "why_net_less", "breakdown_fees", "is_consistent"):
        steps.append(":material/percent: Checking fee and GST on every payment line")
    steps.append(
        ":material/smart_toy: Asking the AI model to phrase the verified figures"
        if use_llm
        else ":material/rule: Writing the answer from the verified figures"
    )
    return steps


def humanize_trace_step(step: str) -> str | None:
    """Turn an internal trace entry into a line a merchant can read."""
    if step.startswith("provider=") or step.startswith("model="):
        return None
    name = step.split(": ", 1)[-1].strip()
    return TOOL_STEP_LABELS.get(name)


def stream_words(text: str):
    for token in re.split(r"(\s+)", text):
        if not token:
            continue
        yield token
        if token.strip():
            time.sleep(STREAM_WORD_DELAY)


def render_message_meta(meta: dict, *, show_trace: bool = True) -> None:
    if meta.get("welcome"):
        return
    badges = agent_mode_badge(meta.get("agent_mode", "keyword"))
    if meta.get("escalated_to_support"):
        badges += '<span class="badge badge-escalated">Escalated to Razorpay support</span>'
    st.markdown(badges, unsafe_allow_html=True)
    if meta.get("support_ticket_id"):
        st.markdown(f"**Ticket ID:** `{meta['support_ticket_id']}`")
    if meta.get("citations"):
        st.caption(f"Evidence: {', '.join(meta['citations'])}")
    if meta.get("fallback_reason"):
        st.caption(
            f"AI answer not used — {meta['fallback_reason']}. "
            "Answered from your settlement data using rules."
        )
    if show_trace and meta.get("tool_trace"):
        with st.expander("How this answer was built", icon=":material/manage_search:"):
            for step in meta["tool_trace"]:
                st.text(step)


def render_chat_message(
    msg: dict,
    *,
    settlement_id: str,
    decision,
    batches: dict,
    msg_idx: int,
) -> None:
    is_assistant = msg["role"] == "assistant"
    with st.chat_message(msg["role"], avatar=ASSISTANT_AVATAR if is_assistant else None):
        st.markdown(msg["content"])
        meta = msg.get("meta") or {}
        if is_assistant:
            render_message_meta(meta)
            render_ticket_cta(
                meta,
                settlement_id,
                decision,
                batches,
                key=f"raise_ticket_chat_{settlement_id}_{msg_idx}",
            )


def run_live_exchange(
    settlement_id: str,
    question: str,
    preset_id: str | None,
    decision,
    batches: dict,
) -> None:
    """Show the question, the assistant's working steps, then stream the answer."""
    append_chat_message(settlement_id, "user", question)
    with st.chat_message("user"):
        st.markdown(question)

    use_llm = bool(st.session_state["use_llm_qa"]) and not preset_id

    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        started = time.perf_counter()
        status = st.status("Checking your settlement data…", expanded=True)
        with status:
            for step in planned_steps(preset_id, use_llm):
                st.markdown(step)
                time.sleep(STEP_PACING_SECONDS)

        with st.skeleton(height=72):
            text, meta = resolve_answer(settlement_id, question, preset_id, decision, batches)

        with status:
            done = [
                label
                for label in (humanize_trace_step(s) for s in meta.get("tool_trace") or [])
                if label
            ]
            for label in dict.fromkeys(done):
                st.markdown(f":material/check_circle: {label}")
        status.update(
            label=f"Checked your settlement data in {time.perf_counter() - started:.1f}s",
            state="complete",
            expanded=False,
        )

        st.write_stream(stream_words(text))
        render_message_meta(meta, show_trace=False)
        render_ticket_cta(
            meta,
            settlement_id,
            decision,
            batches,
            key=f"raise_ticket_live_{settlement_id}_{st.session_state['qa_count']}",
        )

    append_chat_message(settlement_id, "assistant", text, meta)
    st.session_state["qa_count"] += 1


def render_settlement_chatbot(
    settlement_id: str,
    decision,
    batches: dict,
) -> None:
    """Chat surface: agent header, scrollable thread, quick replies, composer."""
    identity, actions = st.columns([4, 1], vertical_alignment="center")
    with identity:
        st.markdown(
            '<div class="chat-header">'
            '<div class="chat-avatar">₹</div>'
            "<div>"
            '<p class="chat-name">Settlement assistant</p>'
            '<p class="chat-presence"><span class="presence-dot"></span>'
            "Online · answers only from your Razorpay settlement data</p>"
            "</div></div>",
            unsafe_allow_html=True,
        )
    with actions:
        if st.button(
            "New chat",
            icon=":material/refresh:",
            key=f"reset_chat_{settlement_id}",
            width="stretch",
        ):
            st.session_state.get("chat_histories", {}).pop(settlement_id, None)
            st.rerun()

    thread = st.container(height=430, border=True, key="chat_thread")

    # MAX_QUESTIONS_PER_SESSION == 0 disables the cap (see settlement_qa).
    asked_out = (
        MAX_QUESTIONS_PER_SESSION > 0
        and st.session_state["qa_count"] >= MAX_QUESTIONS_PER_SESSION
    )
    pending: tuple[str, str | None] | None = None

    with st.container(horizontal=True, gap="small"):
        for preset_id, preset in PRESET_INTENTS.items():
            if st.button(
                preset["label"],
                key=f"chip_{settlement_id}_{preset_id}",
                disabled=asked_out,
            ):
                pending = (preset["label"], preset_id)

    prompt = st.chat_input(
        "Ask about this settlement…",
        key=f"chat_input_{settlement_id}",
        disabled=asked_out,
        submit_mode="disable",
    )
    if prompt and pending is None:
        pending = (prompt, None)

    if asked_out:
        st.markdown(
            f'<p class="chat-hint">Question limit reached '
            f"({MAX_QUESTIONS_PER_SESSION} per session). Refresh the page to reset.</p>",
            unsafe_allow_html=True,
        )
    elif MAX_QUESTIONS_PER_SESSION > 0:
        left = MAX_QUESTIONS_PER_SESSION - st.session_state["qa_count"]
        st.markdown(
            f'<p class="chat-hint">{left} of {MAX_QUESTIONS_PER_SESSION} questions left '
            "this session · every answer cites the settlement data it used</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<p class="chat-hint">Every answer cites the settlement data it used</p>',
            unsafe_allow_html=True,
        )

    with thread:
        for idx, msg in enumerate(get_chat_history(settlement_id)):
            render_chat_message(
                msg,
                settlement_id=settlement_id,
                decision=decision,
                batches=batches,
                msg_idx=idx,
            )
        if pending:
            run_live_exchange(settlement_id, pending[0], pending[1], decision, batches)
            st.rerun()


st.set_page_config(page_title="Razorpay Settlement Assistant", page_icon="₹", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
ensure_demo_data()

if "run" not in st.session_state:
    run_check()

if "qa_count" not in st.session_state:
    st.session_state["qa_count"] = 0
if "selected_settlement" not in st.session_state:
    st.session_state["selected_settlement"] = None
if "use_llm_qa" not in st.session_state:
    st.session_state["use_llm_qa"] = should_use_llm()
if "raised_tickets" not in st.session_state:
    st.session_state["raised_tickets"] = {}

engine: ReconciliationEngine = st.session_state["engine"]
run = st.session_state["run"]
metrics = run.metrics

# --- Header ---
st.markdown(
    '<div class="page-header">'
    "<h1>Razorpay Settlement Assistant</h1>"
    '<p class="page-subtitle">Check your Razorpay settlements — no uploads needed</p>'
    "</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown('<p class="section-label">Actions</p>', unsafe_allow_html=True)
    if st.button("Check settlements", type="primary", width="stretch"):
        with st.spinner("Checking settlements…"):
            run_check()
        st.rerun()
    st.session_state["use_llm_qa"] = st.toggle(
        "AI answers (Groq + Gemini + OpenRouter fallback)",
        value=st.session_state["use_llm_qa"],
        disabled=not should_use_llm(),
        help=(
            "Uses Groq first, then Gemini, then OpenRouter if earlier providers fail. "
            "Preset buttons stay rule-based."
        ),
    )
    if not should_use_llm():
        st.caption(
            "Set USE_LLM=1 and GROQ_API_KEY, GEMINI_API_KEY, or OPENROUTER_API_KEY "
            "in .env to enable AI."
        )
    else:
        providers = llm_providers_available()
        st.caption(
            f"AI model: `{get_llm_model(providers[0])}` via {providers[0]}"
            + (f" · fallback: {providers[1]}" if len(providers) > 1 else "")
        )
        st.caption("Type in the chat box for AI answers. Suggested buttons use rules.")

verified = metrics.get("verified_settlements", 0)
total = metrics.get("processed_settlements", 0)
needs = metrics.get("needs_attention_settlements", 0)

with st.container(border=True):
    st.markdown('<p class="section-label">Summary</p>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Verified", verified)
    c2.metric("Needs attention", needs)
    c3.metric("Total", total)

with st.container(border=True):
    st.markdown('<p class="section-label">Browse settlements</p>', unsafe_allow_html=True)
    filter_tab = st.radio("Filter", ["All", "Needs attention", "Verified"], horizontal=True)

    decisions = list(run.settlement_decisions)
    if filter_tab == "Verified":
        decisions = [d for d in decisions if d.integrity_status == SettlementIntegrityStatus.VERIFIED]
    elif filter_tab == "Needs attention":
        decisions = [d for d in decisions if d.integrity_status != SettlementIntegrityStatus.VERIFIED]

    decisions.sort(
        key=lambda d: (d.integrity_status == SettlementIntegrityStatus.VERIFIED, -d.net_amount_paise)
    )

    if not decisions:
        st.info("No settlements in this view.")
        selected_id = None
    else:
        options = {}
        for d in decisions:
            batch = next(b for b in engine.batches if b.settlement_id == d.settlement_id)
            status = "Verified" if d.integrity_status == SettlementIntegrityStatus.VERIFIED else "Needs attention"
            utr_short = d.utr[-6:] if d.utr else "—"
            label = f"{format_inr(d.net_amount_paise)} · {format_date(batch.processed_at)} · UTR …{utr_short} · {status}"
            options[label] = d.settlement_id

        labels = list(options.keys())
        default_idx = 0
        if st.session_state["selected_settlement"] in options.values():
            for i, lbl in enumerate(labels):
                if options[lbl] == st.session_state["selected_settlement"]:
                    default_idx = i
                    break

        picked = st.selectbox("Settlements", labels, index=default_idx, label_visibility="collapsed")
        selected_id = options[picked]
        st.session_state["selected_settlement"] = selected_id

if selected_id:
    decision = next(d for d in run.settlement_decisions if d.settlement_id == selected_id)
    batch = next(b for b in engine.batches if b.settlement_id == selected_id)

    with st.container(border=True):
        st.markdown('<p class="section-label">Settlement detail</p>', unsafe_allow_html=True)
        st.subheader(f"{format_inr(decision.net_amount_paise)} · {format_date(batch.processed_at)}")
        if decision.integrity_status == SettlementIntegrityStatus.VERIFIED:
            st.markdown('<p class="status-pill verified">✓ Verified</p>', unsafe_allow_html=True)
        else:
            st.markdown(
                f'<p class="status-pill attention">⚠ Needs attention — {decision.plain_issue}</p>',
                unsafe_allow_html=True,
            )

        st.markdown('<p class="section-label">Integrity checks</p>', unsafe_allow_html=True)
        for ctrl in decision.control_decisions:
            if ctrl.control_type in ("batch_integrity", "tax_lines"):
                render_check(ctrl)

        batches = engine.batch_map()
        show_raise_ticket = needs_support_ticket(decision)
        raised = st.session_state["raised_tickets"].get(selected_id)

        if show_raise_ticket and not raised:
            st.markdown(
                '<div class="support-panel">'
                '<p class="section-label">Razorpay support</p>'
                "<p>This issue cannot be fixed from your data alone. "
                "Use the button below to send the calculation breakdown to Razorpay support.</p>"
                "</div>",
                unsafe_allow_html=True,
            )
            render_raise_ticket_button(
                selected_id,
                decision,
                batches,
                key=f"raise_ticket_header_{selected_id}",
            )
        elif raised:
            st.markdown(
                '<div class="support-panel">'
                '<p class="section-label">Razorpay support</p>'
                f'<div class="ticket-raised">Ticket raised — <code>{raised.support_ticket_id}</code></div>'
                "<p style='margin-top:0.65rem;color:#5b21b6;'>Escalated to Razorpay support. "
                "They will investigate the issue shown above.</p>"
                "</div>",
                unsafe_allow_html=True,
            )

    with st.container(border=True):
        render_settlement_chatbot(selected_id, decision, batches)

    with st.expander("See payments", expanded=False):
        st.dataframe(
            [
                {
                    "Id": l.entity_id,
                    "Type": l.line_type,
                    "Amount": format_inr(l.amount),
                    "Fee": format_inr(l.fee),
                    "GST": format_inr(l.tax),
                    "Net": format_inr(l.credit - l.debit),
                }
                for l in batch.lines
            ],
            width="stretch",
            hide_index=True,
        )

st.markdown("---")
with st.expander("Download report", expanded=False):
    exceptions = engine.export_exceptions(run)
    export = {
        "run_id": run.run_id,
        "cutoff": str(run.cutoff_date),
        "metrics": metrics,
        "exceptions": exceptions,
    }
    st.download_button(
        "Download report (JSON)",
        json.dumps(export, indent=2, default=str),
        file_name=f"razorpay_settlement_assistant_{run.cutoff_date}.json",
        mime="application/json",
    )
    st.metric("Settlement integrity rate", f"{metrics.get('settlement_integrity_rate', 0):.1%}")
    st.metric("Tax-line pass rate", f"{metrics.get('tax_line_pass_rate', 0):.1%}")
    acc = metrics.get("labeled_control_accuracy")
    if acc is not None:
        st.metric("Demo labeled accuracy (independent verifier)", f"{acc:.1%}")
    st.caption(f"Label source: {metrics.get('label_source', '—')}")

    st.markdown("**Independent holdout** (hand-crafted, not from generator)")
    st.metric("Holdout integrity rate", f"{metrics.get('holdout_integrity_rate', 0):.1%}")
    hacc = metrics.get("holdout_labeled_accuracy")
    if hacc is not None:
        st.metric("Holdout labeled accuracy", f"{hacc:.1%}")
    st.caption(metrics.get("holdout_description", metrics.get("holdout_source", "")))
    holdout_exc = metrics.get("holdout_exceptions", [])
    if holdout_exc:
        st.markdown("Holdout exceptions")
        st.dataframe(holdout_exc, width="stretch", hide_index=True)

    st.markdown("#### Exception lifecycle")
    st.caption(
        "Historical integrity never changes — a control that failed, failed. Closure "
        "tracks only whether Razorpay later compensated the gap with an adjustment."
    )
    lc1, lc2, lc3 = st.columns(3)
    lc1.metric("Exceptions closed", metrics.get("lifecycle_exceptions_closed", 0))
    lc2.metric("Still open", metrics.get("lifecycle_exceptions_open", 0))
    closure = metrics.get("lifecycle_closure_rate")
    lc3.metric("Closure rate", f"{closure:.1%}" if closure is not None else "n/a")

    lifecycle_rows = metrics.get("lifecycle_rows", [])
    if lifecycle_rows:
        st.dataframe(
            [
                {
                    "Settlement": r["settlement_id"],
                    "Gap": r["delta_display"],
                    "State": getattr(r["state"], "value", r["state"]),
                    "Matched adjustment": r["matched_adjustment"] or "—",
                    "Days to close": r["days_to_close"] or "—",
                    "Evidence": r["dispute_packet"]["evidence_hash"],
                }
                for r in lifecycle_rows
            ],
            width="stretch",
            hide_index=True,
        )
    unmatched = metrics.get("lifecycle_unmatched_adjustments", [])
    if unmatched:
        st.caption(
            "Adjustments received but not bound to any exception: "
            f"{', '.join(unmatched)}. Nothing is bound unless the amount, direction, "
            "timing, and settlement reference all match exactly and uniquely."
        )

    st.metric("Throughput", f"{metrics.get('throughput_lines_per_sec', 0)} lines/s")
    if exceptions:
        st.dataframe(exceptions, width="stretch", hide_index=True)

    if st.button("Export run JSON to sample-output/", key="export_run_json"):
        SAMPLE_OUTPUT.mkdir(exist_ok=True)
        (SAMPLE_OUTPUT / "latest_run.json").write_text(
            json.dumps(export, indent=2, default=str)
        )
        st.success("Wrote sample-output/latest_run.json")
