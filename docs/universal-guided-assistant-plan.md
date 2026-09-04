# Universal guided assistant plan

**Status:** Proposed implementation plan  
**Date:** 3 September 2026  
**Scope:** Replace the two embedded chat surfaces with one universal assistant that supports guided workflows and free-text questions.

## 1. Recommendation

Build this.

The current product makes merchants first navigate to the correct section, select an item, and then use a chatbot tied to that item. A universal assistant removes that duplication and gives the product one place to:

- find a payment or settlement;
- explain status, fees, GST, UTR, and integrity results;
- guide the merchant through a safe resolution;
- offer a compensation claim only when deterministic triage permits it;
- collect evidence and raise a support ticket when self-service cannot resolve the issue;
- accept free text at every point, including while a guided flow is active.

The recommended implementation is a single explicit workflow engine around the existing deterministic Q&A and triage functions. Do not turn the guided path into another LLM prompt. Buttons choose deterministic transitions; the LLM remains limited to understanding or phrasing free-text questions.

## 2. Important correction to the proposed flow

Do not tell a merchant that Razorpay will settle a specific selected payment.

Razorpay's Instant Settlement API creates an on-demand settlement using:

- a requested amount in paise; or
- `settle_full_balance=true` for the maximum available balance.

It does not accept a list of payment IDs whose funds must be settled. Therefore:

- **One selected payment** means “use this payment's amount as the requested amount.”
- **Several selected payments** means “sum these payments to calculate the requested amount.”
- **All unsettled payments** must not be presented as equivalent to `settle_full_balance=true`; the available balance, fees, holds, refunds, daily limit, and other account rules may make those totals different.
- The confirmation screen must say that Instant Settlement draws from the merchant's available Razorpay balance and does not preserve payment-level attribution.

The current app has no live Instant Settlement quote or create connector. Until those exist, the UI must label the operation as a simulation and route the merchant to Razorpay's supported action or support path. It must not display a fake successful bank transfer.

## 3. Product goals

### Goals

1. One assistant entry point on every product view.
2. A useful menu appears when the assistant opens or the merchant types a greeting such as “hi”.
3. Guided and free-text interaction can be mixed in the same conversation.
4. The merchant can search for or select one settlement, one pending payment, multiple pending payments, or an account-level scope.
5. Every answer and action uses the same existing evidence, validation, and triage rules.
6. Every unresolved path can reach support without trapping the merchant in more bot questions.
7. A support ticket contains the conversation summary and all relevant evidence already collected.
8. Payment and settlement screens remain focused on browsing, tracking, and inspecting records.

### Non-goals for the first release

- No autonomous money movement.
- No LLM authority to file claims, create instant settlements, raise tickets, or change verification status.
- No promise that a payment ID maps to a particular Instant Settlement payout.
- No permanent cross-device transcript unless a persistent conversation store is explicitly added.
- No attempt to make a single giant decision tree for every future support topic.

## 4. Recommended merchant experience

### 4.1 Universal launcher

- Show one `support_agent` launcher at the bottom-right of the page.
- Keep it visible while the merchant browses settlements or pending payments.
- Clicking it opens a medium-width native Streamlit dialog containing the assistant.
- The dialog preserves its transcript and workflow state when the merchant changes the browse category or selected row.
- The launcher has an accessible label such as “Open support assistant,” a visible focus state, and a minimum 44 by 44 pixel target.
- On mobile, the dialog becomes the primary overlay and the launcher stays above Streamlit's own controls.

Implementation preference for this Streamlit prototype:

1. Use a keyed native `st.button` as the launcher and `@st.dialog(width="medium")` for the assistant.
2. Apply narrowly scoped CSS only to the launcher's key class to fix it to the bottom-right.
3. Run a small UI spike before the main refactor to verify positioning, keyboard focus, reruns, and mobile behavior in Streamlit 1.55.
4. If the native button cannot meet accessibility or positioning requirements, replace only the launcher with an inline Custom Component v2. Keep the conversation UI in native Streamlit.

### 4.2 Opening message

Opening the assistant should immediately produce the same result as typing “hi”:

> Hi, I can help you track money, understand a settlement, get funds sooner, or contact support. What do you need?

Primary choices:

1. **Track an unsettled payment**
2. **Understand a settlement**
3. **Get funds sooner**
4. **Fix or report an issue**
5. **Ask something else**

This is better than beginning with product nouns alone (“payment or settlement?”). It starts with the merchant's goal while still routing to those two data types.

The free-text composer remains visible below these choices. The merchant never has to finish or exit the menu before typing a question.

### 4.3 Controls available throughout a guided flow

- **Back** returns one workflow step without deleting transcript history.
- **Main menu** clears the current guided selection but preserves the transcript.
- **Start over** starts a new conversation after confirmation if an action is pending.
- **Talk to support** bypasses further troubleshooting and begins the ticket handoff.
- A button choice is appended to the transcript as a user message, so the conversation remains understandable.

Use `st.pills` or buttons for two to five visible choices, `st.selectbox` for one item from a long list, and `st.multiselect` for several pending payments.

### 4.4 Resolution checkpoint

After each substantive answer, show:

- **Yes, resolved**
- **No, I still need help**
- **Ask another question**

“No” should not blindly repeat the same answer. It either offers the next deterministic diagnostic step or presents the support handoff. A direct free-text request such as “talk to a person” starts handoff immediately.

### 4.5 Structured answer layout

Do not render assistant answers as one long paragraph. Every substantive reply, whether produced from a guided choice or free text, follows the same scannable contract:

1. **Outcome heading** — for example, “This settlement needs attention” or “Payment is still within its expected window.”
2. **Direct answer** — one or two sentences answering the merchant's question.
3. **Details or calculation** — short bullets, labeled values, or a compact table when there are several comparable rows.
4. **Evidence** — settlement, payment, UTR, dates, control checks, or other loaded facts used for the answer.
5. **Recommended next step** — a plain-language explanation of what the merchant should do next.
6. **Available actions** — explicit buttons for functionality relevant to this result.
7. **Resolution checkpoint** — shown after the result unless the merchant has already entered a confirmation or handoff flow.

Keep empty sections hidden. Use native Streamlit elements inside `st.chat_message`: a concise heading/status indicator, `st.write` for the direct answer, bullets or labeled rows for details, and `st.container(horizontal=True)` for a small button group. Do not create a dense stack of decorative cards.

Example unresolved response:

```text
Bank credit cannot be verified here

The settlement is marked processed, but this app does not have access to
your bank statement, so I cannot confirm whether the credit arrived.

What I checked
- Settlement: setl_123
- Amount: ₹12,450.00
- UTR: 123456789012
- Razorpay status: processed

Recommended next step
Raise a support ticket with these details already attached.

[Raise ticket]  [View settlement]  [Main menu]
```

### 4.6 Contextual functionality buttons

Buttons are part of the answer contract, not a presentation-time guess based on words in `answer_text`.

- A direct free-text request such as “raise a ticket” returns a visible **Raise ticket** button.
- An unresolved, abstained, or bank-non-receipt result includes **Raise ticket** automatically.
- A compensable result includes **Submit claim** and **Raise ticket** when both are allowed by deterministic rules.
- A settlement answer can include **View settlement**; a pending-payment answer can include **View payment**.
- An eligible “get funds sooner” result can include **Get Instant Settlement quote**.
- A created ticket, claim, or settlement request includes its relevant **Track status** action.
- Result-specific actions should normally be limited to the two or three most useful choices. Navigation controls remain separate.

Every guided node has a persistent escape area with **Back** when applicable, **Main menu**, and **Talk to support**. Selecting **Talk to support** creates a ticket proposal from the context already collected. It does not immediately file the ticket.

The backend emits typed actions with stable IDs, labels, required context, eligibility state, and confirmation requirements. The UI only renders those actions and sends the chosen action ID back as an event. If a requested function is known but currently unavailable, show a disabled action with a short reason or explain the alternative; never display a button that pretends the capability succeeded.

All consequential buttons are proposals. **Raise ticket**, **Submit claim**, and **Get Instant Settlement quote/create** open a review step; a separate explicit confirmation performs the write.

## 5. Guided flow map

```text
Open assistant or type greeting
        |
        v
Main menu ---------------------------------------------------+
  |                 |                 |              |       |
  v                 v                 v              v       v
Track pending   Understand        Get funds      Fix/report  Free text
payment         settlement        sooner         an issue    router
  |                 |                 |              |
Choose scope     Find/select       Choose amount   Choose category
one/many/all     settlement        basis           and subject
  |                 |                 |              |
Choose question  Choose question   Eligibility +   Run triage or
  |                 |              quote checks     collect evidence
  v                 v                 |              |
Evidence-backed  Evidence-backed     v              v
answer           answer           Review action   Proposed resolution
  |                 |                 |              |
  +-----------------+------------> Explicit confirm <+
                    |                 |
                    v                 v
              Resolution check    Execute connector
                    |                 |
             resolved / support   Result + tracking
```

## 6. Detailed guided paths

### 6.1 Track an unsettled payment

1. Ask for scope:
   - One payment
   - Several payments
   - All currently unsettled payments
2. Let the merchant find records by payment ID, order ID, amount, or list selection.
3. Ask what they need:
   - When should this settle?
   - Why is it still pending?
   - Is Instant Settlement available?
   - Summarize the selected payments
4. Answer from `PendingPayment` data and settlement-cycle policy.
5. If evidence is missing or a payment is overdue, offer a support ticket with the selected IDs and dates attached.

Required additions beyond the current code:

- search pending payments across ID, order ID, and amount;
- aggregate several pending payments without pretending they form a Razorpay settlement batch;
- calculate count, gross selected amount, oldest capture, expected dates, overdue count, and eligibility breakdown;
- distinguish standard-cycle explanation from an actual Instant Settlement quote;
- support pending-payment tickets without requiring a settlement ID.

### 6.2 Understand a settlement

1. Find a settlement by ID, UTR, amount, date, or list selection.
2. Ask what the merchant wants:
   - Status and UTR
   - Why net is lower than gross
   - Fees and GST breakdown
   - Whether the settlement adds up
   - Why it needs attention
   - Bank did not receive it
   - What should I do next?
3. Reuse the existing preset, lookup, evidence, and triage functions.
4. Apply the existing triage verdict:
   - `NO_ISSUE`: explain that no confirmed issue exists.
   - `ALREADY_COMPENSATED`: cite the matched adjustment and close the path.
   - `AUTO_COMPENSABLE`: offer claim or support as two explicit choices.
   - `NEEDS_SUPPORT`: offer a prefilled support ticket only.
5. Require a button confirmation before a claim or ticket is created.

### 6.3 Get funds sooner

1. Ask how the requested amount should be calculated:
   - Enter an amount
   - Use the amount of one pending payment
   - Sum several pending payments
   - Request the maximum available balance
2. Explain that the operation is balance-based, not payment-specific.
3. Fetch or validate:
   - merchant Instant Settlement activation;
   - current available balance;
   - maximum daily withdrawable amount;
   - requested amount validity;
   - channel choice, expected timing, fees, tax, and net bank credit;
   - risk hold, KYC, and other blocking status when available.
4. Display a review screen with requested amount, fees plus tax, estimated net credit, timing, and the attribution warning.
5. Require explicit confirmation.
6. On execution, use an idempotency key and display Razorpay's returned on-demand settlement ID and status.
7. Poll or refresh the status as `created`, `initiated`, `partially_processed`, `processed`, or `reversed`.

For the current synthetic prototype, stop after the review screen and clearly label the result “Simulation.” A future production connector may call `POST /v1/settlements/ondemand`.

### 6.4 Fix or report an issue

Offer issue categories that map to the rules already present:

- Settlement failed
- Settlement amount does not match recon
- Fee or GST looks wrong
- Bank did not receive a processed settlement
- Expected settlement date has passed
- Instant Settlement is unavailable or failed
- Compensation/adjustment is missing or ambiguous
- Something else

Ask only for facts that are not already known. If a settlement or payment is currently selected on the main page, suggest it as the first choice but do not silently bind the assistant to it.

### 6.5 Ask something else

Keep the current free-text Q&A, but route through a universal context resolver first. The resolver can search both settlements and pending payments and ask one disambiguation question when several records match.

Do not preserve the current final fallback of treating every unknown question as “Where is this settlement?”. Unknown or out-of-scope questions should receive an honest scope message and the main menu or support option.

## 7. Coverage of current capabilities

| Capability | Existing reusable code | Universal guided destination | Gap |
|---|---|---|---|
| Settlement status and UTR | `answer_preset("where_is_settlement")` | Understand settlement | None |
| Net versus gross | `answer_preset("why_net_less")` | Understand settlement | None |
| Fee and GST breakdown | `answer_preset("breakdown_fees")` | Understand settlement | None |
| Settlement consistency | `answer_preset("is_consistent")` | Understand settlement | None |
| ID, UTR, amount, and date lookup | `SettlementEvidenceTools` and lookup parsers | Universal subject search | Extend across pending payments |
| Verified settlement | `TriageVerdict.NO_ISSUE` | Explain and resolution check | None |
| Already compensated | `ALREADY_COMPENSATED` | Explain matched adjustment | None |
| Clean provable shortfall | `AUTO_COMPENSABLE` | Claim or support choice | Preserve explicit consent |
| Failed/tax/multiple-control issue | `NEEDS_SUPPORT` | Prefilled support ticket | None for settlements |
| Ambiguous or unreconciled adjustment | `NEEDS_SUPPORT` reasons | Prefilled support ticket | Surface reason cleanly |
| Over-settlement | `OVER_SETTLEMENT_RECOVERY` | Support only | None |
| Bank non-receipt | `_bank_non_receipt_answer()` | Support only | None |
| Pending expected date | `answer_pending_query()` | Track pending payment | Fix working-day semantics |
| Pending instant eligibility | `answer_pending_query()` | Get funds sooner | Needs account-level quote data |
| Multiple/all pending summary | None | Track pending payment | New deterministic aggregator |
| Instant Settlement create/status | None | Get funds sooner | New connector or explicit simulation |
| Pending/account-level support ticket | None | Fix/report issue | Generalize ticket model |
| Satisfaction and handoff | None | Resolution checkpoint | New workflow states |

## 8. State and data model

Create one session state object instead of histories keyed independently by selected records.

```python
class AssistantMode(str, Enum):
    GUIDED = "guided"
    FREE_TEXT = "free_text"

class SubjectKind(str, Enum):
    NONE = "none"
    SETTLEMENT = "settlement"
    PENDING_PAYMENT = "pending_payment"
    PENDING_PAYMENT_SET = "pending_payment_set"
    ACCOUNT = "account"

class ActionKind(str, Enum):
    NONE = "none"
    RAISE_TICKET = "raise_ticket"
    SUBMIT_CLAIM = "submit_claim"
    VIEW_SETTLEMENT = "view_settlement"
    VIEW_PAYMENT = "view_payment"
    GET_INSTANT_SETTLEMENT_QUOTE = "get_instant_settlement_quote"
    CREATE_INSTANT_SETTLEMENT = "create_instant_settlement"
    TRACK_STATUS = "track_status"
    RETURN_TO_MENU = "return_to_menu"

class ResponseBlockKind(str, Enum):
    DETAILS = "details"
    CALCULATION = "calculation"
    EVIDENCE = "evidence"
    NEXT_STEP = "next_step"
    WARNING = "warning"

class AssistantResponseBlock(BaseModel):
    kind: ResponseBlockKind
    title: str | None = None
    body: str | None = None
    items: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)

class AssistantAction(BaseModel):
    action_id: str
    kind: ActionKind
    label: str
    style: Literal["primary", "secondary", "tertiary"] = "secondary"
    enabled: bool = True
    disabled_reason: str | None = None
    requires_confirmation: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)

class AssistantResponse(BaseModel):
    heading: str
    summary: str
    blocks: list[AssistantResponseBlock] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    actions: list[AssistantAction] = Field(default_factory=list)
    ask_resolution: bool = True

class AssistantSession(BaseModel):
    mode: AssistantMode = AssistantMode.GUIDED
    node_id: str = "home"
    back_stack: list[str] = Field(default_factory=list)
    subject_kind: SubjectKind = SubjectKind.NONE
    subject_ids: list[str] = Field(default_factory=list)
    intent: str | None = None
    pending_action: ActionKind = ActionKind.NONE
    action_quote_id: str | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)
    resolution_status: str = "open"
```

Store only identifiers in session state. Resolve current objects from the latest engine data on every action. This avoids executing against stale Pydantic objects after the reconciliation run is refreshed.

Model a user interaction as an event and a pure transition:

```python
transition(
    session: AssistantSession,
    event: AssistantEvent,
    data: AssistantDataContext,
) -> AssistantTransition
```

The transition returns the new state, structured assistant responses, guided choices, and visible typed actions. Several actions may be offered, but selecting one consequential action makes it the only pending proposal until it is confirmed, cancelled, or expires. This pure reducer is the main unit-test boundary and protects the app from Streamlit rerun bugs.

Keep the current `AnswerEnvelope.answer_text` as a compatibility fallback while migrating. Add a deterministic adapter that converts an envelope plus its subject and triage context into `AssistantResponse`. Do not parse the answer text to decide which action buttons to show. The answer producer or action resolver must attach actions from typed intent, eligibility, and outcome metadata.

## 9. Architecture

```text
apps/streamlit_app.py
  |-- settlement and pending-payment browse/detail UI
  |-- floating launcher + dialog host
  |
  +--> apps/universal_assistant.py
         |-- renders transcript, guided controls, and free-text composer
         |-- translates widget events into AssistantEvent
         |
         +--> src/agent/conversation.py
         |      |-- explicit state machine / transition reducer
         |      |-- subject resolution and guided routing
         |      +-- resolution checkpoint and handoff rules
         |
         +--> src/agent/responses.py
         |      |-- structured response adapter and block builder
         |      +-- deterministic contextual-action resolver
         |
         +--> src/agent/settlement_qa.py
         |      +-- existing settlement answers and safety intents
         |
         +--> src/agent/pending_qa.py
         |      +-- single and aggregate pending-payment answers
         |
         +--> src/agent/triage.py
         |      +-- existing deterministic settlement verdict
         |
         +--> src/actions/support.py
         |      +-- generalized ticket proposal and confirmation
         |
         +--> src/actions/instant_settlement.py
                +-- quote, confirm, create, fetch status

Deterministic rules and live account data
        |
        +--> answer/action proposal
                |
                +--> explicit merchant confirmation
                        |
                        +--> write connector with idempotency + audit event

LLM boundary:
  free text -> intent/entity extraction or phrasing only
  never -> financial calculation, eligibility decision, action confirmation, or write
```

The new assistant orchestrates existing capabilities. It does not replace `settlement_qa.py`, `triage.py`, or the control engine.

### 9.1 Where the actual AI model runs

The existing repository already has a real model gateway in `src/agent/llm_client.py`. When `USE_LLM=1` and at least one provider key is configured, `answer_free_text()` in `src/agent/settlement_qa.py` calls `_react_qa_llm()`. The configured order is Groq first, then Gemini, then OpenRouter, using their OpenAI-compatible APIs. If all configured providers fail, the request falls back to the deterministic answer path.

The universal assistant should keep that provider gateway and place it in this explicit free-text pipeline:

```text
Merchant types a free-text message
        |
        v
Deterministic safety and command router
  |-- greeting/navigation/support command -> deterministic transition
  |-- claim/ticket/money-movement intent -> deterministic proposal flow
  +-- ordinary question -> continue
        |
        v
Context builder resolves merchant, active subject, IDs, and candidate evidence
        |
        v
AI model through Groq -> Gemini -> OpenRouter provider gateway
  |-- understands conversational wording and ambiguous intent
  |-- selects only allowlisted read-only evidence tools when more data is needed
  +-- drafts a concise structured explanation with citations
        |
        v
Server-side citation, money, policy, and eligibility validators
  |-- invalid output -> repair once or deterministic fallback
  +-- valid output -> continue
        |
        v
Deterministic contextual-action resolver attaches buttons
        |
        v
Structured response renderer
```

The model is therefore used for the genuinely conversational part:

- understanding free-form and follow-up questions that do not match an exact menu label;
- resolving references such as “that payment,” using the controlled conversation context;
- choosing from allowlisted read-only settlement/payment evidence tools;
- turning verified tool results into a clear heading, summary, details, evidence explanation, and next-step text;
- optionally producing a concise conversation summary for the ticket preview, with the original question and evidence retained separately.

The model is not used to:

- calculate fees, GST, settlement totals, expected dates, or claim amounts;
- decide reconciliation status, claim eligibility, or Instant Settlement eligibility;
- decide whether an action button is enabled;
- confirm consent or execute a ticket, claim, or settlement request;
- invent missing facts when no tool evidence is available.

Guided button navigation is deterministic and normally does not need a model call. This keeps it fast and repeatable. The AI remains available through the free-text composer at every guided step, and can explain a guided result in more natural language when requested. The UI should expose answer provenance as **AI explanation** or **Rules answer**, including the provider/model in a diagnostic detail rather than presenting deterministic output as model-generated.

For structured AI output, replace the current flat `finish_answer(answer_text, citations, ...)` tool with a versioned `finish_structured_answer` schema matching `AssistantResponse`. Treat model-produced actions as suggestions only: discard them and run the deterministic action resolver after response validation.

## 10. Routing order for free text

Use this order so safety-sensitive requests cannot be swallowed by a generic LLM answer:

1. Validate and sanitize input.
2. Detect greetings, navigation commands, cancellation, and direct requests for support.
3. Detect consequential intents: claim, ticket, or Instant Settlement.
4. Resolve explicitly mentioned settlement/payment/UTR/order identifiers.
5. Search exact date and amount matches across both settled and pending datasets.
6. Apply the active guided context if it is still compatible.
7. Ask for disambiguation when two or more subjects are plausible.
8. Run existing deterministic or tool-backed answer functions.
9. Use the LLM only where permitted for remaining free-text understanding or phrasing.
10. Convert the result into structured blocks and attach contextual actions from typed outcome metadata.
11. Validate citations, every money figure, and action eligibility before displaying the answer.

Any typed message may interrupt a guided path. The router should answer it, update the subject context when confidently resolved, and then offer either “Continue previous flow” or “Main menu.”

## 11. Consequential action protocol

Claims, tickets, and Instant Settlements follow the same protocol:

```text
Collect subject and intent
  -> recompute current eligibility/evidence
  -> create immutable proposal/quote
  -> show exact consequence
  -> explicit confirm button
  -> revalidate proposal and evidence version
  -> execute once with idempotency key
  -> show result ID and status
```

Rules:

- Never treat a bare “yes” as consent when more than one action is offered.
- Never execute from an LLM tool choice.
- Never reuse a quote after balance, limits, evidence, or settlement status changes.
- Disable or replace the confirmation button after successful submission.
- A rerun, double click, or rephrased request must not create a duplicate ticket, claim, or Instant Settlement.
- Persist real production actions outside `st.session_state`; session-only dictionaries are acceptable only for a clearly labeled demo.

## 12. Support handoff contract

Generalize the current settlement-only support response into a typed ticket proposal:

```python
class SupportTicketProposal(BaseModel):
    category: str
    subject_kind: SubjectKind
    subject_ids: list[str] = Field(default_factory=list)
    merchant_summary: str
    deterministic_findings: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_details: list[CheckCalculationDetail] = Field(default_factory=list)
    conversation_summary: str
    evidence_hash: str
    routing_team: str
```

The preview should show what will be sent. On confirmation, return a stable ticket ID and expected response channel/time if known.

The handoff should include:

- the merchant's unresolved question in their own words;
- selected payment or settlement identifiers;
- known status, amount, UTR, dates, and eligibility facts;
- failed control calculations when they exist;
- what the assistant already tried;
- explicit missing evidence, such as bank credit status;
- no secret keys and no unnecessary full transcript.

## 13. UI changes to existing sections

### Settlements section

Keep:

- list/filter;
- amount, date, UTR, and integrity status;
- deterministic checks;
- payment breakdown;
- claim/ticket status when an action already exists.

Remove:

- the embedded `render_settlement_chatbot()` card;
- duplicate claim and ticket action buttons that are only invitations to start support. Existing action status may remain visible, while new actions begin in the universal assistant.

Add:

- a small “Ask about this settlement” secondary action that opens the universal assistant with the settlement suggested, not silently selected;
- the persistent launcher.

### Unsettled payments section

Keep:

- pending-payment list;
- amount, capture date, expected date, method, and known eligibility.

Remove:

- `render_pending_payment_chatbot()`.

Add:

- “Ask about this payment” and “Get funds sooner” shortcuts that open the same assistant;
- multi-selection only if the main browse experience benefits from it. Multi-selection is always available inside the guided assistant.

## 14. Approaches considered

### A. Add menus to both current chatbots

**Effort:** Small  
**Risk:** Medium

Pros:

- fastest visible demo;
- minimal initial refactor.

Cons:

- duplicates workflow state and UI again;
- cannot answer account-level or cross-record questions cleanly;
- conflicts with the goal of one company-style support assistant;
- makes future ticket and action logic drift between two renderers.

**Decision:** Reject.

### B. One universal assistant with an explicit state machine

**Effort:** Medium  
**Risk:** Low to medium

Pros:

- one transcript, one action boundary, and one routing model;
- deterministic guided paths are easy to test;
- reuses current evidence and triage functions;
- free text remains flexible without controlling financial actions.

Cons:

- requires a deliberate context model and UI refactor;
- Streamlit dialog and fixed-launcher behavior need a short spike.

**Decision:** Recommended.

### C. Let an LLM plan every conversation and action

**Effort:** Medium to large  
**Risk:** High

Pros:

- fewer manually declared conversation nodes;
- flexible for unanticipated wording.

Cons:

- difficult to prove action safety and complete rule coverage;
- inconsistent UX and higher latency/cost;
- creates unacceptable ambiguity around claims, tickets, and money movement.

**Decision:** Reject for action orchestration. Use the LLM only inside the bounded free-text path.

## 15. Implementation sequence

### Phase 1: Universal shell and consolidation

1. Add the fixed launcher and native dialog spike.
2. Create `AssistantSession`, event, transition, structured-response, and typed-action models.
3. Add the generic structured response renderer and stable action event wiring.
4. Move conversation rendering from `apps/streamlit_app.py` into `apps/universal_assistant.py`.
5. Render one welcome message, main menu, transcript, guided escape controls, and persistent free-text composer.
6. Remove both embedded chatbot cards.
7. Preserve settlement and pending-payment browse/detail behavior.

**Exit:** One assistant opens from every section, answers render as structured sections with typed buttons, and changing the browse view does not lose the conversation.

### Phase 2: Guided read-only resolution

1. Implement explicit nodes for the four main paths.
2. Add universal settlement and pending-payment subject search.
3. Reuse all current settlement preset, lookup, and triage answers.
4. Move pending answers into a dedicated module and add multi/all aggregation.
5. Route ordinary free text through the existing provider gateway and a versioned structured-answer schema.
6. Add the deterministic action resolver for view, quote, claim, ticket, tracking, and navigation functionality.
7. Add resolution checkpoints, Back, Main menu, and direct support escape.
8. Keep the free-text composer active on every node.

**Exit:** Every existing read-only rule has a guided entry point and a free-text entry point.

### Phase 3: Generalized ticket handoff

1. Add `SupportTicketProposal` and deterministic routing categories.
2. Support settlement, pending-payment, multi-payment, and account-level tickets.
3. Generate a concise evidence-backed handoff summary.
4. Require preview and confirmation.
5. Make ticket creation idempotent and persist status appropriately for demo or production.

**Exit:** An unresolved merchant can reach support from any path without re-entering known details.

### Phase 4: Instant Settlement workflow

1. Implement deterministic amount aggregation and the payment-attribution warning.
2. Add account-level eligibility, balance, limit, fee/tax quote, and status models.
3. Build the review and confirmation flow.
4. Initially return a clearly labeled simulated result.
5. Add the real Razorpay connector only when credentials, entitlement, failure handling, audit storage, and idempotency are available.

**Exit:** The flow is truthful in demo mode and production-safe when a real connector is enabled.

### Phase 5: Analytics, documentation, and polish

1. Track menu selection, resolution, abandonment, fallback, support escalation, and duplicate-prevention events without storing raw sensitive messages.
2. Update README, architecture, security, limitations, and demo script.
3. Add keyboard, focus, mobile, long-label, empty-data, and provider-failure checks.
4. Remove obsolete chatbot CSS and helpers after no imports remain.

## 16. File-level change plan

| File | Planned change |
|---|---|
| `apps/streamlit_app.py` | Keep browse/detail page; host launcher/dialog; remove embedded chatbot render calls and obsolete helpers |
| `apps/universal_assistant.py` | New native Streamlit conversation UI and event wiring |
| `src/domain/models.py` | Add assistant session, event, subject, structured response/block, typed action, ticket, and optional Instant Settlement models |
| `src/agent/llm_client.py` | Retain the Groq/Gemini/OpenRouter gateway and expose provider/model provenance to the universal assistant |
| `src/agent/conversation.py` | New pure state transition engine and universal router |
| `src/agent/responses.py` | Convert answer envelopes into structured blocks and resolve contextual actions from typed outcomes and eligibility |
| `src/agent/settlement_qa.py` | Preserve settlement logic and the bounded model loop; migrate its flat final-answer tool to the structured response contract |
| `src/agent/pending_qa.py` | Move single pending answer logic; add deterministic multi-payment summaries and search |
| `src/agent/evidence.py` | Add universal subject lookup across settlement and pending sources without weakening allowlists |
| `src/actions/support.py` | Generalized ticket proposal, evidence package, confirmation, and idempotent create |
| `src/actions/instant_settlement.py` | Quote/create/status interface with simulated and future real implementations |
| `tests/test_conversation.py` | State-transition, interruption, navigation, greeting, and resolution tests |
| `tests/test_pending_qa.py` | Search and one/many/all pending-payment aggregation tests |
| `tests/test_support_actions.py` | Handoff payload, consent, idempotency, and routing tests |
| `tests/test_instant_settlement.py` | Amount semantics, quote expiry, limits, confirmation, duplicate, and status tests |
| `tests/test_streamlit_app.py` | Streamlit AppTest coverage for launcher, dialog entry, and removal of embedded bots where feasible |

## 17. Test plan

### Conversation transitions

- Opening the assistant shows the main menu without requiring a typed greeting.
- “Hi”, “hello”, and similar greetings show the menu when no action is pending.
- A greeting during a pending action does not silently discard the action.
- Back and Main menu produce deterministic states.
- A button choice appears in transcript history.
- Free text works from every guided node.
- Free text can change subject after explicit disambiguation.
- Direct support requests never enter a repeated self-service loop.

### Subject resolution

- Exact settlement ID and UTR select one settlement.
- Exact payment/order ID selects one pending payment.
- Amount/date matches with several candidates ask for selection.
- Unknown identifiers abstain and offer search/support.
- Main-page selection is suggested but never silently treated as user confirmation.

### Rule coverage

- Preserve every current settlement Q&A, triage, compensation, bank non-receipt, citation, money-validation, and injection test.
- Add a guided path assertion for every `TriageVerdict` and `TriageReason`.
- Add pending on-time, overdue, instant yes/no/unknown, missing-date, multi-payment, and empty-set cases.
- Replace the current calendar-day language with policy-correct working-day behavior before presenting dates as Razorpay expectations.

### Action safety

- No write occurs before a dedicated confirm-button event.
- A bare “yes” with multiple offered actions asks which action.
- Stale evidence or quote blocks execution and requests review again.
- Double click, rerun, browser refresh, and rephrased request do not duplicate an action.
- The LLM cannot directly produce an executable action.
- Claim eligibility is recomputed immediately before submission.
- Ticket payload excludes secrets and contains only relevant evidence.

### Structured responses and contextual actions

- Every substantive result has a non-empty outcome heading and direct summary.
- Blocks render in the defined order and omit empty sections.
- Calculations use labeled values or rows instead of being buried in prose.
- A direct free-text request to raise a ticket returns a **Raise ticket** action without creating a ticket.
- Every unresolved, abstained, and bank-non-receipt response includes **Raise ticket**.
- An `AUTO_COMPENSABLE` response offers **Submit claim** and **Raise ticket**; a `NO_ISSUE` response never offers a claim.
- Settlement and pending-payment answers expose their matching view action when the subject is known.
- Quote/create buttons appear only when required account data and eligibility checks are available.
- Every guided node exposes Main menu and Talk to support; Back appears whenever history exists.
- Stable action IDs and widget keys prevent duplicate clicks across Streamlit reruns.
- Action selection is driven by typed metadata, never by scanning generated answer prose.

### AI-model boundary and fallback

- With `USE_LLM=1` and a configured provider, an ordinary free-text question invokes the provider gateway and records provider/model provenance.
- Model tool calls are restricted to the read-only allowlist.
- Valid structured model output renders with verified citations and an **AI explanation** provenance label.
- Invalid citations, unverified amounts, malformed structure, timeout, or provider failure produces a visible deterministic fallback, never an unvalidated partial answer.
- Guided navigation, support commands, and consequential intents do not depend on model availability.
- Any model-suggested action is discarded; the deterministic resolver reconstructs allowed actions from trusted state.

### Instant Settlement semantics

- One or many selected payments produce an amount proposal, not a payment-specific promise.
- “All unsettled payments” and “full available balance” are distinct options.
- Limits and insufficient balance block confirmation.
- Fees and tax are shown before confirmation.
- Simulation is unmistakably labeled.
- Every returned Razorpay status is rendered, including partial and reversed outcomes.

### UI and accessibility

- Launcher is reachable by keyboard, has a readable accessible name, and does not cover key content.
- Dialog focus starts in the assistant and returns to the launcher on close.
- Composer remains visible at every node.
- Structured answer sections remain readable and action buttons wrap or stack cleanly on narrow screens.
- Guided escape controls remain available without being confused with result-specific actions.
- Long IDs and long option labels wrap without clipping.
- Mobile layout remains usable at 320-pixel width.
- Switching Settlements/Unsettled Payments does not reset the assistant.
- No embedded chatbot remains in either detail section.

## 18. Success measures

Track separately for guided and free-text sessions:

- self-service resolution rate;
- support escalation rate;
- median steps to resolution;
- abandonment by workflow node;
- percentage of free-text questions resolved without disambiguation;
- fallback/abstention rate;
- ticket completeness rate;
- contextual-action click-through and completion rate;
- structured-response contract violations, target zero;
- duplicate action rate, target zero;
- unverified money figures emitted, target zero;
- actions executed without explicit confirmation, target zero.

Initial product targets for the prototype:

- at least 90% of existing labeled Q&A cases remain reachable and correct through the universal router;
- 100% of existing deterministic triage outcomes have a guided path;
- a merchant reaches any primary answer in no more than three guided choices after subject selection;
- an unresolved merchant reaches the ticket preview in no more than two additional choices;
- no regression in the current settlement Q&A, triage, reconciliation, or money-safety tests.

## 19. Main risks and mitigations

| Risk | Mitigation |
|---|---|
| Guided flow becomes a large brittle tree | Keep nodes explicit and outcome-focused; reuse subflows for subject selection, resolution check, and handoff |
| Free text and button state diverge | Convert both to the same `AssistantEvent` and transition reducer |
| Generated prose mentions an action but no button appears | Attach actions from typed outcome metadata and enforce the response contract in tests |
| Too many buttons overwhelm the answer | Rank result-specific actions and show at most two or three; keep navigation in a separate escape area |
| Assistant acts on the wrong record | Require disambiguation and confirmation; resolve objects fresh by ID |
| Merchant believes selected payments are specifically settled | Show the amount-based attribution warning before quote and confirmation |
| Streamlit reruns duplicate writes | Immutable proposals, evidence versions, server-side idempotency keys, and persistent action records |
| Dialog launcher CSS breaks after upgrade | Scope CSS to a widget key, cover in UI smoke test, keep a native in-flow fallback |
| Ticket reaches support without useful context | Typed proposal with evidence, calculations, missing-data statement, and conversation summary |
| Bot blocks access to a person | Global Talk to support escape and negative-feedback handoff |
| Session state is mistaken for persistence | Clearly separate demo stores from production repositories in interfaces and UI labels |

## 20. Acceptance criteria

- [ ] Exactly one user-facing chatbot exists.
- [ ] It is accessible from a persistent bottom-right launcher.
- [ ] Opening it or typing a greeting displays the guided menu.
- [ ] Free text remains available during every guided step.
- [ ] Settlement and pending-payment pages contain no embedded chatbot.
- [ ] All existing deterministic settlement capabilities are reachable.
- [ ] Pending-payment one/many/all summaries are supported.
- [ ] Multiple/all selection never claims payment-specific Instant Settlement attribution.
- [ ] Every answer cites loaded evidence or abstains.
- [ ] Every substantive answer uses the structured heading, summary, details/evidence, next-step, and action contract while omitting empty sections.
- [ ] Relevant functionality is exposed as a typed button in free-text and guided results.
- [ ] Every guided node provides Main menu and Talk to support; unresolved results provide Raise ticket.
- [ ] Clicking an action proposal never performs a consequential write until a separate review and confirmation.
- [ ] With AI enabled, an ordinary free-text question demonstrably invokes a configured model and shows validated answer provenance.
- [ ] With AI unavailable or its output rejected, the same conversation remains usable through the deterministic fallback.
- [ ] Every claim, ticket, or Instant Settlement has review plus explicit confirmation.
- [ ] Any unresolved path can reach a prefilled ticket.
- [ ] Tickets, claims, and settlement requests are idempotent.
- [ ] Existing tests pass and the new transition/action/UI tests pass.

## 21. External product patterns used

- Intercom workflows combine reply buttons with an open composer, allow AI to take over when a customer types, collect more information before handoff, and trigger handoff from direct human requests or negative feedback.
- Zendesk recommends greeting, self-service, a mapped conversation flow, an explicit “was this resolved?” step, and a planned transfer path that passes collected fields into the ticket.
- Razorpay documents standard settlement cycles, Instant Settlement prerequisites and limits, and amount/full-balance semantics for on-demand settlement creation.

References:

- https://www.intercom.com/help/en/articles/10032299-use-fin-ai-agent-in-workflows
- https://www.intercom.com/help/en/articles/7836459-workflows-explained
- https://support.zendesk.com/hc/en-us/articles/5746068733338-Designing-your-conversational-messaging-workflow
- https://support.zendesk.com/hc/en-us/articles/10412442245914-Workflow-recipe-Using-an-AI-agent-to-collect-customer-info-and-immediately-escalate-to-a-human-agent
- https://razorpay.com/docs/payments/settlements/
- https://razorpay.com/docs/payments/settlements/instant/
- https://razorpay.com/docs/api/settlements/instant/create/
