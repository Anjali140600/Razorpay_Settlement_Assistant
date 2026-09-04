# QA report: Unsettled Payments chatbot

- Date: 2026-09-03
- Target: `http://localhost:8501`
- Scope: Compare the Settlement and Unsettled Payments chatbot layouts
- Result: Fixed and browser-verified

## Summary

The Unsettled Payments view exposed only a disabled send button after a payment
was selected. It did not render the chatbot header, online status, greeting,
scrollable thread, suggested questions, visible composer, evidence hint, or the
separate bordered card used by the Settlement view.

The pending-payment chatbot now uses the same visual structure as the settlement
chatbot, with payment-specific copy and independent history/reset state.

## ISSUE-001: Pending chatbot layout was incomplete

- Severity: High
- Category: Functional / visual / UX
- Fix status: Verified
- File changed: `apps/streamlit_app.py`
- Before: `screenshots/unsettled-selected-before.png`
- After: `screenshots/unsettled-chat-after.png`

Verification:

- Header, avatar, online status, and New chat action render.
- A bordered 430px conversation thread renders with an initial assistant message.
- Four payment-specific suggested questions render as chips.
- The chat input is visible and has an accessible label.
- The payment-specific evidence hint renders below the composer.
- Browser console reported no errors.

## Deferred observation

At a 375px viewport, an open Streamlit sidebar covers most of the main content.
This affects both chatbot views and is outside this focused parity fix.

## Automated checks

- `python3 -m py_compile apps/streamlit_app.py`: passed
- `.venv/bin/pytest -q`: 298 passed

## Outcome

Scoped chatbot health: 94 -> 100.

PR summary: QA found 1 scoped chatbot issue, fixed 1, health score 94 -> 100.
