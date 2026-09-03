# Pending Settlement Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the settlement chatbot answer "where is my money" / "when will I get paid" and "instant / same day / now" for a payment that has been captured but has **no settlement yet** — a state the current pipeline cannot represent at all.

**Architecture:** Additive parallel path. A new `PendingPayment` model, a new loader that reads unsettled recon rows (`settlement_id: null`), a new standalone answer function with its own tiny keyword classifier, and a second Streamlit selector wired to it. Nothing in the existing settlement-scoped pipeline (`SettlementLine`, `attach_lines_to_batches`, `SettlementEvidenceTools`, `triage.classify()`, `route_free_text()`) is modified.

**Tech Stack:** Python 3, Pydantic v1/v2-style `BaseModel`, pytest, Streamlit.

**Spec:** `docs/superpowers/specs/2026-09-03-pending-settlement-status-design.md`

## Global Constraints

- Data boundary: settlements + recon data only — no bank/ledger/live API data (spec, "Hard constraint").
- Never fabricate `instant_eligible`; the tri-state (`"yes"|"no"|"unknown"`) is set explicitly per row and read verbatim — never inferred from other fields.
- Never say "not settled yet" without also giving the expected date, in `answer_pending_query()`.
- Calendar-day math only for `expected_settlement_at` (T+2 as `captured_at + timedelta(days=2)`) — no business-day/holiday/timezone logic.
- Do not make `SettlementLine.settlement_id` nullable. Do not route pending payments through `route_free_text()` or `triage.classify()`.
- Do not add free-text search across pending payments (amount/order-id) — out of scope for this plan.

---

### Task 1: `PendingPayment` model

**Files:**
- Modify: `src/domain/models.py` (add new class; file already imports `date`, `datetime` from `datetime`, and `BaseModel`, `Field` from `pydantic` at the top)
- Test: `tests/test_domain_models.py` (create if it doesn't exist — check first with `ls tests/test_domain_models.py`)

**Interfaces:**
- Produces: `PendingPayment` — consumed by Task 3 (loader) and Task 4 (answer function).

- [ ] **Step 1: Write the failing test**

Check if `tests/test_domain_models.py` exists. If not, create it with this content. If it exists, append this test function (adding `PendingPayment` to the existing import line from `src.domain.models`).

```python
"""Domain model tests."""

from __future__ import annotations

from datetime import date, datetime

from src.domain.models import PendingPayment


def test_pending_payment_defaults():
    p = PendingPayment(
        entity_id="pay_pending_001",
        amount=50000,
        captured_at=datetime(2026, 8, 28, 10, 0, 0),
    )
    assert p.currency == "INR"
    assert p.cycle_type == "standard"
    assert p.instant_eligible == "unknown"
    assert p.order_id is None
    assert p.method is None
    assert p.expected_settlement_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_domain_models.py::test_pending_payment_defaults -v`
Expected: FAIL with `ImportError: cannot import name 'PendingPayment'`

- [ ] **Step 3: Add the model**

In `src/domain/models.py`, add this class after `SettlementLine` (after its closing line, before `class SettlementBatch`):

```python
class PendingPayment(BaseModel):
    """A payment that has been captured but has no settlement yet.

    Deliberately separate from SettlementLine: it has no batch, no UTR, no
    fee/tax lines, and no triage verdict — it is a different shape of fact,
    not a SettlementLine with fields missing.
    """

    entity_id: str
    order_id: str | None = None
    amount: int  # paise
    currency: str = "INR"
    method: str | None = None
    captured_at: datetime
    cycle_type: str = "standard"  # "standard" | "instant_eligible"
    instant_eligible: str = "unknown"  # "yes" | "no" | "unknown" — never inferred, always read from source data
    expected_settlement_at: date | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_domain_models.py::test_pending_payment_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/domain/models.py tests/test_domain_models.py
git commit -m "feat: add PendingPayment model for captured-but-unsettled payments"
```

---

### Task 2: Generator — pending payment rows + settlement-cycle policy

**Files:**
- Modify: `data/synthetic/generator.py`
- Test: `tests/test_synthetic_generator.py` (create if it doesn't exist — check first)

**Interfaces:**
- Consumes: nothing new (uses existing `recon_lines`, `_ts`, `payment_counter` locals inside `generate_demo_dataset`).
- Produces: `recon.json` gains rows shaped like existing payment rows but with `"settled": false`, `"settlement_id": None`, `"settlement_utr": None`, `"settled_at": None`, plus new keys `"captured_at"` (ISO string), `"cycle_type"` (`"standard"` or `"instant_eligible"`), `"instant_eligible"` (`"yes"|"no"|"unknown"`). `manifest.json` gains `"pending_payment_lines": <int>` and `"settlement_cycle": {"standard_days": 2, "instant_available": true}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_synthetic_generator.py`:

```python
"""Synthetic generator tests for the pending-payment dataset extension."""

from __future__ import annotations

import json
from pathlib import Path

from data.synthetic.generator import generate_demo_dataset


def test_generator_emits_pending_payments(tmp_path: Path):
    generate_demo_dataset(tmp_path, repo_root=tmp_path)

    recon = json.loads((tmp_path / "recon.json").read_text())
    items = recon["items"] if isinstance(recon, dict) else recon
    pending = [r for r in items if r.get("settlement_id") is None]

    assert len(pending) >= 3
    eligibilities = {r["instant_eligible"] for r in pending}
    assert eligibilities == {"yes", "no", "unknown"}
    for row in pending:
        assert row["settled"] is False
        assert row["settlement_utr"] is None
        assert row["settled_at"] is None
        assert "captured_at" in row
        assert row["cycle_type"] in ("standard", "instant_eligible")

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["pending_payment_lines"] == len(pending)
    assert manifest["settlement_cycle"] == {"standard_days": 2, "instant_available": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_synthetic_generator.py -v`
Expected: FAIL (`assert len(pending) >= 3` fails — 0 pending rows today, or `KeyError`/`AssertionError` on manifest keys)

- [ ] **Step 3: Add pending rows and cycle policy to the generator**

In `data/synthetic/generator.py`, add a new helper function next to `add_payment` (after its closing `return eid`, before `def add_refund`):

```python
    def add_pending_payment(
        captured_day: int,
        amount_inr: float,
        *,
        idx: int,
        instant_eligible: str,
        method: str | None = None,
    ) -> None:
        """A payment captured but not yet settled — no settlement_id, no UTR."""
        nonlocal line_counter, payment_counter
        amount = paise(amount_inr)
        payment_counter += 1
        line_counter += 1
        eid = f"pay_pending_{idx:03d}"
        cycle_type = "instant_eligible" if instant_eligible == "yes" else "standard"
        recon_lines.append(
            {
                "currency": "INR",
                "on_hold": False,
                "settled": False,
                "settlement_id": None,
                "settlement_utr": None,
                "settled_at": None,
                "entity_id": eid,
                "type": "payment",
                "debit": 0,
                "credit": 0,
                "amount": amount,
                "fee": 0,
                "tax": 0,
                "created_at": _ts(captured_day, hour=random.randint(0, 23)),
                "captured_at": _ts(captured_day, hour=random.randint(0, 23)),
                "payment_id": None,
                "order_id": f"ord_pending_{idx}",
                "method": method or random.choice(METHODS),
                "cycle_type": cycle_type,
                "instant_eligible": instant_eligible,
            }
        )
```

Then, right after the `# --- Profile: combo mess ...` block and its `finalize_settlement(sid, utr, proc_day)` call (immediately before the `# ========== FAILURES ...` comment), add:

```python
    # --- Profile: pending payments (captured, not yet settled) ---
    add_pending_payment(30, 499.0, idx=0, instant_eligible="no", method="upi")
    add_pending_payment(31, 12500.0, idx=1, instant_eligible="yes", method="card")
    add_pending_payment(32, 899.0, idx=2, instant_eligible="unknown", method="upi")
```

(`captured_day` 30-32 falls after the last real settlement's `proc_day` of 29, keeping it clearly in "still pending" territory relative to `BASE_DATE`.)

Then, in the `manifest` dict construction near the end of `generate_demo_dataset` (right before `(output_dir / "manifest.json").write_text(...)`), add two keys:

```python
    manifest = {
        "settlements": len(settlements),
        "recon_lines": len(recon_lines),
        "payment_lines": sum(1 for l in recon_lines if l["type"] == "payment"),
        "refund_lines": sum(1 for l in recon_lines if l["type"] == "refund"),
        "transfer_lines": sum(1 for l in recon_lines if l["type"] == "transfer"),
        "adjustment_lines": sum(1 for l in recon_lines if l["type"] == "adjustment"),
        "verified_settlements": verified,
        "exception_settlements": needs,
        "exception_ids": exception_ids,
        "unix_timestamp_lines": sum(1 for l in recon_lines if isinstance(l.get("created_at"), int)),
        "pending_payment_lines": sum(1 for l in recon_lines if l.get("settlement_id") is None),
        "settlement_cycle": {"standard_days": 2, "instant_available": True},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_synthetic_generator.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate the committed demo dataset and confirm nothing else breaks**

Run:
```bash
python -m data.synthetic.generator
python -m pytest tests/test_reconciliation.py tests/test_lifecycle_runner.py tests/test_settlement_qa.py tests/test_triage.py -v
```
Expected: all PASS. (The `verify_labels_against_contract` label check inside `generate_demo_dataset` only ever looks at recon lines whose `settlement_id` matches a real settlement id, per `src/eval/independent_verifier.py:11` (`sid_lines = [l for l in lines if l.get("settlement_id") == settlement_id]`) — pending rows with `settlement_id: None` are automatically excluded and cannot break label verification.)

- [ ] **Step 6: Commit**

```bash
git add data/synthetic/generator.py tests/test_synthetic_generator.py data/synthetic/demo/recon.json data/synthetic/demo/manifest.json data/eval_labels.json
git commit -m "feat: generate captured-but-unsettled payment rows and settlement-cycle policy"
```

---

### Task 3: `load_pending_payments()` loader

**Files:**
- Modify: `src/connectors/loaders.py`
- Test: `tests/test_loaders.py` (create if it doesn't exist — check first)

**Interfaces:**
- Consumes: `data/synthetic/demo/recon.json` shape from Task 2; `PendingPayment` from Task 1.
- Produces: `load_pending_payments(recon_path: Path, manifest_path: Path) -> list[PendingPayment]` — consumed by Task 5 (Streamlit UI).

- [ ] **Step 1: Write the failing test**

Create `tests/test_loaders.py` (or append if it exists, importing `load_pending_payments` into the existing import line):

```python
"""Loader tests for the pending-payment path."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from src.connectors.loaders import load_pending_payments


def test_load_pending_payments_computes_expected_date(tmp_path: Path):
    recon_path = tmp_path / "recon.json"
    manifest_path = tmp_path / "manifest.json"
    recon_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "entity_id": "pay_pending_000",
                        "type": "payment",
                        "amount": 49900,
                        "fee": 0,
                        "tax": 0,
                        "currency": "INR",
                        "settlement_id": None,
                        "order_id": "ord_pending_0",
                        "method": "upi",
                        "captured_at": "2026-08-30T10:00:00",
                        "cycle_type": "standard",
                        "instant_eligible": "no",
                    },
                    {
                        "entity_id": "pay_settled_000",
                        "type": "payment",
                        "amount": 100000,
                        "fee": 2000,
                        "tax": 300,
                        "currency": "INR",
                        "settlement_id": "setl_x",
                        "order_id": "ord_1",
                        "method": "card",
                        "settled": True,
                    },
                ]
            }
        )
    )
    manifest_path.write_text(json.dumps({"settlement_cycle": {"standard_days": 2, "instant_available": True}}))

    pending = load_pending_payments(recon_path, manifest_path)

    assert len(pending) == 1
    p = pending[0]
    assert p.entity_id == "pay_pending_000"
    assert p.amount == 49900
    assert p.order_id == "ord_pending_0"
    assert p.cycle_type == "standard"
    assert p.instant_eligible == "no"
    assert p.expected_settlement_at == date(2026, 8, 30) + timedelta(days=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_loaders.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_pending_payments'`

- [ ] **Step 3: Write the loader**

In `src/connectors/loaders.py`, change the import line at the top from:

```python
from src.domain.models import BankEntry, LedgerEntry, SettlementBatch, SettlementLine
```

to:

```python
from src.domain.models import BankEntry, LedgerEntry, PendingPayment, SettlementBatch, SettlementLine
```

Then add this function after `attach_lines_to_batches` (after its closing `return list(by_id.values())`, before `def load_bank_csv`):

```python
def load_pending_payments(recon_path: Path, manifest_path: Path) -> list[PendingPayment]:
    """Load captured-but-unsettled payments — recon rows with no settlement_id yet.

    Kept separate from load_recon_json/attach_lines_to_batches: those two only ever
    handle lines that already belong to a settlement, and a pending payment has no
    batch, UTR, or fee/tax lines to attach.
    """
    data = json.loads(recon_path.read_text())
    items = data.get("items", data) if isinstance(data, dict) else data

    standard_days = 2
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        standard_days = manifest.get("settlement_cycle", {}).get("standard_days", 2)

    pending: list[PendingPayment] = []
    for row in items:
        if row.get("settlement_id"):
            continue
        captured_at = _parse_dt(row.get("captured_at") or row.get("created_at"))
        if captured_at is None:
            continue
        pending.append(
            PendingPayment(
                entity_id=str(row.get("entity_id", "")),
                order_id=row.get("order_id"),
                amount=int(row.get("amount", 0)),
                currency=str(row.get("currency", "INR")),
                method=row.get("method"),
                captured_at=captured_at,
                cycle_type=str(row.get("cycle_type", "standard")),
                instant_eligible=str(row.get("instant_eligible", "unknown")),
                expected_settlement_at=captured_at.date() + timedelta(days=standard_days),
            )
        )
    return pending
```

Add `from datetime import timedelta` alongside the existing `from datetime import date, datetime` import at the top of the file (change that line to `from datetime import date, datetime, timedelta`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_loaders.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/connectors/loaders.py tests/test_loaders.py
git commit -m "feat: load captured-but-unsettled payments from recon.json"
```

---

### Task 4: `answer_pending_query()` answer function

**Files:**
- Modify: `src/agent/settlement_qa.py`
- Test: `tests/test_settlement_qa.py`

**Interfaces:**
- Consumes: `PendingPayment` from Task 1.
- Produces: `answer_pending_query(payment: PendingPayment, question: str) -> AnswerEnvelope` — consumed by Task 5 (Streamlit UI).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_settlement_qa.py` (add `answer_pending_query` to the existing `from src.agent.settlement_qa import (...)` block, and add `from src.domain.models import PendingPayment` — note `AnswerEnvelope` may already be imported elsewhere in that file; if not, `from src.domain.models import PendingPayment` is sufficient for these tests):

```python
from datetime import datetime


def _pending(**overrides):
    defaults = dict(
        entity_id="pay_pending_000",
        order_id="ord_pending_0",
        amount=49900,
        captured_at=datetime(2026, 8, 20, 10, 0, 0),
        cycle_type="standard",
        instant_eligible="unknown",
        expected_settlement_at=date(2026, 8, 22),
    )
    defaults.update(overrides)
    return PendingPayment(**defaults)


def test_pending_query_where_is_my_money_gives_expected_date():
    payment = _pending()
    ans = answer_pending_query(payment, "where is my money")
    assert not ans.abstained
    assert "not yet been settled" in ans.answer_text or "not settled" in ans.answer_text
    assert "22" in ans.answer_text or "Aug" in ans.answer_text
    assert ans.citations == ["pay_pending_000"]


def test_pending_query_instant_eligible_yes():
    payment = _pending(instant_eligible="yes", cycle_type="instant_eligible")
    ans = answer_pending_query(payment, "can I get this instantly?")
    assert not ans.abstained
    assert "eligible" in ans.answer_text.lower()


def test_pending_query_instant_eligible_no_falls_back_to_standard_date():
    payment = _pending(instant_eligible="no")
    ans = answer_pending_query(payment, "I need this same day")
    assert not ans.abstained
    assert "not eligible" in ans.answer_text.lower() or "isn't eligible" in ans.answer_text.lower()
    assert "22" in ans.answer_text or "Aug" in ans.answer_text


def test_pending_query_instant_eligible_unknown_abstains_honestly():
    payment = _pending(instant_eligible="unknown")
    ans = answer_pending_query(payment, "is this eligible for instant settlement now?")
    assert ans.abstained
    assert "can't confirm" in ans.answer_text.lower()


def test_pending_query_never_crashes_without_expected_date():
    payment = _pending(expected_settlement_at=None)
    ans = answer_pending_query(payment, "when will I get paid")
    assert isinstance(ans.answer_text, str)
    assert ans.answer_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settlement_qa.py -k pending_query -v`
Expected: FAIL with `ImportError: cannot import name 'answer_pending_query'`

- [ ] **Step 3: Write the function**

In `src/agent/settlement_qa.py`, add `PendingPayment` to the existing `from src.domain.models import (...)` block at the top of the file. Then add this function after `route_free_text` (after its closing `return "where_is_settlement"`, before the `_FINISH_ANSWER_TOOL` dict):

```python
_INSTANT_RE = re.compile(r"\b(instant|same[\s-]?day|fast\s*cash|now)\b", re.I)


def answer_pending_query(payment: PendingPayment, question: str) -> AnswerEnvelope:
    """Answer a merchant question about a payment captured but not yet settled.

    Deliberately not routed through route_free_text(): none of that function's
    escalation, compensation, or triage machinery applies to a payment with no
    settlement yet — there is no batch, no UTR, and no triage verdict to compute.
    """
    q = sanitize_question(question).lower()
    captured_str = payment.captured_at.strftime("%d %b %Y")
    expected_str = payment.expected_settlement_at.strftime("%d %b %Y") if payment.expected_settlement_at else None

    if _INSTANT_RE.search(q):
        if payment.instant_eligible == "yes":
            text = (
                f"Your payment {payment.entity_id} (captured {captured_str}) is eligible for instant "
                "settlement — it's typically credited within minutes of a manual pull, subject to your "
                "available instant-settlement balance."
            )
        elif payment.instant_eligible == "no":
            if expected_str:
                text = (
                    f"Your payment {payment.entity_id} (captured {captured_str}) is not eligible for instant "
                    f"settlement. It's on the standard settlement cycle and is expected by {expected_str} "
                    "(calendar days, not bank business days)."
                )
            else:
                text = (
                    f"Your payment {payment.entity_id} is not eligible for instant settlement, and we don't "
                    "have enough data to give an expected standard settlement date."
                )
            return AnswerEnvelope(
                answer_text=text, citations=[payment.entity_id], tool_trace=["pending_payment"], agent_mode="keyword",
            )
        else:
            return AnswerEnvelope(
                answer_text=(
                    "We can't confirm instant-settlement eligibility for this payment from your Razorpay "
                    "data — check the Instant Settlements section of your dashboard."
                ),
                abstained=True,
                citations=[payment.entity_id],
                tool_trace=["pending_payment"],
                agent_mode="keyword",
            )
        return AnswerEnvelope(
            answer_text=text, citations=[payment.entity_id], tool_trace=["pending_payment"], agent_mode="keyword",
        )

    if expected_str:
        text = (
            f"Your payment {payment.entity_id} (captured {captured_str}) has not yet been settled. "
            f"Based on the standard settlement cycle, it's expected by {expected_str} "
            "(calendar days, not bank business days)."
        )
    else:
        text = (
            f"Your payment {payment.entity_id} (captured {captured_str}) has not yet been settled, and we "
            "don't have enough data from your Razorpay settlement and recon records to give an expected date."
        )
    return AnswerEnvelope(
        answer_text=text, citations=[payment.entity_id], tool_trace=["pending_payment"], agent_mode="keyword",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settlement_qa.py -k pending_query -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Run the full settlement_qa test suite to confirm no regressions**

Run: `python -m pytest tests/test_settlement_qa.py tests/test_settlement_qa_llm.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent/settlement_qa.py tests/test_settlement_qa.py
git commit -m "feat: answer where-is-my-money and instant-settlement questions for pending payments"
```

---

### Task 5: Streamlit UI — pending payments selector

**Files:**
- Modify: `apps/streamlit_app.py`

**Interfaces:**
- Consumes: `load_pending_payments()` from Task 3, `answer_pending_query()` from Task 4, `PendingPayment` from Task 1.
- Produces: nothing consumed by later tasks — this is the last task.

This UI is intentionally simpler than `render_settlement_chatbot` (no ticket/compensation CTAs, no chat history, no presets) because none of that machinery applies to a payment with no settlement — there is no `decision`, no `batches`, and nothing to escalate or compensate.

- [ ] **Step 1: Add the import**

In `apps/streamlit_app.py`, change:

```python
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
    submit_compensation_claim,
    validate_question_input,
)
```

to add `answer_pending_query,` (alphabetically after `answer_free_text,`):

```python
from src.agent.settlement_qa import (
    MAX_QUESTIONS_PER_SESSION,
    PRESET_INTENTS,
    answer_free_text,
    answer_pending_query,
    answer_preset,
    filter_response_text,
    last_llm_error,
    needs_support_ticket,
    question_hash,
    raise_support_ticket,
    sanitize_question,
    submit_compensation_claim,
    validate_question_input,
)
```

And change:

```python
from src.connectors.loaders import ...
```

Check whether `src.connectors.loaders` is already imported in this file (`grep -n "from src.connectors.loaders" apps/streamlit_app.py`). It is not (the app builds `batches` via `engine.batch_map()`), so add a new import line after the `from src.engine import ReconciliationEngine` line:

```python
from src.connectors.loaders import load_pending_payments
```

- [ ] **Step 2: Add a render function for a single pending payment**

Add this function after `format_date` (after its closing `return dt.strftime(...)` line, before `def run_check`):

```python
def render_pending_payment_panel(payment) -> None:
    """Minimal single-turn Q&A for a payment with no settlement yet.

    No ticket/compensation CTAs here: those concepts don't apply until a
    settlement exists to escalate or compensate against.
    """
    st.markdown('<p class="section-label">Pending payment detail</p>', unsafe_allow_html=True)
    st.subheader(f"{format_inr(payment.amount)} · captured {format_date(payment.captured_at)}")
    st.markdown(
        '<p class="status-pill attention">⏳ Not yet settled</p>',
        unsafe_allow_html=True,
    )
    if payment.expected_settlement_at:
        st.caption(f"Expected settlement: {payment.expected_settlement_at.strftime('%d %b %Y')} (calendar days)")

    question = st.chat_input(
        "Ask about this payment (e.g. \"where is my money\" or \"can I get this instantly\")…",
        key=f"pending_chat_input_{payment.entity_id}",
    )
    history_key = f"pending_chat_{payment.entity_id}"
    if history_key not in st.session_state:
        st.session_state[history_key] = []

    if question:
        ans = answer_pending_query(payment, question)
        st.session_state[history_key].append((question, filter_response_text(ans.answer_text)))

    for q, a in st.session_state[history_key]:
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
            st.markdown(a)
```

- [ ] **Step 3: Wire the selector into the main layout**

Find the block that renders the settlement dropdown (`with st.container(border=True):` containing `st.markdown('<p class="section-label">Browse settlements</p>' ...)`, roughly `apps/streamlit_app.py:1066-1102`). Immediately after that whole `with st.container(border=True):` block ends (i.e., after the line `st.session_state["selected_settlement"] = selected_id`, back at the outer indentation level), add:

```python
pending_payments = load_pending_payments(DEMO_DIR / "recon.json", DEMO_DIR / "manifest.json")
selected_pending_id = None
if pending_payments:
    with st.container(border=True):
        st.markdown('<p class="section-label">Pending payments (not yet settled)</p>', unsafe_allow_html=True)
        pending_options = {
            f"{format_inr(p.amount)} · {p.order_id or p.entity_id} · captured {format_date(p.captured_at)}": p.entity_id
            for p in pending_payments
        }
        pending_labels = ["— none selected —"] + list(pending_options.keys())
        picked_pending = st.selectbox("Pending payments", pending_labels, label_visibility="collapsed")
        if picked_pending != "— none selected —":
            selected_pending_id = pending_options[picked_pending]
            selected_id = None
            st.session_state["selected_settlement"] = None

if selected_pending_id:
    payment = next(p for p in pending_payments if p.entity_id == selected_pending_id)
    with st.container(border=True):
        render_pending_payment_panel(payment)
```

This makes the two selectors mutually exclusive: picking a pending payment clears `selected_settlement` (so `if selected_id:` below skips the settlement-detail block on this render), matching the existing single-context UX pattern described in the spec.

- [ ] **Step 4: Manual verification (this UI has no automated test in this plan)**

Run: `streamlit run apps/streamlit_app.py`

In the browser:
1. Confirm the existing "Browse settlements" dropdown and settlement chat still work exactly as before (regression check).
2. Confirm a new "Pending payments (not yet settled)" section appears below it, listing 3 entries.
3. Select the `instant_eligible="no"` entry (₹499, `ord_pending_0`) and ask "where is my money" — confirm the answer states it's not settled and gives an expected date ~2 days after the captured date.
4. Ask "can I get this instantly" on the same entry — confirm it says not eligible and repeats the standard expected date.
5. Select the `instant_eligible="yes"` entry (₹12,500, `ord_pending_1`) and ask "same day please" — confirm it says eligible.
6. Select the `instant_eligible="unknown"` entry (₹899, `ord_pending_2`) and ask "instant settlement now?" — confirm it honestly abstains ("can't confirm").
7. Confirm selecting a pending payment clears the settlement dropdown's detail panel, and vice versa.

- [ ] **Step 5: Commit**

```bash
git add apps/streamlit_app.py
git commit -m "feat: add pending-payments selector and chat panel to the Streamlit app"
```

---

## Self-Review Notes

- **Spec coverage:** All six spec components (§1 `PendingPayment` model, §2 recon rows, §3 cycle policy, §4 loader, §5 answer function, §6 UI selector) map to Tasks 1-5. The spec's three required generator cases (standard past-due, instant-eligible, unknown-eligibility) are covered by Task 2's three `add_pending_payment` calls and exercised end-to-end in Task 5 Step 4's manual verification.
- **Out-of-scope items respected:** no nullable `SettlementLine.settlement_id` change, no business-day math (`timedelta(days=...)` only), no free-text pending search (selector-only entry point), pending payments never touch `route_free_text()` or `triage.classify()`.
- **Type consistency:** `PendingPayment` (Task 1) fields — `entity_id`, `order_id`, `amount`, `currency`, `method`, `captured_at`, `cycle_type`, `instant_eligible`, `expected_settlement_at` — are used identically in Task 3's loader construction, Task 4's `answer_pending_query` signature and test fixtures, and Task 5's UI rendering. `load_pending_payments(recon_path: Path, manifest_path: Path) -> list[PendingPayment]` signature matches its Task 3 definition and Task 5 call site.
