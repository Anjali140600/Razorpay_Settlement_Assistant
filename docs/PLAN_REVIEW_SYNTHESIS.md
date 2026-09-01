# Plan Review Synthesis — Settlement Q&A + Tax-line Integrity

**Date:** 2026-08-31  
**Reviewers:** OpenAI Codex CLI (complete) · Claude CLI (failed — OAuth expired) · Cursor synthesis

---

## Review status

| Reviewer | Status | Output |
|----------|--------|--------|
| **Codex CLI** | ✅ Complete | Sections 1–9 below (also in terminal log) |
| **Claude CLI** | ❌ Blocked | `Failed to authenticate: OAuth session expired` — run `claude login` and re-run |
| **Synthesis** | ✅ This doc | Merged verdict + action list |

To re-run Claude review after login:

```bash
cd /home/vipin/vipinfolder/Razorpay_Reconciliator
cat docs/PLAN_REVIEW_PROMPT.md docs/PLAN.md | claude -p \
  --add-dir . --allowed-tools "Read,Grep,Glob" \
  | tee docs/PLAN_REVIEW_CLAUDE.md
```

---

## Codex verdict (full)

### 1. Verdict

**PASS WITH CHANGES** — the wedge is credible, but tax semantics, accuracy metrics, and old→new architecture transition are not defensible enough to code unchanged.

### 2. Hackathon alignment: **6/10** (can reach ~8/10)

- Covers 50+ records, agent, throughput, exceptions
- Judges may prefer bank-reconciliation (independent cash proof)
- This plan proves **internal Razorpay consistency only** until repositioned as **pre-bank settlement assurance**

### 3. Strengths

1. Privacy-friendly wedge — no bank/ERP upload; fits Dashboard
2. Correct AI boundary — rules own money; agent explains/abstains
3. Strong starting assets — engine, agent, Streamlit, 84-line dataset (pivot not greenfield)

### 4. Critical gaps (ranked)

| Priority | Gap |
|----------|-----|
| **P0** | Fee/GST contract may be wrong — plan uses `tax ≈ fee × 18%` and `credit = amount − fee`; Razorpay may treat fee as GST-inclusive (`tax ≈ fee × 18/118`) |
| **P0** | `false_auto_closes = 0` is hardcoded, not measured from labels |
| **P1** | Internal validation ≠ reconciliation — cannot prove bank receipt or contracted MDR |
| **P1** | Pivot larger than phases admit — engine/UI/tests still bank+GL centric |
| **P1** | Dataset circular — generator defines both truth and checks; no refunds/adjustments |

### 5. Scope realism

Phases 1–4 shippable **only with hard cuts:**

**Keep:** fee/tax control, core 2-source path, shared evidence layer, 4 preset Q&A, labeled metrics, offline demo

**Cut:** Phase 5, optional bank/GL before submit, second full ReAct planner, journal UI, LLM-timeout video scene

### 6. Differentiation

Stand out as: **“Razorpay-native settlement assurance — cited proof packets, no sensitive uploads”**  
Not: generic Q&A or single GST check alone

### 7. Required plan edits (Codex)

- Block on **Razorpay field contract** (fee inclusive/exclusive, rounding)
- Rename to **Fee & Tax Arithmetic Integrity**
- Explicit limitations: no bank, no contracted MDR, no tax invoice
- Immutable **ground-truth labels** for metrics (confusion matrix, not pass rate alone)
- One shared evidence layer (not two agents)
- Generic control list in decision model (not hardwired batch/bank/GL)
- Status: **Blocked on data contract** until P0 gaps fixed

### 8. Demo video risks

- UI still shows bank/ledger; no tax control or Q&A in code yet
- `setl_tax_mismatch` / `setl_batch_mismatch` don't exist in generator
- 100% precision is hardcoded
- Record **offline/deterministic**; LLM as bonus clip only

### 9. Panel Q&A (Codex)

1. *“Matching two Razorpay datasets?”* → Pre-bank settlement assurance, not cash proof  
2. *“Why AI if rules calculate?”* → Rules decide pass/fail; agent investigates/explains/abstains  
3. *“How measure accuracy?”* → Labeled manifest + confusion matrix; never claim 100% without proof  

---

## Independent review (Cursor — Claude substitute)

Aligns with Codex on P0 items; adds:

### Verdict: **PASS WITH CHANGES** (same)

### Additional points

1. **Reframe Track 04 loop** — Judges want “finance-ops loop.” Define loop as:
   > ingest recon → verify arithmetic → investigate → **Q&A closes merchant question** → export exceptions  
   Bank-free is OK if Q&A demo is **live and crisp** (not just docs).

2. **Tax-line is your moat IF correct** — India-specific GST-on-MDR is sharper than generic Q&A. **Fix fee/tax contract first** using one captured Razorpay API response in repo as golden fixture.

3. **Settlement Q&A must be deterministic-default** — Preset buttons call tool chain directly; LLM only rephrases. Judges won't tolerate API-key demo failure.

4. **Minimum viable demo paths (revised):**
   - Clean settlement → both checks PASS → Q&A “break down fees”
   - `setl_tax_mismatch` → tax FAIL → same Q&A
   - Unknown UTR query → abstain  
   Batch mismatch can be 4th path if time; don't block on it.

5. **Metric honesty** — Replace “100% precision” with:
   - `settlement_integrity_rate` (headline)
   - `labeled_control_accuracy` from `data/eval_labels.json`
   - `qa_citation_rate` for preset questions

### Hackathon alignment: **7/10** (slightly higher than Codex)

Razorpay-native + Q&A + tax-line hits **two** example directions. Differentiated vs bank-upload teams if pitch says **“settlement assurance before bank confirm.”**

---

## Merged action list (do before Phase 1 code)

| # | Action | Owner |
|---|--------|-------|
| 1 | Capture **one real Razorpay recon JSON snippet** (redacted) → `data/fixtures/recon_golden.json` | You |
| 2 | Document fee/tax formula in `docs/razorpay-field-contract.md` | Plan update |
| 3 | Fix generator tax math to match contract | Phase 1 |
| 4 | Add `data/eval_labels.json` — expected status per settlement_id | Phase 1 |
| 5 | Change PLAN status → **Blocked on field contract** until #1–2 done | Done below |
| 6 | Single `EvidenceTools` shared by investigator + Q&A | Phase 2–3 |
| 7 | Cut Phase 5 + bank/GL from submission narrative | Docs ✅ |
| 8 | Re-run Claude review after `claude login` | You |

---

## Recommended plan status change

~~Approved — implementation in progress~~  
→ **Blocked on Razorpay field contract + eval labels** (then Phase 1)

---

## Consensus: proceed?

**Yes, with P0 fixes first.** The pivot is sound; Codex and synthesis agree the **fee/GST semantics** and **metric honesty** are the blockers—not the product direction.

Next step after you confirm: update `docs/PLAN.md` with field contract section + revised phases, then implement Phase 1.
