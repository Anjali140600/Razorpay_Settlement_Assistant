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

from apps.universal_assistant import render_universal_assistant_launcher
from data.synthetic.generator import generate_demo_dataset
from src.agent.llm_client import should_use_llm, get_llm_model, llm_providers_available
from src.agent.triage import TriageResult, TriageVerdict
from src.agent.triage import classify as classify_triage
from src.connectors.loaders import load_pending_payments
from src.domain.models import PendingPayment, SettlementIntegrityStatus
from src.engine import ReconciliationEngine
from src.reporting import build_unsettled_payments_report

DEMO_DIR = ROOT / "data" / "synthetic" / "demo"
SAMPLE_OUTPUT = ROOT / "sample-output"

SETTLEMENT_REPORT_METRIC_HELP = {
    "Settlement integrity rate": (
        "**Formula:** Verified settlements ÷ Processed settlements × 100.  \n"
        "A settlement is verified only when both its batch amount and fee/GST checks pass."
    ),
    "Tax-line pass rate": (
        "**Formula:** Settlements passing the fee/GST check ÷ Processed settlements × 100."
    ),
    "Demo labeled accuracy (independent verifier)": (
        "**Formula:** Correct demo results ÷ Labeled demo settlements × 100.  \n"
        "A result is correct when its calculated status matches the expected label."
    ),
    "Holdout integrity rate": (
        "**Formula:** Verified holdout settlements ÷ Processed holdout settlements × 100."
    ),
    "Holdout labeled accuracy": (
        "**Formula:** Correct holdout results ÷ Labeled holdout settlements × 100."
    ),
    "Exceptions closed": (
        "**Formula:** Count of lifecycle exceptions matched to one valid later adjustment."
    ),
    "Still open": (
        "**Formula:** Count of lifecycle exceptions without a valid matching adjustment."
    ),
    "Closure rate": (
        "**Formula:** Closed lifecycle exceptions ÷ Total lifecycle exceptions × 100."
    ),
    "Throughput": (
        "**Formula:** Total reconciliation lines ÷ Processing time in seconds."
    ),
}

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

  /* The universal assistant is the only persistent chat entry point. */
  .st-key-universal_assistant_launcher {
    position: fixed;
    right: 1.5rem;
    bottom: 1.5rem;
    z-index: 1000000;
  }

  .st-key-universal_assistant_launcher button {
    width: 3.6rem !important;
    height: 3.6rem !important;
    min-height: 3.6rem !important;
    padding: 0 !important;
    border-radius: 999px !important;
    box-shadow: 0 10px 28px rgba(37, 99, 235, 0.38) !important;
  }

  .st-key-universal_assistant_launcher button span {
    font-size: 1.65rem !important;
  }

  .st-key-universal_assistant_thread {
    background: #f8fafc !important;
  }

  @media (max-width: 640px) {
    .st-key-universal_assistant_launcher {
      right: 1rem;
      bottom: 1rem;
    }
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


def instant_settlement_label(payment: PendingPayment) -> str:
    if payment.instant_eligible == "yes":
        return "Instant eligible"
    if payment.instant_eligible == "no":
        return "Standard settlement only"
    return "Eligibility unknown"


def render_pending_payment_panel(payment: PendingPayment) -> None:
    """Render the detail summary for a payment with no settlement yet."""
    st.markdown('<p class="section-label">Pending payment detail</p>', unsafe_allow_html=True)
    st.subheader(f"{format_inr(payment.amount)} · captured {format_date(payment.captured_at)}")
    st.markdown(
        '<p class="status-pill attention">⏳ Not yet settled</p>',
        unsafe_allow_html=True,
    )
    if payment.instant_eligible == "yes":
        st.success("Eligible for Instant Settlement")
    elif payment.instant_eligible == "no":
        st.info("Standard settlement only — not eligible for Instant Settlement")
    else:
        st.warning("Instant Settlement eligibility unavailable")
    if payment.expected_settlement_at:
        st.caption(f"Expected settlement: {payment.expected_settlement_at.strftime('%d %b %Y')} (calendar days)")


def run_check() -> None:
    engine = ReconciliationEngine(DEMO_DIR, eval_date=date(2026, 8, 30), use_llm=False)
    engine.load_sources()
    run = engine.run()
    st.session_state["engine"] = engine
    st.session_state["run"] = run


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


def compute_triage(settlement_id: str, decision, batches: dict) -> TriageResult | None:
    if not settlement_id or settlement_id not in batches or not decision:
        return None
    return classify_triage(settlement_id, batches[settlement_id], decision, batches)


st.set_page_config(page_title="Razorpay Settlement Assistant", page_icon="₹", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
ensure_demo_data()

if "run" not in st.session_state:
    run_check()

if "selected_settlement" not in st.session_state:
    st.session_state["selected_settlement"] = None
if "use_llm_qa" not in st.session_state:
    st.session_state["use_llm_qa"] = should_use_llm()
if "raised_tickets" not in st.session_state:
    st.session_state["raised_tickets"] = {}
if "filed_claims" not in st.session_state:
    st.session_state["filed_claims"] = {}

assistant_focus_request = st.session_state.pop("assistant_focus_request", None)
if assistant_focus_request:
    if assistant_focus_request.get("kind") == "settlement":
        st.session_state["browse_category"] = "Settlements"
        st.session_state["settlement_filter"] = "All"
        st.session_state["selected_settlement"] = assistant_focus_request.get("subject_id")
    elif assistant_focus_request.get("kind") == "payment":
        st.session_state["browse_category"] = "Unsettled Payments"

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

    st.markdown('<p class="section-label">Browse</p>', unsafe_allow_html=True)
    browse_category = st.radio(
        "Browse category",
        ["Settlements", "Unsettled Payments"],
        key="browse_category",
        label_visibility="collapsed",
    )

pending_payments = load_pending_payments(DEMO_DIR / "recon.json", DEMO_DIR / "manifest.json")

with st.container(border=True):
    st.markdown('<p class="section-label">Summary</p>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    if browse_category == "Settlements":
        c1.metric("Verified", metrics.get("verified_settlements", 0))
        c2.metric("Needs attention", metrics.get("needs_attention_settlements", 0))
        c3.metric("Total", metrics.get("processed_settlements", 0))
    else:
        instant_eligible = sum(payment.instant_eligible == "yes" for payment in pending_payments)
        unsettled_amount = sum(payment.amount for payment in pending_payments)
        c1.metric("Unsettled payments", len(pending_payments))
        c2.metric("Instant eligible", instant_eligible)
        c3.metric("Total amount", format_inr(unsettled_amount))

selected_id = None
selected_pending_id = None

if browse_category == "Settlements":
    with st.container(border=True):
        st.markdown('<p class="section-label">Browse settlements</p>', unsafe_allow_html=True)
        filter_tab = st.radio("Filter", ["All", "Needs attention", "Verified"], horizontal=True, key="settlement_filter")

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

            if assistant_focus_request and assistant_focus_request.get("kind") == "settlement":
                requested_id = assistant_focus_request.get("subject_id")
                requested_label = next((label for label, sid in options.items() if sid == requested_id), None)
                if requested_label:
                    st.session_state["settlement_picker"] = requested_label

            picked = st.selectbox("Settlements", labels, index=default_idx, label_visibility="collapsed", key="settlement_picker")
            selected_id = options[picked]
            st.session_state["selected_settlement"] = selected_id
else:
    with st.container(border=True):
        st.markdown('<p class="section-label">Pending payments (not yet settled)</p>', unsafe_allow_html=True)
        if not pending_payments:
            st.info("No unsettled payments.")
        else:
            pending_options = {
                (
                    f"{format_inr(p.amount)} · {p.order_id or p.entity_id} · "
                    f"captured {format_date(p.captured_at)} · {instant_settlement_label(p)}"
                ): p.entity_id
                for p in pending_payments
            }
            pending_labels = ["— none selected —"] + list(pending_options.keys())
            if assistant_focus_request and assistant_focus_request.get("kind") == "payment":
                requested_id = assistant_focus_request.get("subject_id")
                requested_label = next(
                    (label for label, pid in pending_options.items() if pid == requested_id),
                    None,
                )
                if requested_label:
                    st.session_state["pending_payment_picker"] = requested_label
            picked_pending = st.selectbox(
                "Pending payments", pending_labels, label_visibility="collapsed", key="pending_payment_picker"
            )
            if picked_pending != "— none selected —":
                selected_pending_id = pending_options[picked_pending]

if selected_pending_id:
    payment = next(p for p in pending_payments if p.entity_id == selected_pending_id)
    with st.container(border=True):
        render_pending_payment_panel(payment)

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
        triage = compute_triage(selected_id, decision, batches)
        raised = st.session_state["raised_tickets"].get(selected_id)
        filed = st.session_state["filed_claims"].get(selected_id)
        verdict = triage.verdict if triage else None

        if filed:
            st.markdown(
                '<div class="support-panel">'
                '<p class="section-label">Compensation claim</p>'
                f'<div class="ticket-raised">Claim filed — <code>{filed.compensation_claim_id}</code></div>'
                "<p style='margin-top:0.65rem;color:#5b21b6;'>Submitted to Razorpay for the confirmed "
                "shortfall shown above.</p>"
                "</div>",
                unsafe_allow_html=True,
            )
        elif verdict == TriageVerdict.ALREADY_COMPENSATED:
            st.markdown(
                '<div class="support-panel">'
                '<p class="section-label">Already resolved</p>'
                f"<p>{triage.detail} No action needed — the batch-integrity check above stays "
                "flagged because history is never rewritten, but the shortfall itself is closed.</p>"
                "</div>",
                unsafe_allow_html=True,
            )
        elif verdict == TriageVerdict.AUTO_COMPENSABLE and not raised:
            st.markdown(
                '<div class="support-panel">'
                '<p class="section-label">Compensation available</p>'
                f"<p>{triage.detail} You choose what happens next — "
                "open the support assistant to review a claim or contact Razorpay support.</p>"
                "</div>",
                unsafe_allow_html=True,
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
        elif verdict in (TriageVerdict.AUTO_COMPENSABLE, TriageVerdict.NEEDS_SUPPORT):
            st.markdown(
                '<div class="support-panel">'
                '<p class="section-label">Razorpay support</p>'
                "<p>This issue cannot be fixed from your data alone. "
                "Open the support assistant to review a prefilled ticket with this calculation breakdown.</p>"
                "</div>",
                unsafe_allow_html=True,
            )

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

if browse_category == "Settlements" or pending_payments:
    st.markdown("---")

if browse_category == "Settlements":
    with st.expander("Download settlement report", expanded=False):
        exceptions = engine.export_exceptions(run)
        export = {
            "run_id": run.run_id,
            "cutoff": str(run.cutoff_date),
            "metrics": metrics,
            "exceptions": exceptions,
        }
        st.download_button(
            "Download settlement report (JSON)",
            json.dumps(export, indent=2, default=str),
            file_name=f"razorpay_settlement_assistant_{run.cutoff_date}.json",
            mime="application/json",
            key="download_settlement_report",
        )
        st.metric(
            "Settlement integrity rate",
            f"{metrics.get('settlement_integrity_rate', 0):.1%}",
            help=SETTLEMENT_REPORT_METRIC_HELP["Settlement integrity rate"],
        )
        st.metric(
            "Tax-line pass rate",
            f"{metrics.get('tax_line_pass_rate', 0):.1%}",
            help=SETTLEMENT_REPORT_METRIC_HELP["Tax-line pass rate"],
        )
        acc = metrics.get("labeled_control_accuracy")
        if acc is not None:
            st.metric(
                "Demo labeled accuracy (independent verifier)",
                f"{acc:.1%}",
                help=SETTLEMENT_REPORT_METRIC_HELP[
                    "Demo labeled accuracy (independent verifier)"
                ],
            )
        st.caption(f"Label source: {metrics.get('label_source', '—')}")

        st.markdown("**Independent holdout** (hand-crafted, not from generator)")
        st.metric(
            "Holdout integrity rate",
            f"{metrics.get('holdout_integrity_rate', 0):.1%}",
            help=SETTLEMENT_REPORT_METRIC_HELP["Holdout integrity rate"],
        )
        hacc = metrics.get("holdout_labeled_accuracy")
        if hacc is not None:
            st.metric(
                "Holdout labeled accuracy",
                f"{hacc:.1%}",
                help=SETTLEMENT_REPORT_METRIC_HELP["Holdout labeled accuracy"],
            )
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
        lc1.metric(
            "Exceptions closed",
            metrics.get("lifecycle_exceptions_closed", 0),
            help=SETTLEMENT_REPORT_METRIC_HELP["Exceptions closed"],
        )
        lc2.metric(
            "Still open",
            metrics.get("lifecycle_exceptions_open", 0),
            help=SETTLEMENT_REPORT_METRIC_HELP["Still open"],
        )
        closure = metrics.get("lifecycle_closure_rate")
        lc3.metric(
            "Closure rate",
            f"{closure:.1%}" if closure is not None else "n/a",
            help=SETTLEMENT_REPORT_METRIC_HELP["Closure rate"],
        )

        lifecycle_rows = metrics.get("lifecycle_rows", [])
        if lifecycle_rows:
            st.dataframe(
                [
                    {
                        "Settlement": r["settlement_id"],
                        "Gap": r["delta_display"],
                        "State": getattr(r["state"], "value", r["state"]),
                        "Matched adjustment": r["matched_adjustment"] or "—",
                        "Days to close": (
                            str(r["days_to_close"])
                            if r["days_to_close"] is not None
                            else "—"
                        ),
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

        st.metric(
            "Throughput",
            f"{metrics.get('throughput_lines_per_sec', 0)} lines/s",
            help=SETTLEMENT_REPORT_METRIC_HELP["Throughput"],
        )
        if exceptions:
            st.dataframe(exceptions, width="stretch", hide_index=True)

        if st.button("Export run JSON to sample-output/", key="export_run_json"):
            SAMPLE_OUTPUT.mkdir(exist_ok=True)
            (SAMPLE_OUTPUT / "latest_run.json").write_text(
                json.dumps(export, indent=2, default=str)
            )
            st.success("Wrote sample-output/latest_run.json")
elif pending_payments:
    with st.expander("Download unsettled payments report", expanded=False):
        unsettled_export = build_unsettled_payments_report(pending_payments, date.today())
        unsettled_summary = unsettled_export["summary"]
        report_columns = st.columns(4)
        report_columns[0].metric("Unsettled payments", unsettled_summary["payment_count"])
        report_columns[1].metric(
            "Total amount", format_inr(unsettled_summary["total_amount_paise"])
        )
        report_columns[2].metric("Instant eligible", unsettled_summary["instant_eligible"])
        report_columns[3].metric("Eligibility unknown", unsettled_summary["eligibility_unknown"])

        st.dataframe(
            [
                {
                    "Payment": payment.entity_id,
                    "Order": payment.order_id or "—",
                    "Amount": format_inr(payment.amount),
                    "Method": payment.method or "—",
                    "Captured": format_date(payment.captured_at),
                    "Expected settlement": format_date(payment.expected_settlement_at),
                    "Instant Settlement": instant_settlement_label(payment),
                }
                for payment in pending_payments
            ],
            width="stretch",
            hide_index=True,
        )
        st.download_button(
            "Download unsettled payments report (JSON)",
            json.dumps(unsettled_export, indent=2),
            file_name=f"razorpay_unsettled_payments_{unsettled_export['cutoff']}.json",
            mime="application/json",
            key="download_unsettled_report",
        )

render_universal_assistant_launcher(
    batches=engine.batch_map(),
    decisions=list(run.settlement_decisions),
    pending_payments=pending_payments,
    use_llm=bool(st.session_state["use_llm_qa"]),
)
