from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.connectors.loaders import load_pending_payments

APP = Path(__file__).resolve().parents[1] / "apps" / "streamlit_app.py"
DEMO_DIR = APP.parents[1] / "data" / "synthetic" / "demo"


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


def test_summary_changes_with_browse_category():
    app = AppTest.from_file(APP, default_timeout=20).run()

    assert [metric.label for metric in app.metric[:3]] == ["Verified", "Needs attention", "Total"]

    browse_category = next(radio for radio in app.radio if radio.label == "Browse category")
    browse_category.set_value("Unsettled Payments").run()

    assert not app.exception
    pending_payments = load_pending_payments(DEMO_DIR / "recon.json", DEMO_DIR / "manifest.json")
    instant_eligible = sum(payment.instant_eligible == "yes" for payment in pending_payments)
    unsettled_amount = sum(payment.amount for payment in pending_payments)
    assert [(metric.label, metric.value) for metric in app.metric[:3]] == [
        ("Unsettled payments", str(len(pending_payments))),
        ("Instant eligible", str(instant_eligible)),
        ("Total amount", f"₹{unsettled_amount / 100:,.2f}"),
    ]


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
