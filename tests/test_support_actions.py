from src.actions.support import raise_general_support_ticket
from src.domain.models import AssistantSubjectKind


def test_general_support_ticket_is_idempotent_for_same_evidence():
    kwargs = {
        "subject_kind": AssistantSubjectKind.PENDING_PAYMENT,
        "subject_ids": ["pay_1"],
        "merchant_summary": "Payment is overdue",
        "facts": ["Amount: ₹100.00"],
    }

    first = raise_general_support_ticket(**kwargs)
    second = raise_general_support_ticket(**kwargs)

    assert first.support_ticket_id == second.support_ticket_id
    assert first.escalated_to_support is True
    assert first.citations == ["pay_1"]

