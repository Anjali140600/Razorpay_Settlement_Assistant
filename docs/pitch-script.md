# Five-Minute Pitch Script

**Product:** Razorpay Settlement Assistant  
**Track:** 04 — AI Finance Controller  
**Direction:** Settlement Q&A + Tax-line integrity

---

## 0:00–0:35 — Problem & differentiation

> "Track 04 — AI Finance Controller. Merchants export 22-column Razorpay settlement reports and manually verify batch totals and GST-on-MDR lines.
>
> Razorpay Settlement Assistant runs on **Razorpay Dashboard data only** — no bank upload, no Tally. We verify every batch, answer finance questions with evidence, and export every exception we couldn't prove."

## 0:35–1:10 — Input & scale

- Show Streamlit dashboard loading demo data
- Point out: **{N} payment lines**, **{M} settlements** — settlements + recon only
- Click **Run verification**

## 1:10–1:55 — Throughput & honest metrics

- **Settlement integrity rate: X%** (batch + tax-line PASS)
- **Auto-close precision: 100%**, false auto-closes: **0**
- **Runtime / throughput**
- Scroll **full exception list** — "We don't hide unresolved items"

## 1:55–2:30 — Verified settlement

- Open a green (VERIFIED) settlement
- Walk: recon lines → Σcredit − Σdebit = header → fee + GST lines check
- "Deterministic rules own all amounts"

## 2:30–3:30 — Tax-line exception

- Open **`setl_tax_mismatch`**
- Show tax-line control FAIL — which payment line, expected vs actual GST
- Agent investigation summary
- Show tax-line control FAIL — **expected vs actual GST with gap**
- **Settlement Q&A:** "Break down fees and GST" → answer cites payment_ids

## 3:30–4:15 — AI Settlement Q&A

- Preset: "Break down fees & GST" (deterministic, fast)
- **Free-text with Groq on:** "Explain why this settlement failed verification" → badge "Answered via Groq", citations
- On failing settlement: "Please escalate to Razorpay support" → **ticket ID shown**
- Unknown UTR → agent **abstains** — cannot verify from loaded data

## 4:15–4:45 — Failure handled gracefully

- Groq retired model / quota → backup Groq model or rules; chat **says why**, not a silent fallback
- AI quoted **₹5,844** vs **₹58.44** → only `*_display` rupees; invented or mis-roled amounts **dropped**
- Groq fails → Cerebras / keyword; controls unchanged
- Prompt injection → refused; verification status unchanged
- Unknown UTR → **abstain** (write-up: [what-broke.md](what-broke.md))

## 4:45–5:00 — Close

- Download audit pack JSON
- "Every settlement verified, explained with evidence, or flagged honestly — Razorpay-native, merchant-safe, built for the Dashboard."

---

## Pre-recording checklist

- [ ] `streamlit run apps/streamlit_app.py` works from fresh clone
- [ ] Demo data generated
- [ ] Integrity metrics visible
- [ ] Tax mismatch + Q&A + abstention demonstrable
- [ ] Audit pack downloads

## Panel phrases

- **Integrity rate:** "Settlements passing batch + tax-line controls / processed settlements."
- **Why no bank?** "Razorpay-native v1; bank confirm optional Phase 2."
- **Why LLM?** "Q&A and exception narration; rules verify every rupee."
