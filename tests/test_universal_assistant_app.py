from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "apps" / "streamlit_app.py"


def test_universal_launcher_replaces_embedded_chat_surfaces():
    app = AppTest.from_file(APP, default_timeout=20).run()

    assert not app.exception
    launchers = [button for button in app.button if button.label == ":material/support_agent:"]
    assert len(launchers) == 1
    assert len(app.chat_input) == 0

    launchers[0].click().run()

    assert not app.exception
    assert len(app.chat_input) == 0
    labels = {button.label for button in app.button}
    assert "Track an unsettled payment" in labels
    assert "Understand a settlement" in labels
    assert "Talk to support" in labels


def test_free_text_ticket_request_renders_contextual_button():
    app = AppTest.from_file(APP, default_timeout=20).run()
    next(button for button in app.button if button.label == ":material/support_agent:").click().run()
    next(button for button in app.button if button.label == "Ask something else").click().run()

    app.chat_input[0].set_value("raise a ticket for pay_pending_000").run()

    assert not app.exception
    labels = {button.label for button in app.button}
    assert "Raise ticket" in labels
    assert "View payment" in labels
    assert "Confirm and raise ticket" not in labels


def _open_assistant():
    app = AppTest.from_file(APP, default_timeout=20).run()
    next(button for button in app.button if button.label == ":material/support_agent:").click().run()
    return app


def _visible_text(app) -> str:
    values = []
    for collection in (app.markdown, app.text, app.caption, app.info, app.warning):
        values.extend(str(element.value) for element in collection)
    return "\n".join(values)


def test_settlement_selection_then_contextual_free_text_keeps_subject():
    app = _open_assistant()
    next(button for button in app.button if button.label == "Understand a settlement").click().run()

    assert len(app.selectbox) >= 1
    assert len(app.chat_input) == 0
    assert "Where is this settlement?" not in {button.label for button in app.button}

    next(button for button in app.button if button.label == "Continue").click().run()

    labels = {button.label for button in app.button}
    assert "Where is this settlement?" in labels
    assert "Ask anything else" in labels
    assert len(app.chat_input) == 0

    next(button for button in app.button if button.label == "Ask anything else").click().run()
    assert len(app.chat_input) == 1

    app.chat_input[0].set_value("What about the fees?").run()

    assert not app.exception
    assert len(app.chat_input) == 1
    assert "Choose a record first" not in _visible_text(app)
    assert "Asking about settlement" in _visible_text(app)


def test_payment_selection_then_contextual_free_text_keeps_subject():
    app = _open_assistant()
    next(button for button in app.button if button.label == "Track an unsettled payment").click().run()
    next(button for button in app.button if button.label == "One payment").click().run()

    assert len(app.chat_input) == 0
    next(button for button in app.button if button.label == "Continue").click().run()
    labels = {button.label for button in app.button}
    assert "When will this settle?" in labels
    assert "Ask anything else" in labels

    next(button for button in app.button if button.label == "Ask anything else").click().run()
    app.chat_input[0].set_value("Why is it still pending?").run()

    assert not app.exception
    assert len(app.chat_input) == 1
    assert "Choose a record first" not in _visible_text(app)
    assert "Asking about payment" in _visible_text(app)
