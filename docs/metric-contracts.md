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
