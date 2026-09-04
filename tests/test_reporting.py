"""Tests for downloadable report payloads."""

from __future__ import annotations

from datetime import date, datetime

from src.domain.models import PendingPayment
from src.reporting import build_unsettled_payments_report


def test_build_unsettled_payments_report_includes_summary_and_payment_fields():
    payments = [
        PendingPayment(
            entity_id="pay_pending_001",
            order_id="order_001",
            amount=1250000,
            method="upi",
            captured_at=datetime(2026, 9, 1, 10, 30),
            cycle_type="instant_eligible",
            instant_eligible="yes",
            expected_settlement_at=date(2026, 9, 3),
        ),
        PendingPayment(
            entity_id="pay_pending_002",
            amount=89900,
            captured_at=datetime(2026, 9, 2, 11, 0),
            instant_eligible="unknown",
        ),
    ]

    report = build_unsettled_payments_report(payments, date(2026, 9, 2))

    assert report["report_type"] == "unsettled_payments"
    assert report["cutoff"] == "2026-09-02"
    assert report["summary"] == {
        "payment_count": 2,
        "total_amount_paise": 1339900,
        "instant_eligible": 1,
        "eligibility_unknown": 1,
    }
    assert report["payments"][0] == {
        "payment_id": "pay_pending_001",
        "order_id": "order_001",
        "amount_paise": 1250000,
        "currency": "INR",
        "method": "upi",
        "captured_at": "2026-09-01T10:30:00",
        "cycle_type": "instant_eligible",
        "instant_eligible": "yes",
        "expected_settlement_at": "2026-09-03",
    }


def test_build_unsettled_payments_report_handles_no_payments():
    report = build_unsettled_payments_report([], date(2026, 9, 2))

    assert report["summary"] == {
        "payment_count": 0,
        "total_amount_paise": 0,
        "instant_eligible": 0,
        "eligibility_unknown": 0,
    }
    assert report["payments"] == []


def test_build_unsettled_payments_report_excludes_payments_after_cutoff():
    payments = [
        PendingPayment(
            entity_id="pay_in_range",
            amount=10000,
            captured_at=datetime(2026, 9, 2, 23, 59),
            instant_eligible="yes",
        ),
        PendingPayment(
            entity_id="pay_after_cutoff",
            amount=50000,
            captured_at=datetime(2026, 9, 3, 0, 0),
            instant_eligible="unknown",
        ),
    ]

    report = build_unsettled_payments_report(payments, date(2026, 9, 2))

    assert report["summary"] == {
        "payment_count": 1,
        "total_amount_paise": 10000,
        "instant_eligible": 1,
        "eligibility_unknown": 0,
    }
    assert [payment["payment_id"] for payment in report["payments"]] == ["pay_in_range"]
