"""Razorpay Settlement Assistant — merchant-facing settlement verification and Q&A."""

from __future__ import annotations

import json
import sys
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
  .badge-cerebras { background: #dbeafe; color: #1e40af; border-color: #93c5fd; }
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

  .chat-layout {
    display: flex;
    gap: 1rem;
    align-items: stretch;
    min-height: 420px;
  }

  .suggestion-menu {
    flex: 0 0 220px;
    background: #f8fafc;
    border: 1px solid var(--card-border);
    border-radius: 12px;
    padding: 0.85rem;
  }

  .suggestion-menu-title {
    font-size: 0.78rem;
    font-weight: 700;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin: 0 0 0.65rem 0.15rem;
  }

  .suggestion-item {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.7rem 0.85rem;
    margin-bottom: 0.45rem;
    border-radius: 10px;
    border: 1px solid #e2e8f0;
    background: #ffffff;
    color: var(--text-primary);
    font-size: 0.95rem;
    font-weight: 600;
    line-height: 1.35;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .suggestion-item:hover {
    background: var(--accent-soft);
    border-color: #93c5fd;
  }

  .chat-panel {
    flex: 1;
    min-width: 0;
    background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%);
    border: 1px solid #fcd34d;
    border-radius: 12px;
    padding: 0.85rem 1rem 0.65rem;
    min-height: 380px;
  }

  /* Yellow chat shell (Streamlit bordered container wrapping messages + input) */
  div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatInput"]) {
    background: linear-gradient(180deg, #fffbeb 0%, #fef3c7 100%) !important;
    border: 1px solid #fcd34d !important;
    border-radius: 12px !important;
    padding: 0.85rem 1rem 0.65rem !important;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6) !important;
  }

  div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatInput"]) div[data-testid="stChatMessage"] {
    background: transparent !important;
  }

  div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatInput"])
    div[data-testid="stChatMessageContent"] {
    background: #ffffff !important;
    border: 1px solid #fde68a !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 2px rgba(180, 83, 9, 0.06) !important;
  }

  div[data-testid="stVerticalBlockBorderWrapper"]:has(div[data-testid="stChatInput"])
    div[data-testid="stChatInput"] > div {
    background: #fffef5 !important;
    border-color: #fbbf24 !important;
  }

  div[data-testid="stChatMessage"] {
    font-size: 1rem !important;
    line-height: 1.6 !important;
  }

  div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
    margin-bottom: 0.35rem !important;
  }

  .chat-meta {
    margin-top: 0.35rem;
    font-size: 0.88rem;
    color: var(--text-muted);
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
        "cerebras": ("Answered via Cerebras", "badge-cerebras"),
        "keyword": ("Answered via rules", "badge-keyword"),
    }
    label, css = labels.get(mode, ("Answered via rules", "badge-keyword"))
    return f'<span class="badge {css}">{label}</span>'


WELCOME_MESSAGE = (
    "Hi — I'm your settlement assistant. Pick a suggested question on the left, "
    "or type your own below. I only answer from your loaded Razorpay data."
)


def get_chat_history(settlement_id: str) -> list[dict]:
    if "chat_histories" not in st.session_state:
        st.session_state["chat_histories"] = {}
    histories = st.session_state["chat_histories"]
    if settlement_id not in histories:
        histories[settlement_id] = [{"role": "assistant", "content": WELCOME_MESSAGE, "meta": {"welcome": True}}]
    return histories[settlement_id]


def append_chat_message(settlement_id: str, role: str, content: str, meta: dict | None = None) -> None:
    get_chat_history(settlement_id).append({"role": role, "content": content, "meta": meta or {}})


def envelope_to_meta(ans, *, ai_requested: bool = False) -> dict:
    mode = getattr(ans, "agent_mode", "keyword")
    return {
        "agent_mode": mode,
        "escalated_to_support": getattr(ans, "escalated_to_support", False),
        "support_ticket_id": getattr(ans, "support_ticket_id", None),
        "citations": getattr(ans, "citations", None) or [],
        "tool_trace": getattr(ans, "tool_trace", None),
        "abstained": getattr(ans, "abstained", False),
        "fallback_reason": last_llm_error() if (ai_requested and mode == "keyword") else None,
    }


def ask_settlement_question(
    settlement_id: str,
    question: str,
    *,
    preset_id: str | None = None,
    decision=None,
    batches: dict | None = None,
) -> None:
    """Append user + assistant messages to the settlement chat thread."""
    if st.session_state["qa_count"] >= MAX_QUESTIONS_PER_SESSION:
        return

    batches = batches or engine.batch_map()
    raised_ticket_id = (
        st.session_state["raised_tickets"][settlement_id].support_ticket_id
        if settlement_id in st.session_state["raised_tickets"]
        else None
    )

    append_chat_message(settlement_id, "user", question)

    if preset_id:
        ans = answer_preset(preset_id, settlement_id, batches)
    else:
        ok, err = validate_question_input(question)
        if not ok:
            append_chat_message(settlement_id, "assistant", err, {"abstained": True})
            return
        ans = answer_free_text(
            question,
            settlement_id,
            batches,
            use_llm=st.session_state["use_llm_qa"],
            settlement_decision=decision,
            raised_ticket_id=raised_ticket_id,
        )
        _ = question_hash(sanitize_question(question))

    text = filter_response_text(ans.answer_text)
    ai_requested = not preset_id and bool(st.session_state["use_llm_qa"])
    append_chat_message(
        settlement_id, "assistant", text, envelope_to_meta(ans, ai_requested=ai_requested)
    )
    st.session_state["qa_count"] += 1


def render_chat_message(msg: dict) -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        meta = msg.get("meta") or {}
        if meta.get("welcome"):
            return
        badges = agent_mode_badge(meta.get("agent_mode", "keyword"))
        if meta.get("escalated_to_support"):
            badges += '<span class="badge badge-escalated">Escalated to Razorpay support</span>'
        if badges:
            st.markdown(badges, unsafe_allow_html=True)
        if meta.get("support_ticket_id"):
            st.markdown(f"**Ticket ID:** `{meta['support_ticket_id']}`")
        if meta.get("citations"):
            st.caption(f"Cited: {', '.join(meta['citations'])}")
        if meta.get("fallback_reason"):
            st.caption(
                f"AI answer not used — {meta['fallback_reason']}. "
                "Answered from your settlement data using rules."
            )
        if meta.get("tool_trace"):
            with st.expander("How this answer was built"):
                for step in meta["tool_trace"]:
                    st.text(step)


def render_settlement_chatbot(
    settlement_id: str,
    decision,
    batches: dict,
) -> None:
    """Chatbot UI: vertical suggestion menu + conversation thread."""
    st.markdown('<p class="section-label">Settlement assistant</p>', unsafe_allow_html=True)
    st.caption("Ask about fees, net amount, or consistency — answers use your settlement data only.")

    menu_col, chat_col = st.columns([1, 2.6], gap="medium")

    with menu_col:
        st.markdown('<p class="suggestion-menu-title">Suggested questions</p>', unsafe_allow_html=True)
        ask_disabled = st.session_state["qa_count"] >= MAX_QUESTIONS_PER_SESSION
        if ask_disabled:
            st.caption(f"Limit reached ({MAX_QUESTIONS_PER_SESSION}/session). Refresh to reset.")

        for preset_id, preset in PRESET_INTENTS.items():
            if st.button(
                preset["label"],
                key=f"suggest_{settlement_id}_{preset_id}",
                width="stretch",
                disabled=ask_disabled,
            ):
                st.session_state["pending_chat_question"] = {
                    "settlement_id": settlement_id,
                    "question": preset["label"],
                    "preset_id": preset_id,
                }
                st.rerun()

    with chat_col:
        with st.container(border=True):
            history = get_chat_history(settlement_id)
            for msg in history:
                render_chat_message(msg)

            pending = st.session_state.pop("pending_chat_question", None)
            if pending and pending.get("settlement_id") == settlement_id:
                ask_settlement_question(
                    settlement_id,
                    pending["question"],
                    preset_id=pending.get("preset_id"),
                    decision=decision,
                    batches=batches,
                )
                st.rerun()

            if prompt := st.chat_input(
                "Ask about this settlement…",
                key=f"chat_input_{settlement_id}",
                disabled=ask_disabled,
            ):
                ask_settlement_question(
                    settlement_id,
                    prompt,
                    decision=decision,
                    batches=batches,
                )
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
        "AI answers (Groq + Cerebras fallback)",
        value=st.session_state["use_llm_qa"],
        disabled=not should_use_llm(),
        help="Uses Groq first, then Cerebras if Groq fails. Preset buttons stay rule-based.",
    )
    if not should_use_llm():
        st.caption("Set USE_LLM=1 and GROQ_API_KEY or CEREBRAS_API_KEY in .env to enable AI.")
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
            if st.button("Raise ticket with Razorpay support", type="primary", width="stretch"):
                ticket_env = raise_support_ticket(selected_id, decision, batches)
                st.session_state["raised_tickets"][selected_id] = ticket_env
                append_chat_message(
                    selected_id,
                    "assistant",
                    f"Support ticket raised — `{ticket_env.support_ticket_id}`. "
                    "Razorpay will investigate the calculation issue shown above.",
                    envelope_to_meta(ticket_env),
                )
                st.rerun()
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

    st.metric("Throughput", f"{metrics.get('throughput_lines_per_sec', 0)} lines/s")
    if exceptions:
        st.dataframe(exceptions, width="stretch", hide_index=True)

    SAMPLE_OUTPUT.mkdir(exist_ok=True)
    (SAMPLE_OUTPUT / "latest_run.json").write_text(json.dumps(export, indent=2, default=str))
    (SAMPLE_OUTPUT / "cli_run.json").write_text(json.dumps(export, indent=2, default=str))
