"""Bounded action execution — journal posting into demo ledger."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from uuid import uuid4

from src.domain.accounts import JOURNAL_TEMPLATES
from src.domain.models import (
    Approval,
    AuditEvent,
    InvestigationCase,
    LedgerEntry,
    ProposedAction,
    SettlementBatch,
)


class DemoLedger:
    """In-memory versioned demo ledger."""

    def __init__(self, entries: list[LedgerEntry] | None = None):
        self.entries: list[LedgerEntry] = list(entries or [])
        self.version: int = 1
        self.posted_actions: set[str] = set()

    def copy(self) -> "DemoLedger":
        ledger = DemoLedger(self.entries)
        ledger.version = self.version
        ledger.posted_actions = set(self.posted_actions)
        return ledger

    def entries_for_settlement(self, settlement_id: str) -> list[LedgerEntry]:
        return [e for e in self.entries if e.settlement_id == settlement_id]

    def evidence_hash(self, settlement_id: str) -> str:
        related = self.entries_for_settlement(settlement_id)
        payload = json.dumps([e.model_dump(mode="json") for e in related], sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def propose_missing_fee_journal(
    batch: SettlementBatch,
    case: InvestigationCase,
) -> ProposedAction:
    total_fee = sum(l.fee for l in batch.lines if l.line_type == "payment")
    total_tax = sum(l.tax for l in batch.lines if l.line_type == "payment")
    fee_expense = total_fee - total_tax

    journal_lines = []
    if fee_expense > 0:
        journal_lines.append(
            {"account_code": "4100", "account_name": "Gateway Fee Expense", "debit": fee_expense, "credit": 0}
        )
    if total_tax > 0:
        journal_lines.append(
            {"account_code": "4110", "account_name": "Fee Tax Suspense", "debit": total_tax, "credit": 0}
        )
    journal_lines.append(
        {"account_code": "1200", "account_name": "Gateway Clearing", "debit": 0, "credit": total_fee}
    )

    tmpl = JOURNAL_TEMPLATES["missing_fee_posting"]
    return ProposedAction(
        action_type="post_journal",
        template_id=tmpl.template_id,
        settlement_id=batch.settlement_id,
        description=f"Post missing fee journal: {total_fee} paise (fee {fee_expense} + tax {total_tax})",
        journal_lines=journal_lines,
        amount_paise=total_fee,
    )


def execute_approved_journal(
    ledger: DemoLedger,
    action: ProposedAction,
    approval: Approval,
    posting_date: date | None = None,
) -> tuple[list[LedgerEntry], AuditEvent | None]:
    """Post journal once with idempotency."""
    if not approval.approved:
        return [], None

    if action.action_id in ledger.posted_actions:
        return [], AuditEvent(
            run_id="",
            event_type="action_duplicate_blocked",
            payload={"action_id": action.action_id},
        )

    if approval.evidence_hash and action.settlement_id:
        current_hash = ledger.evidence_hash(action.settlement_id)
        if approval.evidence_hash != current_hash:
            return [], AuditEvent(
                run_id="",
                event_type="action_stale_blocked",
                payload={"expected": approval.evidence_hash, "current": current_hash},
            )

    posting_date = posting_date or date.today()
    journal_id = f"corr_{action.action_id[:8]}"
    new_entries: list[LedgerEntry] = []

    for i, line in enumerate(action.journal_lines):
        new_entries.append(
            LedgerEntry(
                entry_id=f"{journal_id}_{i}",
                journal_id=journal_id,
                posting_date=posting_date,
                account_code=line["account_code"],
                account_name=line.get("account_name", ""),
                debit=line.get("debit", 0),
                credit=line.get("credit", 0),
                settlement_id=action.settlement_id,
                reference=f"correction:{action.template_id}",
                memo=action.description,
            )
        )

    ledger.entries.extend(new_entries)
    ledger.posted_actions.add(action.action_id)
    ledger.version += 1

    audit = AuditEvent(
        run_id="",
        event_type="journal_posted",
        actor=approval.approver,
        payload={
            "action_id": action.action_id,
            "journal_id": journal_id,
            "settlement_id": action.settlement_id,
            "lines": len(new_entries),
            "ledger_version": ledger.version,
        },
    )
    return new_entries, audit
