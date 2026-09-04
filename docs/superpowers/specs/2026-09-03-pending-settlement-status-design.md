# Design — Pending Settlement Status in the Chatbot

**Date:** 2026-09-03
**Status:** Approved by user 2026-09-03. Reviewed against codebase by Codex CLI (session `01a06737`).

## The gap this closes

The settlement chatbot (`src/agent/settlement_qa.py`, `apps/streamlit_app.py`) answers two
kinds of merchant questions well once a settlement is selected: "where is this settlement"
and "why is net less." Two related questions are not actually answered today:

- "where is my money" / "when will I get paid" / "date"
- "instant" / "same day" / "fast cash" / "now"

Both assume a settlement already exists for the payment in question. Neither handles the
case where a payment was **captured but has not been settled yet** — the case a merchant is
usually in when they ask "where is my money."

Two facts, found by inspection and confirmed with Codex, changed the shape of this design
from the first pass:

1. **"where is my money" already matches something today** — `BANK_NON_RECEIPT_RE`
   (`src/agent/settlement_qa.py:191`) contains the literal phrase and routes it to
   `bank_non_receipt`, which — once a settlement is selected — always escalates ("we can't
   confirm or rule out what you're describing from settlements+recon, raise a ticket").
   That's the wrong answer whenever the real situation is simply "not settled yet, expected
   by X." Auto-escalating a resolvable question is worse than abstaining.
2. **A pending payment cannot exist anywhere in the current pipeline.** `SettlementLine.settlement_id`
   is a non-nullable `str` (`src/domain/models.py:456`), and
   `attach_lines_to_batches` (`src/connectors/loaders.py:76-83`) silently drops any recon row
   whose `settlement_id` doesn't match a known settlement — no error, no visibility. The
   Streamlit UI's only entry point is a settlement dropdown (`apps/streamlit_app.py:1100`);
   there is no order/payment/amount search that doesn't require an existing settlement.
   `SettlementEvidenceTools` (`src/agent/evidence.py`) only ever iterates
   `dict[str, SettlementBatch]`, so it can't see an orphaned line either.

Given fact 2, deriving "pending" purely from today's `recon.json` (the original idea) is
dead on arrival: every recon row already has `settled: true`, a `settlement_id`, and a
`settled_at` (`data/synthetic/generator.py:705-714`, `_line_base`). There is currently zero
unsettled data to derive anything from.

## Hard constraint (unchanged from the project's existing data boundary)

The app consumes only Razorpay-owned data: settlements + recon. No bank statement, no
merchant ledger, no live payment/ERP API. This design adds a new *state* (captured, not yet
settled) inside that same boundary — it does not add a new data source.

## Design: additive, not a migration

Rather than making `SettlementLine.settlement_id` nullable and threading pending payments
through the existing settlement-scoped pipeline (`attach_lines_to_batches`,
`SettlementEvidenceTools`, `triage.classify()`), this design keeps those paths untouched and
adds a parallel path. `triage.classify()` in particular assumes an already-formed
`SettlementBatch` + `SettlementCloseDecision`; forcing a pending payment through it would
mean manufacturing fake settlement facts. Reasons to keep this additive:

- Zero risk to the tested settled-settlement pipeline (97 passing tests, independent
  verifier, holdout fixtures — none of that touches this code).
- A pending payment has no batch, no UTR, no fee/tax lines, no triage verdict — it is a
  different shape of fact, not a `SettlementBatch` with fields missing.
- Smaller, independently testable units: a new loader, a new tiny model, one new answer
  function, one new UI selector.

### 1. New model — `PendingPayment` (`src/domain/models.py`)

```python
class PendingPayment(BaseModel):
    entity_id: str                      # e.g. "pay_pending_014"
    order_id: str | None = None
    amount: int                         # paise
    currency: str = "INR"
    method: str | None = None
    captured_at: datetime
    cycle_type: str = "standard"        # "standard" | "instant_eligible"
    instant_eligible: str = "unknown"   # "yes" | "no" | "unknown" — never inferred
    expected_settlement_at: date | None = None   # computed at load time, see below
```

`instant_eligible` is a tri-state string, not a bool, because the real-world signal
(merchant instant-settlement enablement, risk hold, balance/limit) is not something
settlements+recon can see. The generator sets it explicitly per row; the loader never
guesses it from other fields.

### 2. Recon data — new unsettled rows (`data/synthetic/generator.py`)

Add a `pending` profile alongside the existing settlement profiles: rows with
`"settled": False`, `"settlement_id": None`, `"settlement_utr": None`, `"settled_at": None`,
plus `"captured_at"`, `"cycle_type"`, and `"instant_eligible"`. These rows are appended to
`recon_lines` (same file, `recon.json`) but never passed through `finalize_settlement()`, so
they never get a settlement header in `settlements.json` — that absence *is* "not yet
settled."

Cover at least: one standard-cycle pending payment past its expected date (to exercise
"where is my money" genuinely resolving), one instant-eligible pending payment, and one
`instant_eligible: unknown` case (to exercise the honest-abstention path).

### 3. Settlement-cycle policy — new (`data/synthetic/demo/manifest.json` + a small constant)

No cycle policy exists today. Add a `settlement_cycle` block to `manifest.json`
(`{"standard_days": 2, "instant_available": true}`) and a matching constant read by the
loader to compute `expected_settlement_at = captured_at + standard_days` (business-day
math out of scope for this pass — flag the number as calendar days, not bank business days,
in the answer text itself so it's never silently wrong).

### 4. New loader — `load_pending_payments()` (`src/connectors/loaders.py`)

Reads `recon.json`, selects rows with `settlement_id in (None, "")`, and returns
`list[PendingPayment]` with `expected_settlement_at` computed from the manifest's cycle
policy. Does not touch `load_recon_json`, `load_settlements_json`, or
`attach_lines_to_batches` — those keep loading only settled lines exactly as today.

### 5. New answer function — `answer_pending_query()` (`src/agent/settlement_qa.py`)

```python
def answer_pending_query(payment: PendingPayment, question: str) -> AnswerEnvelope:
```

Its own tiny keyword classifier — deliberately not routed through `route_free_text()`,
because none of that function's escalation/compensation/triage machinery applies to a
payment with no settlement yet:

- Matches `"instant"|"same day"|"fast cash"|"now"` → answer from `instant_eligible`:
  - `"yes"` → "Eligible for instant settlement; typically credited within minutes of a manual pull, subject to your available instant-settlement balance."
  - `"no"` → explain why (cycle type) and give the standard expected date instead.
  - `"unknown"` → **abstain honestly**: "We can't confirm instant-settlement eligibility for this payment from your Razorpay data — check the Instant Settlements section of your dashboard."
- Everything else (including "where is my money", "when will I get paid", "date") → state
  `captured_at`, `expected_settlement_at`, and the cycle type in plain language. Never say
  "not settled yet" without also giving the expected date — that combination is the entire
  point of this feature.
- `AnswerEnvelope.agent_mode = "keyword"`, `citations = [payment.entity_id]`, `abstained`
  only set in the `unknown` eligibility branch above.

This function never calls `classify_triage`, never offers a compensation claim or a support
ticket — none of those concepts apply to a payment that hasn't reached a settlement yet.

### 6. UI — second selector (`apps/streamlit_app.py`)

Alongside the existing settlement dropdown (`apps/streamlit_app.py:1100`), add a second
`st.selectbox("Pending payments (not yet settled)", ...)` sourced from
`load_pending_payments()`, labeled like `"ord_881 · ₹499 · captured 3 days ago"`. Selecting
a pending payment routes chat questions to `answer_pending_query()` instead of
`resolve_answer()`. The two selectors are mutually exclusive in the session state — picking
one clears the other, matching the existing single-settlement-context UX pattern.

## Explicitly out of scope for this pass

- **Free-text search across pending payments** (by amount/order id) when nothing is
  selected. Today's existing fallback message ("select a settlement first") is left as-is
  for that case. This is a natural follow-up once the pending-payment path above is proven,
  not required to close the core gap the user asked about.
- **Business-day-aware cycle math** (holidays, cutoff times, timezones) — calendar-day T+2
  only, stated as such in the answer text.
- **Making `SettlementLine.settlement_id` nullable** or otherwise unifying pending and
  settled payments into one model/table.

## Testing

- `tests/test_settlement_qa.py` — new cases for `answer_pending_query()`: standard pending
  past due, instant-eligible, unknown-eligibility abstention, and the "no cycle info"
  abstention edge case (missing `captured_at` — should never crash).
- New `data/synthetic/generator.py` rows get their own manifest counts (`pending_lines`) so
  a future generator regression is caught the same way `verified_settlements` is today.
- No changes required to `tests/test_reconciliation.py`, `tests/test_lifecycle_runner.py`, or
  `tests/test_triage.py` — this design does not touch that pipeline.
