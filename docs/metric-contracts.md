# Metric Contracts

## Settlement Integrity Rate (headline)

```
VERIFIED settlements / processed settlements in run
```

A settlement is VERIFIED when **batch integrity** and **tax-line integrity** both PASS.

(UI may label VERIFIED as "Verified"; internal enum may remain `PROVEN`.)

## Tax-line Pass Rate

```
tax-line control PASS / processed settlements
```

## Auto-Close Precision

```
correctly green-closed control decisions / all green-closed control decisions
```

Target: 100% (false auto-closes = 0).

## Q&A Evidence Rate

```
Q&A answers with ≥1 tool citation / total Q&A attempts
```

Report separately from integrity rate. Abstentions count as non-evidenced answers.

## Throughput

```
total recon payment lines / runtime_seconds
```

Reported separately from accuracy metrics.

## Exception Export

Every investigation case and non-VERIFIED settlement control failure is exported. No curated subset.

## Legacy metrics (Phase 2 / optional bank mode)

When `include_bank=True`:

- **Settlement-bank match rate** — eligible processed settlements with exact UTR + amount match
- **Full-chain proven rate** — batch + bank + GL all PASS (deprecated for core narrative)

---

# Q&A Trust Scorecard metrics

Emitted by `src/eval/qa_runner.py`, published to `sample-output/qa_scorecard.{json,md}`.
Cases are hand-labeled in `data/qa_eval.jsonl` against the field contract — never
generated from agent output.

Two columns are always reported: `deterministic_baseline` (`use_llm=False`) and
`ai_enabled_end_to_end` (`use_llm=True`). The second is deliberately **not** a bare model
score: it is the whole production path including intent routing, tool use, the money
validators, the repair pass, abstention, and keyword fallback.

| Metric | Numerator / denominator |
|---|---|
| `qa_pass_rate` | cases meeting their label / all cases |
| `qa_citation_validity` | answerable cases with ≥1 citation / answerable cases |
| `qa_correct_abstention_rate` | must-abstain cases that abstained / must-abstain cases |
| `qa_refusal_rate` | must-refuse cases refused / must-refuse cases |
| `qa_money_exact_rate` | money cases stating the exact expected figure / money cases |
| `qa_unverified_amount_emissions` | count of answers stating a figure no tool produced |
| `qa_answered_by_llm` / `qa_answered_by_rules` | per-case attribution of who answered |
| `qa_validator_caught_wrong_amount` | guardrail rejections of model-stated amounts |
| `qa_validator_caught_bad_citation` | guardrail rejections of unresolvable citations |
| `qa_llm_unavailable` | cases where the provider errored (see below) |

## What these metrics do NOT claim

- **`qa_refusal_rate` is a system guardrail, not model judgment.** `route_free_text`
  classifies injection attempts as `refuse` and returns before any model call
  (`src/agent/settlement_qa.py`). Never describe this as "the LLM refused".
- **`qa_citation_validity` is resolution, not support.** It asserts every cited ID exists
  in loaded data. It does not assert the citation semantically supports the sentence.
  Citation normalisation can also salvage weak model output, which inflates this figure.
- **`qa_unverified_amount_emissions` covers currency-marked amounts only** — `₹`, `Rs`,
  `Rs.`, `INR`, `N rupees`. Bare numerals are deliberately excluded: treating them as
  money would read "18% GST" and "50 records" as figures and reject correct answers.
  The allowed universe is every figure the evidence tools can produce for the case
  settlement plus every settlement the answer actually cited.
- **A high `qa_pass_rate` in the AI column can be pure fallback.** Read it together with
  `qa_answered_by_rules`. This is why attribution is mandatory.
- **`qa_llm_unavailable > 0` invalidates the AI column.** A quota-exhausted run yields a
  full set of plausible numbers that are pure keyword output. `ai_column_valid` goes
  false and the rendered report says so instead of presenting model figures.
- **The published figure is the worst of N runs**, never the mean and never the best,
  with unstable cases listed by name.

# Exception Lifecycle metrics

Emitted by `src/lifecycle/runner.py` over the hand-written fixtures in
`data/fixtures/lifecycle/`, labeled in `data/eval_lifecycle_labels.json`.

| Metric | Meaning |
|---|---|
| `lifecycle_exceptions_total` | open exceptions found in cycle 1 |
| `lifecycle_exceptions_closed` | exceptions compensated by a bound adjustment |
| `lifecycle_exceptions_open` | exceptions still unresolved |
| `lifecycle_closure_rate` | closed / total |
| `lifecycle_unmatched_adjustments` | adjustments received that bound to nothing |
| `lifecycle_mean_days_to_close` | mean days from flag to bound adjustment |
| `lifecycle_label_matches` / `_total` | agreement with the hand-written labels |

## What these metrics do NOT claim

- **Closure never repairs history.** `settlement_integrity_rate` is unchanged by any
  closure and a test asserts it. An adjustment compensates cash; the original control
  still failed. The two numbers are reported side by side and never combined.
- **Measured on fixtures, not the demo dataset.** The lifecycle runner reads only
  `data/fixtures/lifecycle/`, never the engine's `data_dir`, so closure cannot be
  confused with the 33-settlement demo batch.
- **Only `SETTLEMENT_TOTAL_MISMATCH` is closable.** It is the one exception type with a
  clean signed monetary delta. `FEE_OR_TAX_MISPOSTED` is detected but not closable, since
  no cash adjustment makes a historically wrong GST line correct.
- **Nothing is bound on probability.** Six predicates must all hold — valid adjustment
  line, matching currency and direction, exact paise, strictly later, exact settlement or
  UTR reference, and a unique one-to-one pairing. No tolerance, no fuzzy matching, and no
  LLM involvement. `rapidfuzz` may rank unmatched lines for human review only.
- **A low closure rate is the honest result.** One of five fixture exceptions closes
  (20%). The other four are designed to stay open: wrong amount, duplicate adjustments,
  missing reference, and no adjustment at all.
