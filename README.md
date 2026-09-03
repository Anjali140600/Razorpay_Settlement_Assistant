# Razorpay Settlement Assistant

Evidence-driven settlement Q&A and tax-line integrity for **Razorpay AI Buildathon 2026 — Track 04**.

> **Plan:** [docs/PLAN.md](docs/PLAN.md) · **Submit:** [SUBMISSION.md](SUBMISSION.md) · **What broke:** [docs/what-broke.md](docs/what-broke.md)

> Simple screen. Verified settlements, plain explanations, no uploads.

## Problem

Finance teams export 22-column Razorpay settlement reports and manually check batch totals, MDR fees, and 18% GST-on-MDR lines. Generic chatbots guess; spreadsheets don't scale.

## What it does

1. Ingests **Razorpay settlements + combined recon only** (no bank upload, no ERP)
2. Runs deterministic controls: **batch integrity** and **tax-line integrity**
3. Lets merchants **ask settlement questions** with **preset buttons + free-text Q&A** — evidence-backed or abstention
4. Exports honest metrics and full exception list

## Why Razorpay-native

| | Razorpay Settlement Assistant | Bank-upload reconcilers |
|--|------------------|-------------------------|
| Data needed | Dashboard/API data merchant already has | Full bank statement |
| Merchant trust | High — same boundary as Razorpay | Hesitation on PII |
| Dashboard fit | Embeddable via Settlements + Recon APIs | External tool |

## Quick start

```bash
pip install -r requirements.txt
python data/synthetic/generator.py
python -m src.cli --data-dir data/synthetic/demo
streamlit run apps/streamlit_app.py
# Or
./run.sh
```

Open http://localhost:8501

## Headline metrics

- **Settlement integrity rate** — verified / processed on **full demo batch** (not cherry-picked)
- **6 intentional failures** — tax, batch, refund, transfer, semantic errors exported honestly
- **Independent holdout** — 8 hand-crafted settlements separate from generator (`docs/dataset-realism.md`)
- **Tax-line pass rate** · **Throughput** · **Full exception export**
- **Q&A trust scorecard** — 41 hand-labeled questions scored on both answer paths.
  Measured: **money-exact 63.6% → 100%** with the AI path, **0 unverified amounts
  emitted**, and **12 model-stated wrong amounts caught by the deterministic
  validator**. See [sample-output/qa_scorecard.md](sample-output/qa_scorecard.md).
- **Exception closure rate** — measured on hand-written two-cycle fixtures. Most
  exceptions stay open by design; only an exact, uniquely-referenced adjustment closes one.

**Historical integrity is immutable.** A later Razorpay adjustment compensates cash; it
never makes a failed control pass. `settlement_integrity_rate` and
`lifecycle_closure_rate` are separate metrics that never mix, and a test enforces it.

See [docs/dataset-realism.md](docs/dataset-realism.md) for what we claim vs what we don't,
and [docs/metric-contracts.md](docs/metric-contracts.md) for what each metric does *not* claim.

## Measuring the agent

```bash
python -m src.eval.qa_cli --baseline-only      # deterministic path, no API key
python -m src.eval.qa_cli --runs 3             # both columns, needs a provider key
```

The scorecard refuses to present the AI column as a model measurement when the provider
was unavailable, so a quota-exhausted run cannot be published as model performance.

## Three demo paths

| Settlement ID | Scenario | Outcome |
|---------------|----------|---------|
| `setl_tax_mismatch` | GST-on-MDR line wrong | Flagged + Q&A explains |
| `setl_batch_mismatch` | Recon net ≠ header | Flagged |
| `setl_fee_semantic_error` | credit ≠ amount − fee | Flagged |
| `setl_refund_wrong_amount` | Refund debit ≠ amount | Flagged |
| `setl_transfer_tax_wrong` | Transfer GST wrong | Flagged |
| `setl_orphan_header_drift` | Header drift | Flagged |
| Messy profiles (`setl_messy_*`) | Flash sale, refunds, UPI promo, etc. | **Verified** when math holds |
| Holdout (`setl_holdout_*`) | Independent fixtures | 5 pass / 3 fail |

## Architecture

- [docs/PLAN.md](docs/PLAN.md) — master plan + implementation phases
- [docs/architecture.md](docs/architecture.md) — system overview
- [docs/what-broke.md](docs/what-broke.md) — failures, mitigations, and honest limits

## Agent modes

| Mode | Command |
|------|---------|
| Rules + keyword Q&A (default) | `./run.sh` |
| AI Q&A (Groq → Gemini → OpenRouter → keyword) | Set `USE_LLM=1` + `GROQ_API_KEY`, `GEMINI_API_KEY`, and/or `OPENROUTER_API_KEY` in `.env` |

Rules engine owns all amounts. Agent runs on exceptions and Q&A only.

## Tests

```bash
pytest tests/ -v
```

## Submission

- **Track:** 04 — AI Finance Controller
- **Direction:** Settlement Q&A + Tax-line matcher
- **Buildathon:** https://razorpay.com/buildathon/

## Limitations

Evaluator-grade prototype. Uses synthetic JSON shaped like Razorpay Settlements + Recon APIs. Bank/GL paths optional and not part of core narrative.
