# Customer / Finance Validation (Lightweight)

**Status:** Informal builder validation only. Not a formal user study.

## What was validated

- Razorpay settlement-recon semantics: fee within credit, batch net = header amount, GST-on-MDR per line
- Demo exception paths shaped around Razorpay-native breaks: tax-line mismatch, batch mismatch, Q&A abstention
- Product pivot (Aug 2026): Settlement Q&A + tax-line integrity — no bank/ERP required for core wedge

## What was NOT validated

- No formal 5-interview customer discovery program
- No practicing CA sign-off (see `docs/accounting-model.md`)
- No quantified time-saved claims

## Product decisions influenced by finance logic (not interviews)

| Observation | Decision |
|-------------|----------|
| Settlement ≠ single bank row | Group by `settlement_id`, use Σcredit − Σdebit |
| `processed` ≠ cash received | SLA state machine for bank arrival |
| Same-amount bank rows | Abstain unless UTR discriminator exists |
| Missing fee in GL | Bounded correction template, human approval required |

## Before production

Conduct real merchant interviews and CA review of chart of accounts and posting policy.
