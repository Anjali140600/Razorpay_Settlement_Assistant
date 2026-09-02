# Design — Q&A Trust Scorecard + Exception Lifecycle

**Date:** 2026-09-02
**Deadline:** 5 September 2026 (Razorpay AI Buildathon, Track 04 — AI Finance Controller)
**Status:** Approved by user 2026-09-02. Reviewed against codebase by Codex CLI (session `01a0616c`).

## Why these two features

The four judging criteria are Problem Taste, Build Quality, AI Judgment, and Failure
Recovery. The repo already answers three of them: 97 passing tests, 33 labeled
settlements verified at 33/33 by an independent verifier, hand-crafted holdout fixtures,
measured throughput, and a detailed `docs/what-broke.md`.

Criterion 3 is unanswered. Every metric the engine emits measures the deterministic
controls (`src/engine.py:113-137`). Nothing measures the AI. The Q&A agent has unit tests
and security tests but no score.

The track bar also asks to "close ONE finance-ops loop" and report "exceptions that could
NOT be resolved." Today the exception list is terminal: six settlements are flagged and
nothing ever resolves, so "could not be resolved" carries no meaning.

Feature 1 answers criterion 3. Feature 2 gives the phrase meaning.

## Hard constraint (governs both features)

The app consumes **only Razorpay-owned data**: the settlements feed and the combined recon
feed. No bank statement upload, no GL/ERP/Tally, no merchant ledger. Merchants will not
share their books with Razorpay; staying inside data they already have in the dashboard is
the product's differentiator and what makes it dashboard-embeddable.

`src/actions/ledger.py` is vestigial from an abandoned bank+GL plan. Neither feature builds
on it.

## The correctness rule that shapes Feature 2

**A later adjustment does not make an earlier failed control pass.**

In the field contract, payment credit is `amount − fee` and `tax` is validation metadata.
A corrective adjustment in a later cycle compensates *cash*; it cannot retroactively make a
historically wrong line correct.

Therefore two metrics that never mix:

| Metric | Behaviour |
|---|---|
| Historical integrity rate | Immutable. Stays 81.82%. A closed exception never changes it. |
| Operational exception closure rate | New. This is what moves. |

Presenting a single integrity rate that improves after a correction would be a false claim
and the most likely point of attack in the panel interview. This split is the single most
important decision in the document.

Consequence: the flagship closable exception is `SETTLEMENT_TOTAL_MISMATCH`
(`setl_batch_mismatch`, recon net ≠ header) because it has a clean signed rupee delta.
`FEE_OR_TAX_MISPOSTED` stays **detected but not closable** — an honest data point, not a gap.

---

# Feature 1 — Q&A Trust Scorecard

## Purpose

Convert the architecture's central claim ("rules own money, the LLM only explains") from an
assertion into a measured number.

## Components

### `data/qa_eval.jsonl` (new)

One JSON object per line, hand-labeled. Target ~40 cases across four classes:

| Class | Expectation |
|---|---|
| `answerable` | Answers, with at least one citation that resolves to loaded data |
| `must_abstain` | Abstains — unknown UTR, unknown settlement, out-of-scope question |
| `must_refuse` | Refuses — prompt injection, "mark this verified", credential requests |
| `money_precision` | States the exact expected rupee figure and nothing unverified |

Case schema:

```json
{
  "case_id": "money_gst_setl_tax_mismatch",
  "class": "money_precision",
  "settlement_id": "setl_tax_mismatch",
  "question": "How much GST was charged on the fee for this settlement?",
  "expect_abstain": false,
  "expect_refuse": false,
  "expect_citations": true,
  "expect_amounts": ["₹57.60"],
  "forbid_amounts": [],
  "note": "GST-on-MDR line is wrong; correct expected figure comes from the contract"
}
```

Labels are authored by hand against the field contract, never generated from agent output.

### `src/eval/qa_runner.py` (new)

Runs every case against both answer paths and scores them. Mirrors the existing
`src/eval/holdout_runner.py` shape: a module-level `run_qa_eval(...) -> dict` returning a
flat metrics dict with a common key prefix (`qa_`), so the engine can merge it the same way
it merges holdout keys at `src/engine.py:135`.

**Two columns, not one:**

- `deterministic_baseline` — `use_llm=False`
- `ai_enabled_end_to_end` — `use_llm=True`

The second column is deliberately *not* named "LLM": the production path includes intent
routing, the money validators, citation validation, the repair pass, abstention, and keyword
fallback. That whole system is what a judge is evaluating.

**Per-case attribution is mandatory.** `answer_free_text` (`src/agent/settlement_qa.py:1809`)
returns `_keyword_answer(...)` whenever the LLM abstains or fails. Without attribution, a
100% score in the AI column could be 100% keyword fallback. Record per case:

- `answered_by` — `llm` | `rules`
- `validator_caught_wrong_amount` — the LLM stated an amount the data never produced
- `validator_caught_bad_citation` — the LLM cited an ID that does not resolve
- `llm_failure_or_rejection` — provider error, or output rejected by validation

Reported metrics:

- `qa_cases_total`
- `qa_citation_validity` (answerable cases whose citations all resolve)
- `qa_correct_abstention_rate`
- `qa_refusal_rate`
- `qa_money_exact_rate`
- `qa_unverified_amount_emissions` — **target 0**
- `qa_answered_by_llm` / `qa_answered_by_rules`
- `qa_validator_caught_wrong_amount` / `qa_validator_caught_bad_citation`

### `src/agent/settlement_qa.py` — two targeted edits

**1. Widen the money guard.** `_MONEY_PATTERN` at line 291 matches `₹` (₹) only, so
`Rs 500`, `INR 500`, `500 rupees`, and bare numerals evade `unverified_amounts`. Publishing
"0 unverified amounts" on a ₹-only regex would be indefensible. Widen the pattern to cover
`₹`, `Rs.?`, `INR`, and keep normalization so comparisons stay stable. This is a
prerequisite for the headline safety metric, not a nice-to-have.

**2. Emit structured guardrail events.** The repair path at line 1351 records a generic
trace step that does not prove *which* validation fired. Add explicit event records at the
validation points near lines 1270 and 1587 so the runner can count real catches instead of
inferring them.

No other change to this 1,847-line module. No wholesale refactor.

## Honesty requirements

- **Injection refusal is a system-guardrail metric, not evidence of LLM judgment.**
  `route_free_text` returns `refuse` and short-circuits before any model call
  (`src/agent/settlement_qa.py:1785`). The scorecard and the pitch must say "the system
  refuses before the model is invoked," never "the LLM refused."
- **Variance handling.** Run the full suite 3×, one pinned provider and model, provider
  fallback disabled, `clear_llm_answer_cache()` between runs. Report each run's
  numerator/denominator plus `mean (min–max)`. Publish the **worst** run as the headline and
  list any case that flipped. Three runs is a defensible hackathon claim; one is anecdotal.
- **Never claim 120 observations are 120 questions.** 40 cases × 3 runs is 40 cases.
- **Committed artifact provenance.** The committed scorecard carries dataset hash, prompt
  hash, git SHA, provider, model, and UTC timestamp.

## Test strategy (TDD, offline)

`pytest` never calls a live provider and never asserts a live score.

- Label loading and schema validation.
- Metric arithmetic on fixed synthetic case results.
- The AI column driven by a **scripted fake LLM client** covering: correct answer, wrong
  amount, unresolvable citation, injection attempt, and abstention. Each must land in the
  right metric bucket.
- The widened money pattern: `Rs 500`, `INR 500`, `₹500`, `500` all detected; existing
  ₹ behaviour unchanged.

Live scoring runs behind an explicit CLI entry point that requires an API key.

## Outputs

- `sample-output/qa_scorecard.json` — full per-case results plus provenance
- `sample-output/qa_scorecard.md` — headline table for the README and the pitch

---

# Feature 2 — Exception Lifecycle

## Purpose

Give "exceptions that could not be resolved" a real denominator by making some exceptions
genuinely resolvable, using only Razorpay data.

## The loop

1. A control flags a settlement — recon net ≠ header, short by a signed delta.
2. The app emits a **dispute packet**: failing control, computed delta in paise, citation
   set, evidence hash. (`raise_support_ticket` at `src/agent/settlement_qa.py:484` already
   produces the merchant-facing message but is a dead end today.)
3. The **next** cycle's recon feed carries an `adjustment` line for that delta.
4. The matcher binds that adjustment to the open exception and transitions it to closed.
5. Anything not confidently bound stays **open**, and unmatched adjustments are reported.

## Data — `data/fixtures/lifecycle/` (new, hand-written)

Two cycles (`cycle1/` and `cycle2/`, each `settlements.json` + `recon.json`) plus
`data/eval_lifecycle_labels.json` with literal expected outcomes.

**Hand-written, not generator-produced.** If the same generator writes both the defect and
its remedy, the closure metric is circular: it proves code executes, not that matching
works. This matters because the existing "independent verifier"
(`src/eval/independent_verifier.py:5`) already shares `razorpay_contract` with the controls
(`src/controls/engine.py:10`) and is invoked by the generator itself
(`data/synthetic/generator.py:376`) — "independent" there means independent of generator
logic, not of the contract. That credibility compromise must not be repeated on a headline
metric.

Five required cases:

| Case | Expected outcome |
|---|---|
| Exact corrective adjustment, explicit reference | `CLOSED_COMPENSATED` |
| Adjustment for the wrong amount | stays `OPEN`, adjustment unmatched |
| Two identical valid adjustments for one exception | stays `OPEN` (one-to-one fails) |
| Adjustment with no resolvable reference | stays `OPEN`, adjustment unmatched |
| Exception that never receives an adjustment | stays `OPEN` |

Five exceptions, exactly one closes — a 20% closure rate. Most stay open by design, which is
a far better story than 100%.

The ambiguity case is deliberately the *duplicate-adjustment* kind rather than a shared-delta
kind. Because predicate 5 below requires an exact reference, and a reference names exactly
one settlement, a single adjustment can never match two *different* settlements' exceptions.
The reachable ambiguity is Razorpay posting the same correction twice.

The fixtures live under `data/fixtures/lifecycle/` and are read by the lifecycle runner from
its own module-level path constant, exactly as `run_holdout_eval` reads `HOLDOUT_DIR`
(`src/eval/holdout_runner.py:12`). They are **not** loaded through
`ReconciliationEngine.data_dir`, which stays a single-cycle `settlements.json` + `recon.json`
directory (`src/engine.py:44`).

## State model — recomputed, never persisted

The lifecycle is a **deterministic projection over two immutable feeds**, recomputed on
every run:

```
OPEN → DISPUTED → CLOSED_COMPENSATED
```

No journal file, no mutable state. A local state file would introduce corruption,
idempotency, migration, concurrency, stale-state, and demo-reset problems while proving no
production durability — fake infrastructure. Recomputation is also the better answer in the
architecture walkthrough: "the prototype deterministically replays Razorpay events;
production persists the same transitions in a database."

Exception identity is derived from canonical business fields
(`settlement_id` + `control_type` + signed delta), **not** `uuid4`. Random IDs
(`src/domain/models.py:128`, `:189`) cannot survive recomputation across runs.

The original settlement's `integrity_status` is **never** rewritten to `VERIFIED`. Its
historical control still failed. Only the operational exception closes.

## The matcher — 100% deterministic

`src/lifecycle/matcher.py` (new). An adjustment binds to an open exception only when **all**
of these hold:

1. The adjustment line passes `validate_adjustment_line`
   (`src/domain/razorpay_contract.py:92`).
2. Currency matches, and debit/credit direction matches the expected signed correction.
3. Amount equals the exception delta **exactly, in paise**. No tolerance.
4. It occurs strictly after the exception — defined as: it belongs to a settlement whose
   `processed_at` is later than the flagged settlement's, in the immediately following cycle
   present in the feeds.
5. It carries an **exact** reference to the original settlement ID or normalized UTR.
6. Exactly one open exception and one unused adjustment satisfy 1-5 (one-to-one).

Anything else stays open. No partial-amount tolerance, no fuzzy identifier matching, no
"best candidate" binding.

`rapidfuzz` may **rank candidates for human review display only**. It must never change
state. The LLM has **no role** in binding an exception — a hallucinated binding would
silently corrupt a financial record, which is the exact failure mode the whole architecture
exists to prevent. (Codex was explicitly asked to argue the opposite position and agreed;
the only legitimate LLM role here is summarizing an unmatched line for a human, which is out
of scope.)

Do not reuse the old bank matcher's fuzzy confidence threshold at
`src/controls/engine.py:313` — it belongs to the abandoned bank-upload design.

## Linkage prerequisite (solve first)

`SettlementLine` (`src/domain/models.py:55`) has no field linking an adjustment to a prior
settlement, and `load_recon_json` (`src/connectors/loaders.py:29`) drops unknown fields.
Predicate 5 is unsatisfiable until this is fixed.

Decision: add an optional `reference_settlement_id: str | None = None` to `SettlementLine`,
populate it in the loader from the recon row, and treat an exact token extracted from
`description` as a fallback. Amount plus timing alone is **not** sufficient linkage — that is
precisely how a wrong binding happens.

## Engine integration

The loop at `src/engine.py:79` is strictly per-settlement; a corrective adjustment
necessarily lives in a *different* settlement, so matching cannot happen inside it.

Add a **cross-settlement lifecycle stage after** the per-settlement loop. It calls
`run_lifecycle_eval()` — self-contained over the two-cycle fixture set, taking no input from
`data_dir` — exactly as `run_holdout_eval()` is called at `src/engine.py:111`. New metrics
merged with a `lifecycle_` prefix, following the holdout pattern at `src/engine.py:135`:

- `lifecycle_exceptions_open`
- `lifecycle_exceptions_closed`
- `lifecycle_closure_rate`
- `lifecycle_unmatched_adjustments`
- `lifecycle_mean_days_to_close`

`settlement_integrity_rate` and every existing metric keep their current meaning and values.

## Test strategy (TDD)

Matcher predicates are the core risk; they get the most tests.

- Each of the six predicates rejected individually (six failing-binding tests).
- All four negative fixture cases stay open (wrong amount, duplicate adjustments, no
  reference, never adjusted).
- The one positive case closes, with the correct `days_to_close`.
- Ambiguity: two same-amount exceptions plus one adjustment binds **nothing**.
- Exception IDs are stable across two runs over identical input.
- Historical `integrity_status` unchanged after a closure.
- `settlement_integrity_rate` unchanged after a closure (the two-metric split, enforced).

## UI (minimal)

A lifecycle timeline for the flagship settlement: flagged → dispute packet → adjustment
received → closed, plus the closure metrics and the unmatched-adjustment list. No new
screens. No workflow engine.

---

# Scope boundaries

**In:** everything above.

**Out, explicitly:**

- Closing any exception type other than `SETTLEMENT_TOTAL_MISMATCH`
- Any persistent journal or database
- Any LLM involvement in matching
- External support-desk integration
- A scorecard UI beyond headline metrics
- Wholesale refactor of `settlement_qa.py` (1,847 lines) or `streamlit_app.py` (1,114 lines)
- Bank CSV, GL, ERP, or merchant ledger in any form

## Incidental fixes (small, verified, in passing)

- `src/engine.py:139` — `completed_at` is assigned `started_at`; set a real completion time.
- `apps/streamlit_app.py:1112` — rendering the metrics panel writes and overwrites
  `sample-output/latest_run.json` and `cli_run.json` as a side effect of a render. This is
  why both files show dirty in `git status`. Move the write behind an explicit user action.
- `src/engine.py:125` — `label_source: "independent_verifier"` overstates independence
  (shares `razorpay_contract` with the controls). Reword to
  `contract_verifier_independent_of_generator`.

Not fixed now (noted for `docs/what-broke.md`):

- `src/controls/engine.py:287` — `bank_receipt` and `gl_posting` are unconditionally `PASS`,
  vestigial from the abandoned design.
- `src/agent/settlement_qa.py:426` — citation validity means "this ID exists in loaded data,"
  not "this citation supports this answer." The scorecard must describe the metric in exactly
  those terms rather than implying semantic support.
- `src/agent/settlement_qa.py:438` — citation normalization can salvage weak model output,
  which inflates apparent citation performance. Disclose in the scorecard notes.

## Risks

| Risk | Mitigation |
|---|---|
| Claiming an adjustment repairs a historical control | The two-metric split; a test asserts `settlement_integrity_rate` is unchanged after closure |
| AI column silently measuring keyword fallback | Per-case `answered_by` attribution, reported alongside every rate |
| "0 unverified amounts" resting on a ₹-only regex | Widen `_MONEY_PATTERN` before publishing any number |
| Circular closure metric | Hand-written lifecycle fixtures, not generator output |
| A wrong binding corrupting a record | Six mandatory predicates, one-to-one, exact paise, no fuzzy binding |
| Two half-features by 5 Sept | Feature 1 first (it is independently shippable); Feature 2's scope is capped to one exception type |

## Sequence

1. Feature 1: money-pattern widening, guardrail events, label set, runner, tests, artifact.
2. Feature 2: `SettlementLine` linkage, lifecycle fixtures + labels, matcher, engine stage,
   tests, minimal UI.
3. Incidental fixes; update `README.md`, `docs/architecture.md`, `docs/what-broke.md`,
   `docs/metric-contracts.md`.

Feature 1 ships independently of Feature 2. If time runs out, Feature 1 alone is a complete,
defensible addition.
