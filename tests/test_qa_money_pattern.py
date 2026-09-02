"""Money detection must cover every currency form a model actually emits."""

from __future__ import annotations

from src.agent.settlement_qa import money_figures, unverified_amounts


def test_rupee_symbol_still_detected():
    assert money_figures("Net payout was ₹500.00") == {"₹500.00"}


def test_rs_and_inr_forms_detected():
    assert money_figures("Fee of Rs 250.50 charged") == {"₹250.50"}
    assert money_figures("Fee of Rs. 250.50 charged") == {"₹250.50"}
    assert money_figures("Total INR 1,200 settled") == {"₹1200"}


def test_trailing_rupees_word_detected():
    assert money_figures("You received 900 rupees") == {"₹900"}


def test_commas_normalised_so_forms_compare_equal():
    assert money_figures("₹5,844.00") == money_figures("Rs 5844.00")


def test_bare_numbers_not_matched():
    """Deliberate: matching bare digits would reject '18% GST' and '50 records'."""
    assert money_figures("18% GST applies to 50 records in step 2") == set()


def test_unverified_amount_caught_in_rs_form():
    allowed = {"₹500.00"}
    assert unverified_amounts("We paid Rs 999.00", allowed) == {"₹999.00"}


def test_verified_amount_in_rs_form_accepted():
    allowed = {"₹500.00"}
    assert unverified_amounts("We paid Rs 500.00", allowed) == set()
