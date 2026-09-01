# Plan Review v2 — Free-text Q&A + AI Security

**Date:** 2026-09-01  
**Plan reviewed:** [PLAN.md](PLAN.md) Sections 4.4, 12  
**Codex CLI:** ✅ Complete — full review in [PLAN_REVIEW_CODEX_v2.md](PLAN_REVIEW_CODEX_v2.md) (tail of file)  
**This doc:** Summary + security review

---

## 1. Verdict

**PASS WITH CHANGES** — Presets + free-text is the right UX for a simple merchant product; Section 12 security is a strong start but needs structured output validation and deterministic routing before ship.

---

## 2. Hackathon alignment: **8/10** (Codex)

Codex scored **8/10** — strong Track 04 fit (Q&A + tax-line named directions). Loses points for vague “measured accuracy” and LLM-off default risking “rules dashboard with AI label.”

---

## 3. Strengths

1. **Simple UX preserved** — Presets for speed; free-text for real merchant questions without leaving the screen  
2. **Security-by-design** — Untrusted input, allowlist tools, deterministic controls unchanged by AI  
3. **Demo story strengthened** — Prompt-injection refusal in video proves Track 04 “failure handled gracefully”

---

## 4. Critical gaps / risks (ranked)

| # | Risk | Mitigation (add to build) |
|---|------|-------------------------|
| 1 | Fee/GST formula still unvalidated | `docs/razorpay-field-contract.md` + golden fixture **before** controls |
| 2 | Free-text + LLM can hallucinate despite rules | **Structured JSON answer** + citation validator (now in PLAN 12.5) |
| 3 | Keyword router too naive for free-text | Map intents: lookup / breakdown / consistency / unknown → fixed tool chains |
| 4 | Code still bank/GL centric | Build list Section 6 must execute before demo |
| 5 | Session rate limit (10) bypassable via refresh | Acceptable for demo; note in panel |

---

## 5. Free-text Q&A design

**Yes — preset + free-text is right.**

| Aspect | Assessment |
|--------|------------|
| UX | Presets teach what’s possible; free-text catches “fee on pay_…” without extra clicks |
| Simplicity | One text box + Ask button below chips — fits Section 3 layout |
| Risk | Wider attack surface — mitigated by Section 12 if implemented in code, not docs only |

**Recommendation:** Free-text routes through **same tool chains as presets** where possible; LLM only for intent classification when offline keywords don’t match.

---

## 6. AI security review

### What Section 12 covers well ✅

- Untrusted user input  
- System prompt isolation  
- Read-only tool allowlist  
- Deterministic controls cannot be flipped by AI  
- Input length limit (500)  
- Session rate limit (10)  
- Injection test cases listed  
- Demo video shows failed injection  

### What was missing (now added to PLAN 12.5) ✅

- **Structured JSON output** before UI render  
- **Citation validator** — reject answers citing non-existent ids  
- **Max 6 tool calls** per question  

### Still implement in code

| Control | Purpose |
|---------|---------|
| `sanitize_question()` | Strip control chars, enforce 500 char, reject empty |
| `validate_citations(answer, loaded_data)` | Anti-hallucination |
| `route_question()` | Deterministic keywords first; LLM tool-calling second |
| `refusal_templates` | Fixed strings for out-of-scope / injection — no LLM rewrite |
| `tests/test_settlement_qa_security.py` | All cases in PLAN 12.7 |

### Threat coverage

| Threat | Covered? |
|--------|----------|
| Prompt injection | ✅ Controls unchanged; refusal template |
| Tool abuse | ✅ Allowlist only |
| Secret exfiltration | ✅ No keys in prompts/logs/responses |
| Hallucination | ✅ Citations required + validator |
| DoS (long input) | ✅ 500 char + rate limit |
| Financial harm narrative | ✅ Refuse transfers/status changes |

---

## 7. Specific plan edits (applied / recommended)

- [x] Free-text box required in PLAN Section 3, 4.4, 6, 8  
- [x] Section 12 AI security added to PLAN  
- [x] `docs/security.md` expanded  
- [x] Structured JSON + citation validator in PLAN 12.5  
- [ ] Add `docs/razorpay-field-contract.md` (still blocking)  
- [ ] Add intent routing table to PLAN 4.4 (optional small addition)

---

## 8. Demo video risk

| Risk | Mitigation |
|------|------------|
| Free-text LLM hangs | Demo with **planner/keyword** path; LLM optional clip |
| Injection demo fails | Pre-test scripted question in rehearsal |
| UI cluttered | Keep free-text **one line** below presets, 16px+ |

Show: preset → answer → free-text custom question → injection refused → controls unchanged.

---

## 9. Panel questions

1. **“Is free-text safe?”**  
   → User input never touches system instructions; tools are read-only; verification status is deterministic; we demo a failed injection.

2. **“Can AI mark settlements verified?”**  
   → No. Only batch + fee/GST rules set status. AI explains and answers questions.

3. **“Why not just presets?”**  
   → Presets cover 80% of questions; free-text handles specific payment ids and dates without building infinite buttons.

---

## Consensus

**Proceed to build** after `razorpay-field-contract.md` is written. Free-text + Section 12 security are approved product requirements.
