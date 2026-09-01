# Frozen MVP Scope — Razorpay Settlement Assistant (Final)

**Master plan:** [docs/PLAN.md](docs/PLAN.md) — single final build, no phases.

## Product

Simple merchant UI: verify Razorpay settlements, explain fees/GST, answer preset questions. Razorpay data only. No bank or ERP.

## In scope

1. Razorpay settlement + combined recon adapters  
2. Batch integrity + fee/GST line integrity controls  
3. Settlement Q&A — **four presets + free-text box**, evidence-backed, abstention  
4. Simple readable UI (16px+ body, plain language, essential info only)  
5. Demo exceptions: tax mismatch, batch mismatch, Q&A abstention  
6. Metrics: settlement integrity rate, honest exception export, labeled eval  
7. One-command startup + 5-min video submission  

## Out of scope

- Bank statement upload, ledger/Tally, journal posting UI  
- Multi-phase rollout, optional bank/GL modes in product narrative  

## Done when

Merchant understands the screen in 10 seconds; all success criteria in PLAN.md Section 8 are met.
