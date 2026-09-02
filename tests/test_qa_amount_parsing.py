"""Digits inside an entity id are not money, however deep in the id they sit."""

from __future__ import annotations

from src.agent.settlement_qa import parse_amount_candidates


def test_trailing_index_of_a_payment_id_is_not_an_amount():
    """pay_setl_tax_mismatch_1 must not be read as one paisa."""
    assert parse_amount_candidates(
        "For payment pay_setl_tax_mismatch_1, what should the GST have been?"
    ) == []


def test_digits_deep_inside_a_settlement_id_ignored():
    assert parse_amount_candidates("Tell me about setl_merchant_d2c_005.") == []


def test_refund_and_adjustment_ids_ignored():
    assert parse_amount_candidates("Why is rfnd_setl_messy_refund_day_2 debited?") == []
    assert parse_amount_candidates("Explain adj_setl_messy_chargebacks_2.") == []


def test_utr_digits_ignored():
    assert parse_amount_candidates("What happened to UTR20260808888BCH1?") == []


def test_real_amount_still_parsed():
    assert 50000 in parse_amount_candidates("Which settlement was ₹500.00?")


def test_real_amount_parsed_alongside_an_entity_id():
    """The id contributes nothing; the genuine figure still does."""
    got = parse_amount_candidates("Did pay_setl_tax_mismatch_1 settle for ₹8,500.00?")
    assert 850000 in got


def test_bare_number_still_parsed():
    got = parse_amount_candidates("Find the settlement for 42640")
    assert 42640 in got or 4264000 in got
