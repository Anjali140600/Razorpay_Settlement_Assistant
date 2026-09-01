# Synthetic Accounting Model

**Status:** Builder-authored synthetic policy. Not externally CA-endorsed.

## Scope

This document defines the frozen v1 accounting policy for the hackathon demo. A practicing accountant or CA should review before production use.

## Chart of Accounts

| Code | Name | Type |
|------|------|------|
| 1100 | Bank - Current | Asset |
| 1200 | Gateway Clearing | Asset |
| 1210 | Settlement-in-Transit | Asset |
| 2100 | Customer Receivable | Asset |
| 4100 | Gateway Fee Expense | Expense |
| 4110 | Fee Tax Suspense | Expense |
| 5100 | Customer Refunds | Expense |

## Event → Journal Mapping

### 1. Captured payment (daily aggregate)

- **Dr** Gateway Clearing (1200)
- **Cr** Customer Receivable (2100)
- Amount: gross captured

### 2. Processed settlement

- **Dr** Settlement-in-Transit (1210)
- **Cr** Gateway Clearing (1200)
- Amount: net settlement (Σcredit − Σdebit from recon)

### 3. Fee evidenced in settled recon

- **Dr** Gateway Fee Expense (4100) — `fee − tax`
- **Dr** Fee Tax Suspense (4110) — `tax`
- **Cr** Gateway Clearing (1200) — total `fee`

Tax is posted to suspense, not claimed as Input GST.

### 4. Bank credit verified

- **Dr** Bank (1100)
- **Cr** Settlement-in-Transit (1210)
- Amount: net settlement

## Correction Templates

### Missing fee/tax posting

When recon shows fees but GL lacks fee journal:

- **Dr** 4100 (fee − tax) + **Dr** 4110 (tax)
- **Cr** 1200 (total fee)

### Misclassified fee

Reclassify between expense accounts without touching Gateway Clearing.

## Review Checklist (for CA/finance reviewer)

- [ ] Settlement net = Σcredit − Σdebit (do not double-subtract fee/tax)
- [ ] Fee recognition at settled-recon timing is consistent across demo
- [ ] Bank debit only when bank evidence exists
- [ ] Refund timing: processed from gateway balance reduces clearing
- [ ] Partial settlements: deferred captures remain in clearing

## Limitations

- Single merchant, single INR bank account
- No GST filing or input credit claims
- Aggregate journals only (not per-payment GL in demo)
- Instant Settlements excluded

## Reviewer Notes

_Placeholder for external reviewer sign-off. If no review occurred, all journals remain builder-authored._

- Reviewer: _Not yet conducted_
- Date: _N/A_
- Scope reviewed: Chart of accounts, settlement transit journal, fee posting, correction template
