"""Domain model tests."""

from __future__ import annotations

from datetime import date, datetime

from src.domain.models import PendingPayment


def test_pending_payment_defaults():
    p = PendingPayment(
        entity_id="pay_pending_001",
        amount=50000,
        captured_at=datetime(2026, 8, 28, 10, 0, 0),
    )
    assert p.currency == "INR"
    assert p.cycle_type == "standard"
    assert p.instant_eligible == "unknown"
    assert p.order_id is None
    assert p.method is None
    assert p.expected_settlement_at is None
