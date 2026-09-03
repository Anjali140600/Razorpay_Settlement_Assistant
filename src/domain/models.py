"""Canonical domain models — all amounts in paise (integer)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ExceptionCode(str, Enum):
    SOURCE_INCOMPLETE = "SOURCE_INCOMPLETE"
    SETTLEMENT_TOTAL_MISMATCH = "SETTLEMENT_TOTAL_MISMATCH"
    PROCESSED_AWAITING_BANK = "PROCESSED_AWAITING_BANK"
    MISSING_BANK_CREDIT = "MISSING_BANK_CREDIT"
    BANK_REFERENCE_AMBIGUOUS = "BANK_REFERENCE_AMBIGUOUS"
    BANK_AMOUNT_MISMATCH = "BANK_AMOUNT_MISMATCH"
    LEDGER_ENTRY_MISSING = "LEDGER_ENTRY_MISSING"
    FEE_OR_TAX_MISPOSTED = "FEE_OR_TAX_MISPOSTED"
    SETTLEMENT_FAILED = "SETTLEMENT_FAILED"
    UNSUPPORTED_LINE_SEMANTICS = "UNSUPPORTED_LINE_SEMANTICS"


class ControlStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"
    REVIEW = "REVIEW"
    ESCALATED = "ESCALATED"


class SettlementStatus(str, Enum):
    PROVEN = "PROVEN"
    PENDING_BANK_WITHIN_POLICY = "PENDING_BANK_WITHIN_POLICY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    ESCALATED = "ESCALATED"
    UNRESOLVED = "UNRESOLVED"


class SettlementIntegrityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class CaseOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    PENDING_EVIDENCE = "PENDING_EVIDENCE"
    ESCALATED = "ESCALATED"
    UNRESOLVED = "UNRESOLVED"


class SettlementLine(BaseModel):
    entity_id: str
    line_type: str  # payment, refund, transfer, adjustment
    debit: int = 0
    credit: int = 0
    amount: int
    fee: int = 0
    tax: int = 0
    currency: str = "INR"
    settlement_id: str
    payment_id: str | None = None
    order_id: str | None = None
    created_at: datetime | None = None
    settled_at: datetime | None = None
    description: str = ""
    # Razorpay adjustments that correct an earlier cycle name the settlement they
    # compensate. Without an exact reference, amount plus timing alone would bind the
    # wrong exception — which is how a matcher silently corrupts a financial record.
    reference_settlement_id: str | None = None


class PendingPayment(BaseModel):
    """A payment that has been captured but has no settlement yet.

    Deliberately separate from SettlementLine: it has no batch, no UTR, no
    fee/tax lines, and no triage verdict — it is a different shape of fact,
    not a SettlementLine with fields missing.
    """

    entity_id: str
    order_id: str | None = None
    amount: int  # paise
    currency: str = "INR"
    method: str | None = None
    captured_at: datetime
    cycle_type: str = "standard"  # "standard" | "instant_eligible"
    instant_eligible: str = "unknown"  # "yes" | "no" | "unknown" — never inferred, always read from source data
    expected_settlement_at: date | None = None


class SettlementBatch(BaseModel):
    settlement_id: str
    amount: int  # net settlement in paise
    utr: str = ""
    status: str = "processed"  # created, processed, failed
    processed_at: datetime | None = None
    lines: list[SettlementLine] = Field(default_factory=list)

    @property
    def net_from_lines(self) -> int:
        return sum(l.credit for l in self.lines) - sum(l.debit for l in self.lines)


class BankEntry(BaseModel):
    entry_id: str
    value_date: date
    amount: int  # credit positive
    narration: str
    utr: str = ""
    currency: str = "INR"
    running_balance: int | None = None


class LedgerEntry(BaseModel):
    entry_id: str
    journal_id: str
    posting_date: date
    account_code: str
    account_name: str
    debit: int = 0
    credit: int = 0
    settlement_id: str | None = None
    reference: str = ""
    memo: str = ""


class SourceSnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: str
    record_count: int
    total_amount_paise: int | None = None
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    complete: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CheckCalculationDetail(BaseModel):
    check_name: str
    formula: str
    expected_display: str
    actual_display: str
    delta_display: str | None = None
    line_id: str | None = None
    error: str


class ControlDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    settlement_id: str | None = None
    control_type: str  # batch_integrity, tax_lines, bank_receipt, gl_posting
    status: ControlStatus
    exception_code: ExceptionCode | None = None
    message: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    auto_closed: bool = False
    calculation_detail: CheckCalculationDetail | None = None


class SettlementCloseDecision(BaseModel):
    settlement_id: str
    status: SettlementStatus
    integrity_status: SettlementIntegrityStatus = SettlementIntegrityStatus.NEEDS_ATTENTION
    batch_integrity: ControlStatus
    tax_lines: ControlStatus = ControlStatus.PASS
    bank_receipt: ControlStatus = ControlStatus.PASS
    gl_posting: ControlStatus = ControlStatus.PASS
    net_amount_paise: int
    utr: str = ""
    processed_at: datetime | None = None
    bank_entry_id: str | None = None
    control_decisions: list[ControlDecision] = Field(default_factory=list)
    plain_issue: str = ""


class AnswerEnvelope(BaseModel):
    answer_text: str
    citations: list[str] = Field(default_factory=list)
    abstained: bool = False
    escalated_to_support: bool = False
    offer_raise_ticket: bool = False
    support_ticket_id: str | None = None
    settlement_id: str | None = None
    tool_trace: list[str] = Field(default_factory=list)
    agent_mode: str = "keyword"
    # Query triage — set whenever a settlement-scoped answer was classified.
    triage_verdict: str = ""
    offer_compensation: bool = False
    compensation_amount_display: str | None = None
    compensation_claim_id: str | None = None


class CompensationClaim(BaseModel):
    """A merchant-consented claim for a provable shortfall, filed to Razorpay support.

    Never a ledger write and never automatic — the agent can only reach this after an
    explicit consent turn on an AUTO_COMPENSABLE triage verdict.
    """

    claim_id: str
    settlement_id: str
    exception_id: str
    amount_paise: int
    evidence_hash: str
    citations: list[str] = Field(default_factory=list)


class ProposedAction(BaseModel):
    action_id: str = Field(default_factory=lambda: str(uuid4()))
    action_type: str  # post_journal, escalate, recheck
    template_id: str | None = None
    settlement_id: str | None = None
    description: str = ""
    journal_lines: list[dict[str, Any]] = Field(default_factory=list)
    amount_paise: int = 0


class PredictedHypothesis(BaseModel):
    hypothesis_id: str = Field(default_factory=lambda: str(uuid4()))
    summary: str
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    sufficient_evidence: bool = False
    tool_trace: list[str] = Field(default_factory=list)


class InvestigationCase(BaseModel):
    case_id: str = Field(default_factory=lambda: str(uuid4()))
    settlement_id: str | None = None
    exception_codes: list[ExceptionCode] = Field(default_factory=list)
    control_decisions: list[ControlDecision] = Field(default_factory=list)
    hypothesis: PredictedHypothesis | None = None
    proposed_action: ProposedAction | None = None
    outcome: CaseOutcome = CaseOutcome.UNRESOLVED
    bank_candidates: list[dict[str, Any]] = Field(default_factory=list)


class Approval(BaseModel):
    approval_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str
    action_id: str
    approver: str = "demo_approver"
    approved: bool = False
    comment: str = ""
    evidence_hash: str = ""
    approved_at: datetime | None = None


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    event_type: str
    actor: str = "system"
    payload: dict[str, Any] = Field(default_factory=dict)


class ReconciliationRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    cutoff_date: date
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    settlement_decisions: list[SettlementCloseDecision] = Field(default_factory=list)
    investigation_cases: list[InvestigationCase] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    runtime_seconds: float = 0.0


def paise_to_inr(paise: int) -> Decimal:
    return Decimal(paise) / Decimal(100)


def inr_to_paise(inr: float | Decimal) -> int:
    return int(Decimal(str(inr)) * 100)
