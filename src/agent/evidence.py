"""Shared read-only evidence tools for settlement Q&A and investigation."""

from __future__ import annotations

from typing import Any

from src.domain.formatting import format_inr
from src.domain.models import SettlementBatch, SettlementLine
from src.domain.razorpay_contract import expected_tax_paise


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
    if tool_name == "get_policy":
        return tools.get_policy(args.get("policy_id", "settlement_assurance"))
    if tool_name == "finish_answer":
        return {"status": "ok"}
    return {"error": "tool_not_allowed", "tool": tool_name}


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
