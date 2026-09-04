"""Report payload builders for downloadable reconciliation data."""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from src.domain.models import PendingPayment


def build_unsettled_payments_report(
    payments: Sequence[PendingPayment],
    cutoff_date: date,
) -> dict[str, Any]:
    """Build a JSON-ready report for captured payments awaiting settlement."""
    eligible_payments = [
        payment for payment in payments if payment.captured_at.date() <= cutoff_date
    ]
    payment_rows = [
        {
            "payment_id": payment.entity_id,
            "order_id": payment.order_id,
            "amount_paise": payment.amount,
            "currency": payment.currency,
            "method": payment.method,
            "captured_at": payment.captured_at.isoformat(),
            "cycle_type": payment.cycle_type,
            "instant_eligible": payment.instant_eligible,
            "expected_settlement_at": (
                payment.expected_settlement_at.isoformat()
                if payment.expected_settlement_at
                else None
            ),
        }
        for payment in eligible_payments
    ]

    return {
        "report_type": "unsettled_payments",
        "cutoff": cutoff_date.isoformat(),
        "summary": {
            "payment_count": len(eligible_payments),
            "total_amount_paise": sum(payment.amount for payment in eligible_payments),
            "instant_eligible": sum(
                payment.instant_eligible == "yes" for payment in eligible_payments
            ),
            "eligibility_unknown": sum(
                payment.instant_eligible == "unknown" for payment in eligible_payments
            ),
        },
        "payments": payment_rows,
    }
