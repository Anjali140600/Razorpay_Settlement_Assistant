# Q&A Trust Scorecard

**Cases:** 41 hand-labeled  
**Published figure:** deterministic path only, no AI run  
**Model:** not used in this run  
**Commit:** 3a22e98 · **Dataset:** `6e9fe2d829bb` · **Prompt:** `1a1601cd0287`  
**Generated:** 2026-09-02T10:02:10Z

> **The AI column was not measured in this run.** Only the deterministic
> path was scored, so no figure here describes model behaviour.

| Metric | Deterministic baseline |
|---|---|
| Pass rate | 82.9% |
| Citation validity | 100.0% |
| Correct abstention | 90.0% |
| Refusal (system guardrail) | 75.0% |
| Money exact | 63.6% |
| **Unverified amounts emitted** | 0 |
| Answered by rules | 41 |

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
