"""Exception identity must be reproducible across runs and processes."""

from __future__ import annotations

from src.lifecycle.identity import (
    exception_id,
    extract_reference_settlement_id,
    signed_delta_paise,
)


def test_id_is_stable_for_the_same_inputs():
    a = exception_id("setl_lc_exact", "batch_integrity", 2000)
    b = exception_id("setl_lc_exact", "batch_integrity", 2000)
    assert a == b
    assert a.startswith("exc_")


def test_id_differs_by_settlement():
    assert exception_id("setl_a", "batch_integrity", 2000) != exception_id(
        "setl_b", "batch_integrity", 2000
    )


def test_id_differs_by_delta():
    assert exception_id("setl_a", "batch_integrity", 2000) != exception_id(
        "setl_a", "batch_integrity", 2001
    )


def test_id_differs_by_control_type():
    assert exception_id("setl_a", "batch_integrity", 2000) != exception_id(
        "setl_a", "tax_lines", 2000
    )


def test_signed_delta_is_header_minus_lines():
    class FakeBatch:
        amount = 100000
        net_from_lines = 98000

    assert signed_delta_paise(FakeBatch()) == 2000


def test_signed_delta_is_negative_when_over_settled():
    class FakeBatch:
        amount = 98000
        net_from_lines = 100000

    assert signed_delta_paise(FakeBatch()) == -2000


def test_reference_extracted_from_description():
    assert extract_reference_settlement_id(
        "Recon correction for setl_lc_exact"
    ) == "setl_lc_exact"


def test_no_reference_returns_none():
    assert extract_reference_settlement_id("Goodwill credit") is None


def test_two_distinct_ids_is_ambiguous_and_returns_none():
    assert extract_reference_settlement_id("covers setl_a and setl_b") is None


def test_same_id_repeated_is_not_ambiguous():
    assert extract_reference_settlement_id("setl_a correction, see setl_a") == "setl_a"


def test_empty_text_is_safe():
    assert extract_reference_settlement_id("") is None
    assert extract_reference_settlement_id(None) is None
