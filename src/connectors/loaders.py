"""Source connectors for Razorpay recon, settlements, bank, and GL."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from dateutil import parser as date_parser

from src.domain.models import BankEntry, LedgerEntry, PendingPayment, SettlementBatch, SettlementLine


def _parse_dt(value: str | int | float | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.utcfromtimestamp(value)
    return date_parser.parse(str(value))


def _parse_date(value: str | None) -> date | None:
    dt = _parse_dt(value)
    return dt.date() if dt else None


def load_recon_json(path: Path) -> list[SettlementLine]:
    """Load Razorpay combined settlement-recon API-shaped JSON."""
    data = json.loads(path.read_text())
    items = data.get("items", data) if isinstance(data, dict) else data
    lines: list[SettlementLine] = []
    for row in items:
        lines.append(
            SettlementLine(
                entity_id=str(row.get("entity_id", row.get("id", ""))),
                line_type=str(row.get("type", "payment")),
                debit=int(row.get("debit", 0)),
                credit=int(row.get("credit", 0)),
                amount=int(row.get("amount", 0)),
                fee=int(row.get("fee", 0)),
                tax=int(row.get("tax", 0)),
                currency=str(row.get("currency", "INR")),
                settlement_id=str(row.get("settlement_id", "")),
                payment_id=row.get("payment_id"),
                order_id=row.get("order_id"),
                created_at=_parse_dt(row.get("created_at")),
                settled_at=_parse_dt(row.get("settled_at")),
                description=str(row.get("description", "")),
                reference_settlement_id=row.get("reference_settlement_id"),
            )
        )
    return lines


def load_settlements_json(path: Path) -> list[SettlementBatch]:
    """Load settlement headers and attach recon lines."""
    data = json.loads(path.read_text())
    headers = data.get("items", data) if isinstance(data, dict) else data
    batches: list[SettlementBatch] = []
    for row in headers:
        batches.append(
            SettlementBatch(
                settlement_id=str(row.get("id", row.get("settlement_id", ""))),
                amount=int(row.get("amount", 0)),
                utr=str(row.get("utr", "")),
                status=str(row.get("status", "processed")),
                processed_at=_parse_dt(row.get("processed_at") or row.get("created_at")),
                lines=[],
            )
        )
    return batches


def attach_lines_to_batches(
    batches: list[SettlementBatch], lines: list[SettlementLine]
) -> list[SettlementBatch]:
    by_id = {b.settlement_id: b for b in batches}
    for line in lines:
        if line.settlement_id in by_id:
            by_id[line.settlement_id].lines.append(line)
    return list(by_id.values())


def load_pending_payments(recon_path: Path, manifest_path: Path) -> list[PendingPayment]:
    """Load captured-but-unsettled payments — recon rows with no settlement_id yet.

    Kept separate from load_recon_json/attach_lines_to_batches: those two only ever
    handle lines that already belong to a settlement, and a pending payment has no
    batch, UTR, or fee/tax lines to attach.
    """
    data = json.loads(recon_path.read_text())
    items = data.get("items", data) if isinstance(data, dict) else data

    standard_days = 2
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        standard_days = manifest.get("settlement_cycle", {}).get("standard_days", 2)

    pending: list[PendingPayment] = []
    for row in items:
        if row.get("settlement_id"):
            continue
        captured_at = _parse_dt(row.get("captured_at") or row.get("created_at"))
        if captured_at is None:
            continue
        pending.append(
            PendingPayment(
                entity_id=str(row.get("entity_id", "")),
                order_id=row.get("order_id"),
                amount=int(row.get("amount", 0)),
                currency=str(row.get("currency", "INR")),
                method=row.get("method"),
                captured_at=captured_at,
                cycle_type=str(row.get("cycle_type", "standard")),
                instant_eligible=str(row.get("instant_eligible", "unknown")),
                expected_settlement_at=captured_at.date() + timedelta(days=standard_days),
            )
        )
    return pending


def load_bank_csv(path: Path) -> list[BankEntry]:
    if not path.exists():
        return []
    entries: list[BankEntry] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            amount_raw = row.get("amount", row.get("credit", "0"))
            amount = int(float(amount_raw) * 100) if "." in str(amount_raw) else int(amount_raw)
            narration = row.get("narration", row.get("description", ""))
            utr = row.get("utr", "") or _extract_utr_from_narration(narration)
            entries.append(
                BankEntry(
                    entry_id=row.get("entry_id", f"bank_{i}"),
                    value_date=_parse_date(row.get("value_date", row.get("date"))) or date.today(),
                    amount=amount,
                    narration=narration,
                    utr=utr,
                    running_balance=int(row["running_balance"]) if row.get("running_balance") else None,
                )
            )
    return entries


def _extract_utr_from_narration(narration: str) -> str:
    """Best-effort UTR extraction from bank narration."""
    import re

    # Common UTR patterns: 12-22 alphanumeric
    patterns = [
        r"UTR[:\s]*([A-Z0-9]{12,22})",
        r"NEFT[:\s/]*([A-Z0-9]{12,22})",
        r"IMPS[:\s/]*([A-Z0-9]{12,22})",
        r"REF[:\s]*([A-Z0-9]{12,22})",
        r"\b([A-Z0-9]{16,22})\b",
    ]
    upper = narration.upper()
    for pat in patterns:
        m = re.search(pat, upper)
        if m:
            return m.group(1)
    return ""


def load_gl_csv(path: Path) -> list[LedgerEntry]:
    if not path.exists():
        return []
    entries: list[LedgerEntry] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            debit_raw = row.get("debit", "0")
            credit_raw = row.get("credit", "0")
            debit = int(float(debit_raw) * 100) if "." in str(debit_raw) else int(debit_raw or 0)
            credit = int(float(credit_raw) * 100) if "." in str(credit_raw) else int(credit_raw or 0)
            entries.append(
                LedgerEntry(
                    entry_id=row.get("entry_id", f"gl_{i}"),
                    journal_id=row.get("journal_id", f"j_{i}"),
                    posting_date=_parse_date(row.get("posting_date", row.get("date"))) or date.today(),
                    account_code=str(row.get("account_code", "")),
                    account_name=str(row.get("account_name", "")),
                    debit=debit,
                    credit=credit,
                    settlement_id=row.get("settlement_id") or None,
                    reference=row.get("reference", ""),
                    memo=row.get("memo", ""),
                )
            )
    return entries


def load_activity_json(path: Path) -> list[dict[str, Any]]:
    """Load payment/refund activity feed."""
    data = json.loads(path.read_text())
    return data.get("items", data) if isinstance(data, dict) else data
