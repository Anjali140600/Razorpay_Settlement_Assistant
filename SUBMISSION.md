# Submit — Razorpay AI Buildathon Track 04

**Direction:** Settlement Q&A + Tax-line integrity  
**Deadline:** 5 September 2026  
**Plan:** [docs/PLAN.md](docs/PLAN.md)

## 1. Verify locally

```bash
cd /path/to/your-cloned-repository
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/synthetic/generator.py
pytest tests/ -v
streamlit run apps/streamlit_app.py
```

Or: `./run.sh`

## 2. Record 5-minute video

Follow [docs/pitch-script.md](docs/pitch-script.md). Show in order:

1. Dashboard — **integrity rate**, 0 false auto-closes, exception list
2. **Verified settlement** — batch ✓ + tax lines ✓
3. **`setl_tax_mismatch`** — tax-line fail → **expected vs actual GST** + Q&A fee/GST breakdown
4. **Settlement Q&A** — preset (rules) + **one live Groq free-text** question with citations
5. **Support escalation** — ask to escalate failing settlement → ticket raised message
6. **Q&A abstention** — unknown UTR → cannot verify
7. Download audit pack

**Opening line:** "50+ Razorpay recon lines, settlement integrity rate, evidence-backed Q&A, and every exception we could not resolve — no bank upload required."

## 3. Push public GitHub repo

- Remove `.venv`, secrets, real PII
- Include `sample-output/cli_run.json`
- README with clone + run instructions

## 4. Submit form

https://razorpay.com/buildathon/

- Track: **04 — AI Finance Controller**
- Direction: **Settlement Q&A + Tax-line matcher**
- Links: GitHub repo + pitch video
- **What broke, and how you got out:** paste from [docs/what-broke.md](docs/what-broke.md) (use the short version)

## 5. Panel prep

| Question | Answer |
|----------|--------|
| Integrity rate? | % settlements passing batch + tax-line controls (denominator: processed) |
| Why no bank upload? | Razorpay-native v1; verifies Dashboard data; bank confirm is Phase 2 |
| Why LLM? | Rules verify money; Groq/Cerebras agent explains with read-only tools; keyword fallback offline |
| vs Dashboard export? | Auto-verifies 50+ lines; answers questions with payment_id evidence |
| Production? | Prototype; production = Settlements + Recon API embed in Dashboard |
| Merchant privacy? | Only Razorpay data merchant already trusts; no bank/ERP sharing |

## Do NOT do before deadline

- Bank upload as core narrative
- GL/Tally correction loop
- 100k stress test, FastAPI rewrite

Ship demo → record video → submit.
