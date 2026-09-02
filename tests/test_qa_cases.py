"""The label set is the whole value of the scorecard; it must be well-formed."""

from __future__ import annotations

import pytest

from src.eval.qa_cases import QA_CLASSES, load_qa_cases


def test_cases_load_from_default_path():
    assert len(load_qa_cases()) >= 40


def test_every_class_is_represented():
    present = {c.qa_class for c in load_qa_cases()}
    assert present == set(QA_CLASSES)


def test_case_ids_are_unique():
    ids = [c.case_id for c in load_qa_cases()]
    assert len(ids) == len(set(ids))


def test_money_precision_cases_state_expected_amounts():
    for case in load_qa_cases():
        if case.qa_class == "money_precision":
            assert case.expect_amounts, f"{case.case_id} has no expected amount"


def test_must_abstain_cases_expect_abstention():
    for case in load_qa_cases():
        if case.qa_class == "must_abstain":
            assert case.expect_abstain is True
            assert case.expect_citations is False


def test_must_refuse_cases_expect_refusal():
    for case in load_qa_cases():
        if case.qa_class == "must_refuse":
            assert case.expect_refuse is True


def test_unknown_class_rejected(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"case_id": "x", "class": "vibes", "question": "hi"}\n')
    with pytest.raises(ValueError, match="vibes"):
        load_qa_cases(bad)


def test_duplicate_case_id_rejected(tmp_path):
    dup = tmp_path / "dup.jsonl"
    dup.write_text(
        '{"case_id": "a", "class": "answerable", "question": "q"}\n'
        '{"case_id": "a", "class": "answerable", "question": "q2"}\n'
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_qa_cases(dup)


def test_blank_lines_ignored(tmp_path):
    ok = tmp_path / "ok.jsonl"
    ok.write_text(
        '{"case_id": "a", "class": "answerable", "question": "q"}\n'
        "\n"
        '{"case_id": "b", "class": "must_refuse", "question": "q2", "expect_refuse": true}\n'
    )
    assert [c.case_id for c in load_qa_cases(ok)] == ["a", "b"]
