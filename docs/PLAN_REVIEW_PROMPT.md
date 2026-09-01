# Plan Review Request

You are reviewing a hackathon submission plan for Razorpay AI Buildathon Track 04 (AI Finance Controller).

## Official brief (Track 04)
- Build an agent that closes ONE finance-ops loop on 50+ synthetic records
- Report match rate and exceptions that could NOT be resolved
- Bar: throughput + measured accuracy + honest exception list
- Example directions: Multi-source reconciliation, Settlement Q&A agent, Forward cash forecaster, Tax-line matcher
- Deadline: 5 September 2026
- Submission: public repo + 5-min video + architecture

## Context
The team pivoted FROM: bank CSV + GL/Tally three-way reconciliation
TO: Razorpay-native Settlement Q&A + tax-line integrity (settlements + recon JSON only, no bank upload)

## Files to review (read these in the repo)
- docs/PLAN.md (master plan)
- SCOPE.md
- docs/architecture.md
- docs/pitch-script.md
- docs/metric-contracts.md

## Existing codebase (partially implements OLD plan)
- src/controls/engine.py — batch integrity, bank match, GL validation
- src/agent/investigator.py — ReAct on exceptions
- apps/streamlit_app.py — dashboard
- data/synthetic/generator.py — demo data with bank/GL scenarios

## Review format (required)

### 1. Verdict
PASS / PASS WITH CHANGES / FAIL — one sentence why

### 2. Hackathon alignment (1-10)
Score vs Track 04 bar. Will judges buy this vs bank-reconciliation submissions?

### 3. Strengths (top 3)

### 4. Critical gaps / risks (top 5, ranked)

### 5. Scope realism
Can Phases 1-4 ship before 5 Sep with existing codebase? What to cut?

### 6. Differentiation
Does "Settlement Q&A + tax-line" stand out? Or too narrow?

### 7. Specific plan edits
Bullet list of concrete changes to PLAN.md before coding starts

### 8. Demo video risk
What will fail in a 5-min judge demo if not fixed?

### 9. Panel questions
Top 3 hard questions judges will ask + suggested answers

Be brutally honest. This is pre-implementation review — catch architecture mistakes now.
