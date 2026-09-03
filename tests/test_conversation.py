import pytest

from src.agent.conversation import (
    HOME,
    PENDING_ONE,
    PENDING_ONE_CUSTOM_QUESTION,
    PENDING_ONE_QUESTIONS,
    PENDING_SCOPE,
    SETTLEMENT_CUSTOM_QUESTION,
    SETTLEMENT_QUESTIONS,
    SETTLEMENT_SELECT,
    append_response,
    append_user,
    change_subject_selection,
    confirm_subject_selection,
    go_back,
    go_home,
    initial_session,
    is_greeting,
    navigate,
    recent_subject_context,
    set_subject,
)
from src.agent.responses import simple_response
from src.domain.models import AssistantActionKind, AssistantSubjectKind


def test_initial_session_opens_with_guided_menu():
    session = initial_session()

    assert session.node_id == HOME
    assert len(session.messages) == 1
    response = session.messages[0].response
    assert response is not None
    assert response.heading == "How can I help?"
    assert len(response.actions) == 5
    assert all(choice.kind == AssistantActionKind.NAVIGATE for choice in response.actions)


@pytest.mark.parametrize("greeting", ["hi", "Hello!", "good morning", "menu"])
def test_greetings_open_menu(greeting):
    assert is_greeting(greeting)


def test_navigation_back_and_home_are_deterministic():
    session = initial_session()
    session = navigate(session, PENDING_SCOPE, "Track an unsettled payment")
    session = navigate(session, PENDING_ONE, "One payment")

    assert session.node_id == PENDING_ONE
    assert session.back_stack == [HOME, PENDING_SCOPE]

    session = go_back(session)
    assert session.node_id == PENDING_SCOPE
    assert session.back_stack == [HOME]

    session = set_subject(session, AssistantSubjectKind.PENDING_PAYMENT, ["pay_1"])
    session = go_home(session)
    assert session.node_id == HOME
    assert session.subject_kind == AssistantSubjectKind.NONE
    assert session.subject_ids == []
    assert session.back_stack == []


def test_unknown_navigation_target_is_rejected():
    with pytest.raises(ValueError, match="Unknown assistant node"):
        navigate(initial_session(), "not-a-node", "Bad route")


@pytest.mark.parametrize(
    ("selector,kind,subject_id,target,custom"),
    [
        (
            SETTLEMENT_SELECT,
            AssistantSubjectKind.SETTLEMENT,
            "setl_123",
            SETTLEMENT_QUESTIONS,
            SETTLEMENT_CUSTOM_QUESTION,
        ),
        (
            PENDING_ONE,
            AssistantSubjectKind.PENDING_PAYMENT,
            "pay_123",
            PENDING_ONE_QUESTIONS,
            PENDING_ONE_CUSTOM_QUESTION,
        ),
    ],
)
def test_confirm_selection_and_custom_question_preserve_subject(
    selector, kind, subject_id, target, custom
):
    session = navigate(initial_session(), selector, "Choose record")
    session = confirm_subject_selection(session, kind, [subject_id], target, f"Selected {subject_id}")

    assert session.node_id == target
    assert session.subject_kind == kind
    assert session.subject_ids == [subject_id]
    assert session.subject_context_start is not None

    session = navigate(session, custom, "Ask anything else")
    session = go_back(session)

    assert session.node_id == target
    assert session.subject_kind == kind
    assert session.subject_ids == [subject_id]


def test_change_selection_starts_a_clean_context_epoch():
    session = navigate(initial_session(), SETTLEMENT_SELECT, "Understand a settlement")
    session = confirm_subject_selection(
        session,
        AssistantSubjectKind.SETTLEMENT,
        ["setl_old"],
        SETTLEMENT_QUESTIONS,
        "Selected settlement setl_old",
    )
    old_version = session.context_version
    session = append_user(session, "Why is net lower?")
    session = append_response(session, simple_response("Fee explanation", "Fees reduced the net."))

    assert any("Fees reduced" in item["content"] for item in recent_subject_context(session))

    session = change_subject_selection(session, SETTLEMENT_SELECT)

    assert session.node_id == SETTLEMENT_SELECT
    assert session.subject_kind == AssistantSubjectKind.NONE
    assert session.subject_ids == []
    assert session.subject_context_start is None
    assert session.context_version == old_version + 1
    assert recent_subject_context(session) == []


def test_recent_subject_context_is_bounded_and_merchant_visible():
    session = confirm_subject_selection(
        initial_session(),
        AssistantSubjectKind.PENDING_PAYMENT,
        ["pay_123"],
        PENDING_ONE_QUESTIONS,
        "Selected payment pay_123",
    )
    for index in range(10):
        session = append_user(session, f"Question {index}")
        session = append_response(
            session,
            simple_response(f"Answer {index}", f"Visible summary {index}"),
        )

    history = recent_subject_context(session, max_exchanges=2, max_chars=200)

    assert len(history) <= 4
    assert sum(len(item["content"]) for item in history) <= 200
    assert history[-1]["role"] == "assistant"
    assert "Visible summary 9" in history[-1]["content"]
