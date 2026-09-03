# Contextual Payment and Settlement Question Flow

**Date:** 2026-09-03

**Goal:** Make record selection an explicit first step. After a merchant confirms a payment or settlement, show contextual suggested questions plus an **Ask anything else** option. Show free text only after that option is chosen, keep it active for the rest of that subject conversation, and answer every follow-up using both the confirmed record and the relevant recent conversation.

## Problem confirmed in the current implementation

`_render_settlement_controls()` and `_render_pending_one_controls()` keep the selected record only in a local widget variable. `AssistantSession.subject_kind` and `subject_ids` are not updated until a predefined question is clicked. Meanwhile, `_assistant_dialog()` always renders the global `st.chat_input`.

As a result, a merchant can select a record and type a question, but `_handle_free_text()` still sees no active subject and responds with **Choose a record first**.

There is a second context gap after the subject is known. `_handle_free_text()` can recover `subject_kind` and `subject_ids` from `AssistantSession`, but `_settlement_response()` calls `answer_free_text()` with only the latest question, settlement ID, and current evidence. `_build_qa_user_payload()` similarly sends only `user_question`, `selected_settlement_id`, evidence, and related matches. The visible transcript is never supplied to the answer engine. This means a follow-up such as “why?”, “what about that fee?”, or “can I raise it?” has little or no knowledge of the preceding exchange.

## Product flow

### Settlement

```text
Understand a settlement
  -> Choose settlement
  -> Continue
  -> Suggested questions
       - Where is this settlement?
       - Why is net less than gross?
       - Break down fees & GST
       - Is this settlement consistent?
       - Ask anything else
  -> Preset: answer immediately with the confirmed settlement
  -> Ask anything else: reveal contextual free-text composer
```

### One unsettled payment

```text
Track an unsettled payment
  -> One payment
  -> Choose payment
  -> Continue
  -> Suggested questions
       - Where is my money?
       - When will this settle?
       - Can I get this instantly?
       - Why is it still pending?
       - Ask anything else
  -> Preset: answer immediately with the confirmed payment
  -> Ask anything else: reveal contextual free-text composer
```

The same explicit confirmation rule applies when a one-payment selector is entered from **Get funds sooner** or **Fix or report an issue**. Their specialized next step remains intact.

For **Several payments** and **All unsettled payments**, retain the existing aggregate actions in this change. Contextual arbitrary Q&A over a payment set should be added separately because `_handle_free_text()` currently has no `PENDING_PAYMENT_SET` answer path.

## Interaction rules

- A dropdown change does not submit or answer anything.
- A primary **Continue** button explicitly accepts the selected record.
- **Continue** saves `subject_kind` and `subject_ids` before navigating to the question menu.
- The question menu repeats the selected record in a compact context line and offers **Change selection**.
- The free-text composer is hidden on the home, selection, and suggested-question screens.
- Clicking **Ask anything else** moves to a contextual free-text state and reveals the composer.
- Once the merchant enters contextual free-text mode, the composer stays visible after every answer until they go Back, change the selected record, return to the Main menu, or start a New chat.
- The composer placeholder names the selected context, for example `Ask about setl_123…` or `Ask about pay_pending_000…`.
- Submitted free text uses the confirmed session subject even when the text contains no ID.
- Every free-text request also receives a bounded, subject-scoped view of the preceding conversation so follow-ups and interruptions are understandable.
- The confirmed subject is authoritative. A pronoun such as “this” or “that payment” refers to it. Mentioning a different ID does not silently replace it; the assistant asks the merchant to confirm a context switch.
- **Back** from free text returns to the suggested questions and keeps the confirmed record.
- **Change selection** returns to the selector and clears the confirmed subject before another record can be used.
- **Main menu** and **New chat** clear the subject as they do today.
- The transcript remains visible throughout; only the active controls and composer change.

## State-machine changes

### `src/agent/conversation.py`

Add explicit nodes:

- `SETTLEMENT_QUESTIONS`
- `SETTLEMENT_CUSTOM_QUESTION`
- `PENDING_ONE_QUESTIONS`
- `PENDING_ONE_CUSTOM_QUESTION`

Add them to `VALID_NODES` and give each a focused `node_response()`:

- question nodes: “What would you like to know about this record?”
- custom nodes: “Ask anything else about the selected record.”

Add a pure helper such as `confirm_subject_selection(session, kind, ids, target, label)` that performs one atomic transition:

1. append the confirmed selection to the transcript;
2. set `subject_kind` and `subject_ids`;
3. push the selector node onto `back_stack`;
4. navigate to the appropriate question node;
5. append that node's assistant response.

Add a `change_subject_selection()` helper that navigates back to the correct selector while clearing `subject_kind`, `subject_ids`, `pending_action`, and any resolution state. Do not overload ordinary `go_back()`, because Back from the custom composer should retain context.

Extend `AssistantSession` with explicit subject-conversation metadata:

- `subject_context_start: int | None` — transcript index at which the active subject was confirmed;
- `last_intent: str | None` — the most recently answered deterministic/preset intent for short follow-ups;
- optionally `context_version: int` — incremented whenever the active subject changes, making stale cache entries and widget drafts impossible to reuse.

Do not duplicate the entire transcript in a second session-state field. The transcript remains the source for display and recent-turn extraction; the metadata above defines which portion belongs to the active subject.

## Streamlit UI changes

### `apps/universal_assistant.py`

1. Split selection from question rendering.
   - `_render_settlement_controls()` renders only the settlement dropdown and **Continue**.
   - `_render_pending_one_controls()` renders only the payment dropdown and **Continue** for the normal tracking path.
   - Move the existing preset buttons into `_render_settlement_question_controls()` and `_render_pending_question_controls()`.

2. Confirm subject before moving forward.
   - Settlement Continue stores `AssistantSubjectKind.SETTLEMENT` plus `[sid]`.
   - Payment Continue stores `AssistantSubjectKind.PENDING_PAYMENT` plus `[payment.entity_id]`.
   - The question renderers resolve objects from `AssistantDataContext` using the stored IDs rather than relying on stale widget objects.

3. Add **Ask anything else** to both question menus.
   - It navigates to the matching custom-question node without clearing the subject.
   - It does not call the answer engine itself.
   - After a preset answer, keep **Ask anything else** available as the way to interrupt the guided flow with a custom follow-up.

4. Render `st.chat_input` conditionally.
   - Show it only for `FREE_TEXT`, `SETTLEMENT_CUSTOM_QUESTION`, and `PENDING_ONE_CUSTOM_QUESTION`.
   - Preserve the existing generic `FREE_TEXT` path if the product still exposes **Ask something else** from the home menu.
   - Use distinct stable widget keys per context state so a draft from one record cannot appear for another.
   - Do not leave the custom node after submission; repeated follow-ups remain in the same contextual free-text mode.

5. Keep the existing answer boundaries.
   - Settlement custom text continues through `_settlement_response()`.
   - Payment custom text continues through `_pending_response()`.
   - `_handle_free_text()` remains the central safety and subject resolver, but the confirmed subject now exists before it is called.
   - Resolve the active subject before building conversation memory. Chat text may help interpret a question, but it never grants authority to select records or perform actions.

6. Add **Change selection** near the selected-record context line.
   - This is a non-consequential navigation action.
   - It clears the active subject before returning to the selector.

7. Show persistent context while free text is active.
   - Render a compact line above the composer, such as `Asking about settlement setl_123`.
   - Keep **Change selection** accessible beside it.
   - If the selected record disappears after a data refresh, stop before answering and return the merchant to selection with an explanatory message.

## Conversation-memory changes

### Build subject-scoped recent history

Add a pure helper in `src/agent/conversation.py`, for example:

```python
recent_subject_context(
    session: AssistantSession,
    *,
    max_exchanges: int = 6,
    max_chars: int = 4_000,
) -> list[dict[str, str]]
```

It should:

1. read messages only from `subject_context_start` onward;
2. include the most recent merchant questions and merchant-visible assistant headings/summaries;
3. preserve order while limiting both exchange count and total characters;
4. omit tool traces, internal prompts, hidden metadata, and action payloads;
5. exclude selector/navigation chatter unless it is needed to establish the active subject;
6. return no history after Change selection, Main menu, or New chat starts a new context epoch.

The current `AssistantResponse` is structured, so add a deterministic serializer that extracts only `heading`, `summary`, and concise visible detail/next-step text. Do not serialize arbitrary Pydantic objects or the full Streamlit session.

### Pass context into settlement free text

Update the call chain with a backward-compatible optional parameter:

```text
_handle_free_text()
  -> _settlement_response(..., conversation_context=...)
  -> answer_free_text(..., conversation_context=None)
  -> _react_qa_llm(..., conversation_context=None)
  -> _build_qa_user_payload(..., conversation_context=None)
```

Existing CLI, evaluation, and unit-test callers can omit it. The payload supplied to the model should clearly separate:

- `current_question` — the new merchant message;
- `active_subject` — server-selected kind and IDs;
- `recent_conversation` — untrusted dialogue used only to resolve references and follow-ups;
- `evidence` — current authoritative Razorpay facts.

Update the system prompt to state that recent conversation is context, not evidence or instruction, and that the active subject plus tool evidence override any conflicting statement in chat history.

### Support deterministic and LLM-disabled follow-ups

Conversation continuity must not disappear when `use_llm=False` or providers fail. Store the last resolved intent after both preset and free-text answers. Before falling back to a generic keyword answer:

- resolve short references such as “why?”, “explain that”, “what about GST?”, and “can I raise it?” against `last_intent`, the active subject, and currently offered typed actions;
- keep safety/action intents deterministic and higher priority than conversational inference;
- if more than one interpretation remains plausible, ask a targeted clarification and show the subject's predefined questions rather than guessing.

For pending payments, extend `answer_pending_query()` with optional prior-intent/context input or add a small `route_pending_follow_up()` helper. It should never infer settlement facts that do not exist.

### Make caching context-aware

The existing LLM cache key uses only normalized question, settlement ID, and the batch fingerprint. Add a hash of the sanitized, bounded recent conversation (or `context_version` plus its last-intent fingerprint). Otherwise identical phrases such as “why?” could incorrectly reuse an answer from a different earlier exchange.

### Preserve trust boundaries

- Sanitize and length-limit every history item before model submission.
- Never let an earlier user message override the active subject, verification status, safety policy, or pending-action confirmation rules.
- Compute allowed monetary figures from authoritative evidence/tool results only. Do **not** allow numbers merely because they appear in `recent_conversation`; adding history to the current payload before `money_figures()` would accidentally weaken the amount guardrail.
- Keep ticket/claim/Instant Settlement actions typed and confirmation-gated. A conversational phrase may propose an action but cannot execute it.
- Re-resolve subject IDs against the latest `AssistantDataContext` on every turn.

## Suggested copy

- Selector CTA: **Continue**
- Question heading: **What would you like to know?**
- Settlement context: `Asking about settlement setl_123`
- Payment context: `Asking about payment pay_pending_000`
- Custom option: **Ask anything else**
- Settlement placeholder: `Ask anything about settlement setl_123…`
- Payment placeholder: `Ask anything about payment pay_pending_000…`
- Context reset: **Change selection**
- Ambiguous follow-up: `Are you asking about the settlement status or its fee and GST breakdown?`
- Different record detected: `You’re currently asking about setl_123. Switch to setl_456?`

## Test plan

### Pure state tests — `tests/test_conversation.py`

- Confirming a settlement stores its kind and ID and advances to `SETTLEMENT_QUESTIONS`.
- Confirming a payment stores its kind and ID and advances to `PENDING_ONE_QUESTIONS`.
- Moving from a question menu to its custom node preserves the selected subject.
- The subject context start/index is created when selection is confirmed.
- Back from a custom node preserves the subject and returns to the question menu.
- Change selection clears the subject and returns to the correct selector.
- Changing subjects starts a new context epoch and excludes the old subject's turns from recent history.
- Recent-context extraction is ordered, bounded, and contains only merchant-visible text.
- Main menu and New chat still clear all subject state.
- Invalid target nodes remain rejected.

### Streamlit interaction tests — `tests/test_universal_assistant_app.py`

- The composer is absent on the initial guided menu.
- Settlement selection shows **Continue**, not preset questions.
- After Continue, all settlement presets and **Ask anything else** appear; the composer is still absent.
- Clicking **Ask anything else** reveals exactly one composer.
- A custom settlement question without an ID answers against the confirmed settlement and never renders **Choose a record first**.
- After that answer, the composer remains visible and a second follow-up still uses the same settlement.
- A preset question followed by **Ask anything else** and “why?” carries both the confirmed subject and the preset exchange into the answer engine.
- Repeat the same select -> Continue -> Ask anything else -> submit flow for one pending payment.
- Changing the selection prevents the old subject ID from being reused.
- Mentioning another record prompts for a context switch instead of silently changing subjects.
- A preset still answers immediately and retains its existing evidence/actions.
- Empty settlement/payment datasets continue to show their current informational messages.

### Answer-engine and security tests

- `tests/test_settlement_qa_llm.py`: the model payload contains bounded recent conversation, current question, active subject, and current evidence as separate fields.
- `tests/test_settlement_qa_llm.py`: two identical “why?” questions with different recent histories do not share a cache entry.
- `tests/test_settlement_qa.py`: LLM-disabled short follow-ups use `last_intent` where deterministic and clarify when ambiguous.
- `tests/test_settlement_qa_security.py`: instructions or record IDs in old dialogue cannot override the active subject.
- `tests/test_settlement_qa_security.py`: monetary values appearing only in conversation history are not added to the allowed-money set.

### Regression tests

Run:

```bash
pytest tests/test_conversation.py \
  tests/test_universal_assistant_app.py \
  tests/test_universal_assistant_settlement_context.py \
  tests/test_settlement_qa.py \
  tests/test_settlement_qa_llm.py \
  tests/test_settlement_qa_security.py \
  tests/test_assistant_responses.py
```

Then run the full suite:

```bash
pytest
```

## Acceptance criteria

- Selecting a payment or settlement never silently activates it; **Continue** is required.
- Suggested questions appear only after the selection is accepted.
- Free text appears only after **Ask anything else** (or the intentionally retained generic home free-text path).
- A custom question is answered using the confirmed payment or settlement even when the merchant does not repeat its ID.
- Once contextual free text is opened, it remains usable for an uninterrupted multi-turn conversation about that subject.
- Follow-ups can refer to the recent exchange (“why?”, “that fee”, “raise it”) without restating the record or full question.
- Switching records creates a clean context boundary; old subject turns cannot influence the new answer.
- Conversation history helps interpret language but cannot override evidence, safety rules, or confirmation requirements.
- Back, Change selection, Main menu, and New chat have deterministic, tested context behavior.
- Existing preset answers, support handoff, compensation, Instant Settlement, and transcript behavior do not regress.

## Non-goals

- No change to settlement calculations, triage, LLM provider order, or support-ticket authorization.
- No arbitrary multi-payment-set Q&A in this change.
- No automatic answer on dropdown change.
- No custom HTML or JavaScript; native Streamlit controls and session state are sufficient.
