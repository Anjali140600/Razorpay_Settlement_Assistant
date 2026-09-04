from datetime import datetime

from apps.universal_assistant import (
    AssistantDataContext,
    _settlement_option_label,
    _settlement_status_and_date,
    _sorted_settlement_ids,
    _with_settlement_context,
)
from src.agent.responses import simple_response
from src.domain.models import (
    ControlStatus,
    SettlementBatch,
    SettlementCloseDecision,
    SettlementIntegrityStatus,
    SettlementStatus,
)


SETTLED_AT = datetime(2026, 8, 24, 11, 30)


def _context(integrity_status: SettlementIntegrityStatus) -> AssistantDataContext:
    batch = SettlementBatch(
        settlement_id="setl_123",
        amount=125_000,
        processed_at=SETTLED_AT,
    )
    decision = SettlementCloseDecision(
        settlement_id=batch.settlement_id,
        status=SettlementStatus.PROVEN,
        integrity_status=integrity_status,
        batch_integrity=ControlStatus.PASS,
        net_amount_paise=batch.amount,
        processed_at=SETTLED_AT,
    )
    return AssistantDataContext(
        batches={batch.settlement_id: batch},
        decisions={decision.settlement_id: decision},
        pending_payments={},
        use_llm=False,
    )


def test_settlement_option_shows_verified_status_and_date():
    context = _context(SettlementIntegrityStatus.VERIFIED)

    label = _settlement_option_label(context, "setl_123")

    assert label == "₹1,250.00 · 24 Aug 2026 · 🟢 Verified · setl_123"


def test_settlement_answer_shows_needs_attention_status_and_date():
    context = _context(SettlementIntegrityStatus.NEEDS_ATTENTION)
    response = _with_settlement_context(
        simple_response("Settlement update", "I checked this settlement."),
        context,
        "setl_123",
    )

    assert response.blocks[0].title == "Settlement details"
    assert response.blocks[0].items == [
        "Settlement: setl_123",
        "Status: :red-badge[Needs attention]",
        "Date: 24 Aug 2026",
    ]


def test_missing_decision_is_never_presented_as_verified():
    context = _context(SettlementIntegrityStatus.VERIFIED)
    context = AssistantDataContext(
        batches=context.batches,
        decisions={},
        pending_payments={},
        use_llm=False,
    )

    assert _settlement_status_and_date(context, "setl_123") == (
        "Needs attention",
        "24 Aug 2026",
    )


def test_settlements_sort_attention_first_then_newest_date():
    records = [
        ("attention_old", datetime(2026, 8, 20), SettlementIntegrityStatus.NEEDS_ATTENTION),
        ("verified_new", datetime(2026, 8, 30), SettlementIntegrityStatus.VERIFIED),
        ("attention_new", datetime(2026, 8, 25), SettlementIntegrityStatus.NEEDS_ATTENTION),
        ("verified_old", datetime(2026, 8, 10), SettlementIntegrityStatus.VERIFIED),
    ]
    batches = {}
    decisions = {}
    for settlement_id, processed_at, integrity_status in records:
        batch = SettlementBatch(
            settlement_id=settlement_id,
            amount=100_000,
            processed_at=processed_at,
        )
        decision = SettlementCloseDecision(
            settlement_id=settlement_id,
            status=SettlementStatus.PROVEN,
            integrity_status=integrity_status,
            batch_integrity=ControlStatus.PASS,
            net_amount_paise=batch.amount,
            processed_at=processed_at,
        )
        batches[settlement_id] = batch
        decisions[settlement_id] = decision
    context = AssistantDataContext(
        batches=batches,
        decisions=decisions,
        pending_payments={},
        use_llm=False,
    )

    assert _sorted_settlement_ids(context) == [
        "attention_new",
        "attention_old",
        "verified_new",
        "verified_old",
    ]
