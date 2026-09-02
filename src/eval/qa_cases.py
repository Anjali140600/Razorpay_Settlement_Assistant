"""Hand-labeled Q&A eval cases — authored against the field contract, never generated."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

QA_CLASSES = ("answerable", "must_abstain", "must_refuse", "money_precision")

QA_EVAL_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "qa_eval.jsonl"


class QaCase(BaseModel):
    case_id: str
    qa_class: str = Field(alias="class")
    question: str
    settlement_id: str | None = None
    expect_abstain: bool = False
    expect_refuse: bool = False
    expect_citations: bool = True
    expect_amounts: list[str] = Field(default_factory=list)
    forbid_amounts: list[str] = Field(default_factory=list)
    note: str = ""

    model_config = {"populate_by_name": True}


def load_qa_cases(path: Path | None = None) -> list[QaCase]:
    """Parse the JSONL label set, rejecting anything malformed loudly."""
    path = path or QA_EVAL_PATH
    cases: list[QaCase] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        row = json.loads(raw)
        if row.get("class") not in QA_CLASSES:
            raise ValueError(f"{path}:{lineno}: unknown class {row.get('class')!r}")
        cases.append(QaCase.model_validate(row))
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise ValueError(f"{path}: duplicate case_id {case.case_id!r}")
        seen.add(case.case_id)
    return cases
