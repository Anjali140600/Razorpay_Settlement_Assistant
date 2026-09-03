from src.agent.responses import response_from_envelope
from src.domain.models import (
    AnswerEnvelope,
    AssistantActionKind,
    AssistantResponseBlockKind,
    AssistantSubjectKind,
)


def action_kinds(response):
    return [item.kind for item in response.actions]


def test_legacy_answer_becomes_structured_summary_details_and_evidence():
    envelope = AnswerEnvelope(
        answer_text="The settlement is processed. Recon lines match the header. No action is required.",
        citations=["setl_123"],
    )

    response = response_from_envelope(
        envelope,
        AssistantSubjectKind.SETTLEMENT,
        ["setl_123"],
    )

    assert response.heading == "Settlement update"
    assert response.summary == "The settlement is processed."
    assert response.blocks[0].kind == AssistantResponseBlockKind.DETAILS
    assert response.blocks[0].items == ["Recon lines match the header.", "No action is required."]
    assert any(block.kind == AssistantResponseBlockKind.EVIDENCE for block in response.blocks)


def test_direct_ticket_intent_gets_button_without_creating_ticket():
    response = response_from_envelope(
        AnswerEnvelope(answer_text="I can prepare a request.", citations=["pay_1"]),
        AssistantSubjectKind.PENDING_PAYMENT,
        ["pay_1"],
        force_ticket=True,
    )

    assert action_kinds(response) == [
        AssistantActionKind.RAISE_TICKET,
        AssistantActionKind.VIEW_PAYMENT,
    ]
    assert response.actions[0].requires_confirmation is True


def test_compensable_answer_offers_claim_ticket_and_view():
    response = response_from_envelope(
        AnswerEnvelope(
            answer_text="A confirmed shortfall exists.",
            citations=["setl_1"],
            offer_compensation=True,
            offer_raise_ticket=True,
        ),
        AssistantSubjectKind.SETTLEMENT,
        ["setl_1"],
    )

    assert action_kinds(response) == [
        AssistantActionKind.SUBMIT_CLAIM,
        AssistantActionKind.RAISE_TICKET,
        AssistantActionKind.VIEW_SETTLEMENT,
    ]


def test_resolved_answer_does_not_invent_support_or_claim_action():
    response = response_from_envelope(
        AnswerEnvelope(answer_text="Everything matches.", citations=["setl_ok"]),
        AssistantSubjectKind.SETTLEMENT,
        ["setl_ok"],
    )

    assert action_kinds(response) == [AssistantActionKind.VIEW_SETTLEMENT]


def test_submitted_ticket_has_tracking_action_and_no_resolution_prompt():
    response = response_from_envelope(
        AnswerEnvelope(
            answer_text="Ticket submitted.",
            support_ticket_id="RZP-SUP-123",
            citations=["setl_1"],
        ),
        AssistantSubjectKind.SETTLEMENT,
        ["setl_1"],
    )

    assert response.heading == "Support ticket raised"
    assert response.actions[0].kind == AssistantActionKind.TRACK_STATUS
    assert response.ask_resolution is False

