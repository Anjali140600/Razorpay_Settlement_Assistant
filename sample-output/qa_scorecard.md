# Q&A Trust Scorecard

**Cases:** 41 hand-labeled  
**Published figure:** worst of 1 clean run(s), 3 attempted (2 invalidated by provider limits)  
**Model:** groq / openai/gpt-oss-120b  
**Commit:** 96856f4 · **Dataset:** `6e9fe2d829bb` · **Prompt:** `1a1601cd0287`  
**Generated:** 2026-09-02T20:05:16Z

| Metric | Deterministic baseline | AI enabled (end to end) |
|---|---|---|
| Pass rate | 82.9% | 92.7% |
| Citation validity | 100.0% | 100.0% |
| Correct abstention | 90.0% | 90.0% |
| Refusal (system guardrail) | 75.0% | 75.0% |
| Money exact | 63.6% | 100.0% |
| **Unverified amounts emitted** | 0 | 0 |
| Answered by LLM | 0 | 26 |
| Answered by rules | 41 | 15 |
| Validator caught wrong amount | 0 | 12 |
| Validator caught bad citation | 0 | 2 |
| Provider unavailable on | — | 0 case(s) |

## How to read this

- The AI column is the **whole production path**: intent routing, tool use, the
  money validators, the repair pass, abstention, and keyword fallback. It is not
  a bare model score.
- **Answered by rules** in the AI column means the LLM produced nothing usable
  and the deterministic agent answered instead. Read the pass rate together
  with it, or a high score could be pure fallback.
- Prompt-injection refusal is a **system guardrail**, not model judgment: the
  router refuses those questions before the model is invoked.
- The money guard covers currency-marked amounts (`₹`, `Rs`, `INR`, `rupees`).
  Bare numerals are deliberately not treated as money, because '18% GST' and
  '50 records' would otherwise be read as figures.
- Citation validity means every cited ID resolves to loaded data. It does not
  assert that the citation semantically supports the sentence.
- Unverified amounts are measured against the figures the evidence tools can
  produce for the case settlement plus every settlement the answer cited.

## Cases that were not stable across runs

- `money_b2b_fee`
- `money_batch_gap`
- `money_batch_total_fee`
- `money_drift_gap`
