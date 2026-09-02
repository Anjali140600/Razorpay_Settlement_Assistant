"""Published numbers must carry provenance and must report the worst run, not the best."""

from __future__ import annotations

import json

from src.eval.qa_report import flaky_cases, provenance, render_markdown, worst_run, write_report


def run(pass_rate, emissions=0, rows=None):
    return {
        "metrics": {"qa_pass_rate": pass_rate,
                    "qa_unverified_amount_emissions": emissions,
                    "qa_cases_total": 2},
        "rows": rows or [],
    }


def test_worst_run_is_the_lowest_pass_rate():
    assert worst_run([run(0.95), run(0.80), run(0.90)])["metrics"]["qa_pass_rate"] == 0.80


def test_ties_broken_by_more_unverified_emissions():
    runs = [run(0.90, emissions=0), run(0.90, emissions=3)]
    assert worst_run(runs)["metrics"]["qa_unverified_amount_emissions"] == 3


def test_flaky_cases_detected_across_runs():
    a = run(1.0, rows=[{"case_id": "x", "passed": True}, {"case_id": "y", "passed": True}])
    b = run(0.5, rows=[{"case_id": "x", "passed": False}, {"case_id": "y", "passed": True}])
    assert flaky_cases([a, b]) == ["x"]


def test_no_flaky_cases_when_stable():
    a = run(1.0, rows=[{"case_id": "x", "passed": True}])
    b = run(1.0, rows=[{"case_id": "x", "passed": True}])
    assert flaky_cases([a, b]) == []


def test_provenance_carries_hashes_and_commit(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text('{"case_id": "a", "class": "answerable", "question": "q"}\n')
    prov = provenance(cases)
    assert len(prov["dataset_sha256"]) == 64
    assert len(prov["prompt_sha256"]) == 64
    assert prov["git_commit"]
    assert prov["generated_at"].endswith("Z")


def report_stub():
    return {
        "provenance": {"model": "m", "provider": "p", "git_commit": "abc",
                       "dataset_sha256": "d" * 64, "prompt_sha256": "p" * 64,
                       "generated_at": "2026-09-02T00:00:00Z"},
        "runs": 3,
        "headline": {"qa_pass_rate": 0.9, "qa_unverified_amount_emissions": 0,
                     "qa_cases_total": 41},
        "deterministic_baseline": {"qa_pass_rate": 0.829, "qa_cases_total": 41},
        "flaky_cases": [],
    }


def test_markdown_states_injection_is_a_system_guardrail():
    md = render_markdown(report_stub())
    assert "before the model is invoked" in md
    assert "worst of 3" in md.lower()


def test_markdown_discloses_the_money_guard_limit():
    md = render_markdown(report_stub())
    assert "Bare numerals" in md


def test_markdown_lists_flaky_cases_when_present():
    rep = report_stub()
    rep["flaky_cases"] = ["money_batch_gap"]
    assert "money_batch_gap" in render_markdown(rep)


def test_write_report_emits_both_files(tmp_path):
    js, md = write_report(report_stub(), tmp_path)
    assert json.loads(js.read_text())["runs"] == 3
    assert md.read_text().startswith("# Q&A Trust Scorecard")


def test_ai_column_invalid_when_provider_was_exhausted():
    from src.eval.qa_report import ai_column_valid

    assert ai_column_valid({"qa_llm_unavailable": 0}, runs=3) is True
    assert ai_column_valid({"qa_llm_unavailable": 7}, runs=3) is False
    assert ai_column_valid({"qa_llm_unavailable": 0}, runs=0) is False


def test_markdown_refuses_to_present_a_degraded_ai_column():
    rep = report_stub()
    rep["headline"]["qa_llm_unavailable"] = 11
    rep["ai_column_valid"] = False
    md = render_markdown(rep)
    assert "NOT a measurement of the model" in md
    assert "11" in md


def test_baseline_only_report_has_no_ai_column():
    """With no AI run there is nothing to put in an AI column; do not fake one."""
    rep = report_stub()
    rep["runs"] = 0
    rep["baseline_only"] = True
    rep["ai_column_valid"] = False
    md = render_markdown(rep)
    assert "AI enabled" not in md
    assert "AI column was not measured" in md
    assert "provider failed on" not in md.lower()


def test_degraded_ai_run_still_warns():
    rep = report_stub()
    rep["baseline_only"] = False
    rep["headline"]["qa_llm_unavailable"] = 11
    rep["ai_column_valid"] = False
    md = render_markdown(rep)
    assert "NOT a measurement of the model" in md


def test_baseline_only_header_does_not_name_a_model_or_claim_runs():
    rep = report_stub()
    rep["runs"] = 0
    rep["baseline_only"] = True
    md = render_markdown(rep)
    assert "not used in this run" in md
    assert "worst of 0" not in md
