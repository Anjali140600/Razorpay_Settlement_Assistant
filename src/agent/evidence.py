"""Shared read-only evidence tools for settlement Q&A."""

from __future__ import annotations

from typing import Any

from src.domain.formatting import format_inr
from src.domain.models import SettlementBatch, SettlementLine
from src.domain.razorpay_contract import expected_tax_paise

NEAREST_MATCHES = 5
PAYMENT_PREVIEW = 3


class SettlementEvidenceTools:
    """Allowlisted read-only tools — Razorpay settlements + recon only."""

    def __init__(self, batches: dict[str, SettlementBatch]):
        self.batches = batches

    def fetch_settlement(self, settlement_id: str) -> dict[str, Any]:
        if settlement_id not in self.batches:
            return {"error": "not_found", "settlement_id": settlement_id}
        b = self.batches[settlement_id]
        return {
            "settlement_id": b.settlement_id,
            "amount_paise": b.amount,
            "amount_display": format_inr(b.amount),
            "utr": b.utr,
            "status": b.status,
            "processed_at": b.processed_at.isoformat() if b.processed_at else None,
            "line_count": len(b.lines),
        }

    def fetch_recon_lines(self, settlement_id: str) -> dict[str, Any]:
        if settlement_id not in self.batches:
            return {"error": "not_found", "settlement_id": settlement_id}
        b = self.batches[settlement_id]
        return {
            "settlement_id": settlement_id,
            "lines": [_line_payload(l) for l in b.lines],
        }

    def calculate_batch(self, settlement_id: str) -> dict[str, Any]:
        if settlement_id not in self.batches:
            return {"error": "not_found", "settlement_id": settlement_id}
        b = self.batches[settlement_id]
        gross = sum(l.amount for l in b.lines if l.line_type == "payment")
        total_fee = sum(l.fee for l in b.lines)
        total_tax = sum(l.tax for l in b.lines)
        return {
            "settlement_id": settlement_id,
            "header_amount_paise": b.amount,
            "header_amount_display": format_inr(b.amount),
            "net_from_lines_paise": b.net_from_lines,
            "net_from_lines_display": format_inr(b.net_from_lines),
            "match": b.net_from_lines == b.amount,
            "gap_paise": b.amount - b.net_from_lines,
            "gap_display": format_inr(b.amount - b.net_from_lines),
            "gross_payments_paise": gross,
            "gross_payments_display": format_inr(gross),
            "total_fee_paise": total_fee,
            "total_fee_display": format_inr(total_fee),
            "total_tax_paise": total_tax,
            "total_tax_display": format_inr(total_tax),
        }

    def explain_fee_tax(self, settlement_id: str, entity_id: str | None = None) -> dict[str, Any]:
        if settlement_id not in self.batches:
            return {"error": "not_found", "settlement_id": settlement_id}
        b = self.batches[settlement_id]
        lines = b.lines
        if entity_id:
            lines = [l for l in lines if l.entity_id == entity_id]
            if not lines:
                return {"error": "not_found", "entity_id": entity_id}
        breakdown = []
        for l in lines:
            if l.fee == 0 and l.tax == 0 and l.line_type not in ("payment", "transfer"):
                continue
            breakdown.append(
                {
                    "entity_id": l.entity_id,
                    "type": l.line_type,
                    "amount_paise": l.amount,
                    "amount_display": format_inr(l.amount),
                    "fee_paise": l.fee,
                    "fee_display": format_inr(l.fee),
                    "tax_paise": l.tax,
                    "tax_display": format_inr(l.tax),
                    "expected_tax_paise": expected_tax_paise(l.fee),
                    "expected_tax_display": format_inr(expected_tax_paise(l.fee)),
                    "credit_paise": l.credit,
                    "debit_paise": l.debit,
                }
            )
        return {"settlement_id": settlement_id, "breakdown": breakdown}

    def search_by_amount(self, amount_paise: int, limit: int = NEAREST_MATCHES) -> dict[str, Any]:
        """Find settlements and payment lines worth exactly amount_paise.

        Only the loaded batches are scanned, so both the exact hits and the
        "closest" fallback stay inside this merchant's own Razorpay data.
        """
        settlements_exact: list[dict[str, Any]] = []
        payments_exact: list[dict[str, Any]] = []
        near: list[tuple[int, int, dict[str, Any]]] = []

        for b in self.batches.values():
            settlement_hit = _settlement_hit(b)
            if b.amount == amount_paise:
                settlements_exact.append(settlement_hit)
            else:
                near.append((abs(b.amount - amount_paise), 1, settlement_hit))
            for line in b.lines:
                payment_hit = _payment_hit(line)
                if line.amount == amount_paise:
                    payments_exact.append(payment_hit)
                else:
                    near.append((abs(line.amount - amount_paise), 0, payment_hit))

        # Payments rank ahead of settlements at the same distance: a merchant
        # asking about an amount we cannot match wants the payment lines.
        near.sort(key=lambda item: (item[0], item[1]))
        nearest = [{**hit, "delta_paise": delta, "delta_display": format_inr(delta)} for delta, _, hit in near[:limit]]

        return {
            "amount_paise": amount_paise,
            "amount_display": format_inr(amount_paise),
            "settlements_exact": settlements_exact[:limit],
            "payments_exact": payments_exact[:limit],
            "nearest": nearest,
        }

    def search_by_date(self, month: int, day: int, year: int | None = None) -> dict[str, Any]:
        """Settlements processed on a calendar day. Year is optional — '23 aug' has none."""
        matches = [
            _settlement_hit(b)
            for b in self.batches.values()
            if b.processed_at is not None
            and b.processed_at.month == month
            and b.processed_at.day == day
            and (year is None or b.processed_at.year == year)
        ]
        matches.sort(key=lambda hit: hit["settlement_id"])
        return {"month": month, "day": day, "year": year, "matches": matches}

    def payment_preview(self, settlement_id: str, limit: int = PAYMENT_PREVIEW) -> list[dict[str, Any]]:
        """First few money lines on a settlement, for context under a match."""
        b = self.batches.get(settlement_id)
        if not b:
            return []
        return [_payment_hit(l) for l in b.lines[:limit]]

    def search_settlements(self, query: str) -> dict[str, Any]:
        q = query.upper().replace(" ", "")
        matches = []
        for sid, b in self.batches.items():
            if q in sid.upper() or (b.utr and q in b.utr.upper().replace(" ", "")):
                matches.append(
                    {
                        "settlement_id": sid,
                        "amount_paise": b.amount,
                        "amount_display": format_inr(b.amount),
                        "utr": b.utr,
                    }
                )
        return {"query": query, "matches": matches[:10]}

    def get_policy(self, policy_id: str) -> dict[str, Any]:
        policies = {
            "settlement_assurance": (
                "Razorpay Settlement Assistant verifies settlement headers against recon lines "
                "and fee/GST rules. It does not confirm bank receipt."
            ),
            "tax_formula": "For INR domestic lines, tax ≈ round(fee × 18/118) with ±1 paise tolerance.",
            "abstention": "If data is missing from loaded settlements, abstain — never guess.",
        }
        return {"policy_id": policy_id, "text": policies.get(policy_id, "Unknown policy")}


QA_TOOL_ALLOWLIST = {
    "fetch_settlement",
    "fetch_recon_lines",
    "calculate_batch",
    "explain_fee_tax",
    "search_settlements",
    "search_by_amount",
    "search_by_date",
    "get_policy",
    "finish_answer",
}


def execute_qa_tool(tools: SettlementEvidenceTools, tool_name: str, args: dict[str, Any]) -> Any:
    if tool_name not in QA_TOOL_ALLOWLIST:
        return {"error": "tool_not_allowed", "tool": tool_name}
    if tool_name == "fetch_settlement":
        return tools.fetch_settlement(args["settlement_id"])
    if tool_name == "fetch_recon_lines":
        return tools.fetch_recon_lines(args["settlement_id"])
    if tool_name == "calculate_batch":
        return tools.calculate_batch(args["settlement_id"])
    if tool_name == "explain_fee_tax":
        return tools.explain_fee_tax(args["settlement_id"], args.get("entity_id"))
    if tool_name == "search_settlements":
        return tools.search_settlements(args.get("query", ""))
    if tool_name == "search_by_amount":
        amount = _as_int(args.get("amount_paise"))
        if amount is None:
            return {"error": "bad_argument", "argument": "amount_paise"}
        return tools.search_by_amount(amount, _as_int(args.get("limit")) or NEAREST_MATCHES)
    if tool_name == "search_by_date":
        month, day = _as_int(args.get("month")), _as_int(args.get("day"))
        if month is None or day is None:
            return {"error": "bad_argument", "argument": "month/day"}
        return tools.search_by_date(month, day, _as_int(args.get("year")))
    if tool_name == "get_policy":
        return tools.get_policy(args.get("policy_id", "settlement_assurance"))
    if tool_name == "finish_answer":
        return {"status": "ok"}
    return {"error": "tool_not_allowed", "tool": tool_name}


def _as_int(value: Any) -> int | None:
    """Models send numbers as strings often enough to be worth coercing."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _settlement_hit(batch: SettlementBatch) -> dict[str, Any]:
    return {
        "kind": "settlement",
        "settlement_id": batch.settlement_id,
        "amount_paise": batch.amount,
        "amount_display": format_inr(batch.amount),
        "utr": batch.utr,
        "status": batch.status,
        "processed_on": batch.processed_at.date().isoformat() if batch.processed_at else None,
    }


def _payment_hit(line: SettlementLine) -> dict[str, Any]:
    return {
        "kind": "payment",
        "entity_id": line.entity_id,
        "settlement_id": line.settlement_id,
        "type": line.line_type,
        "amount_paise": line.amount,
        "amount_display": format_inr(line.amount),
        "fee_paise": line.fee,
        "fee_display": format_inr(line.fee),
        "tax_paise": line.tax,
        "tax_display": format_inr(line.tax),
    }


def _line_payload(line: SettlementLine) -> dict[str, Any]:
    return {
        "entity_id": line.entity_id,
        "type": line.line_type,
        "amount_paise": line.amount,
        "amount_display": format_inr(line.amount),
        "fee_paise": line.fee,
        "fee_display": format_inr(line.fee),
        "tax_paise": line.tax,
        "tax_display": format_inr(line.tax),
        "credit_paise": line.credit,
        "debit_paise": line.debit,
        "payment_id": line.payment_id,
        "order_id": line.order_id,
    }
