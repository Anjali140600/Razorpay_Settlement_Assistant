"""Razorpay Settlement Assistant engine — deterministic controls and bounded Q&A."""

from __future__ import annotations

import json
import src.config  # noqa: F401 — load .env before other imports use os.environ

import time
from datetime import date, datetime
from pathlib import Path

from src.agent.llm_client import agent_mode_label, get_llm_model, llm_provider, should_use_llm
from src.connectors.loaders import (
    attach_lines_to_batches,
    load_recon_json,
    load_settlements_json,
)
from src.controls.engine import (
    build_settlement_exception_case,
    compose_settlement_integrity_decision,
    validate_batch_integrity,
    validate_tax_lines,
)
from src.domain.models import (
    AuditEvent,
    ControlStatus,
    ReconciliationRun,
    SettlementIntegrityStatus,
    SettlementStatus,
)
from src.eval.holdout_runner import run_holdout_eval
from src.lifecycle.runner import run_lifecycle_eval


class ReconciliationEngine:
    """Rules own money; loads Razorpay settlements + recon only."""

    def __init__(self, data_dir: Path, eval_date: date | None = None, use_llm: bool | None = None):
        self.data_dir = Path(data_dir)
        self.eval_date = eval_date or date.today()
        self.use_llm = use_llm if use_llm is not None else should_use_llm()
        self.batches: list = []
        self.eval_labels: dict = {}

    def load_sources(self) -> None:
        recon_lines = load_recon_json(self.data_dir / "recon.json")
        batches = load_settlements_json(self.data_dir / "settlements.json")
        self.batches = attach_lines_to_batches(batches, recon_lines)
        labels_path = self.data_dir.parent.parent / "eval_labels.json"
        if not labels_path.exists():
            labels_path = self.data_dir / "data" / "eval_labels.json"
        if not labels_path.exists():
            labels_path = Path(__file__).resolve().parent.parent / "data" / "eval_labels.json"
        if labels_path.exists():
            doc = json.loads(labels_path.read_text())
            self.eval_labels = doc.get("labels", {})

    def run(self) -> ReconciliationRun:
        start = time.perf_counter()
        run = ReconciliationRun(cutoff_date=self.eval_date)
        mode = agent_mode_label(self.use_llm)
        run.audit_events.append(
            AuditEvent(
                run_id=run.run_id,
                event_type="run_started",
                payload={
                    "cutoff": str(self.eval_date),
                    "agent_mode": mode,
                    "product": "razorpay_settlement_assistant",
                },
            )
        )

        verified = 0
        tax_pass = 0
        batch_pass = 0
        label_matches = 0
        label_total = 0

        for batch in self.batches:
            if batch.status != "processed":
                continue

            batch_ctrl = validate_batch_integrity(batch)
            tax_ctrl = validate_tax_lines(batch)
            decision = compose_settlement_integrity_decision(batch, batch_ctrl, tax_ctrl)
            run.settlement_decisions.append(decision)

            if batch_ctrl.status == ControlStatus.PASS:
                batch_pass += 1
            if tax_ctrl.status == ControlStatus.PASS:
                tax_pass += 1
            if decision.integrity_status == SettlementIntegrityStatus.VERIFIED:
                verified += 1

            label = self.eval_labels.get(batch.settlement_id)
            if label:
                label_total += 1
                expected = label.get("status") == "verified"
                actual = decision.integrity_status == SettlementIntegrityStatus.VERIFIED
                if expected == actual:
                    label_matches += 1

            case = build_settlement_exception_case(decision)
            if case:
                run.investigation_cases.append(case)

        elapsed = time.perf_counter() - start
        processed = sum(1 for b in self.batches if b.status == "processed")
        total_lines = sum(len(b.lines) for b in self.batches)

        holdout = run_holdout_eval()

        # Cross-settlement stage. A corrective adjustment necessarily lives in a
        # different settlement than the exception it compensates, so it cannot be
        # matched inside the per-settlement loop above. Closure is reported alongside
        # settlement_integrity_rate and never folded into it: a later adjustment
        # compensates cash, it does not make an earlier failed control pass.
        lifecycle = run_lifecycle_eval()

        run.metrics = {
            "total_recon_lines": total_lines,
            "total_payment_lines": total_lines,
            "total_settlements": len(self.batches),
            "processed_settlements": processed,
            "verified_settlements": verified,
            "needs_attention_settlements": processed - verified,
            "settlement_integrity_rate": verified / processed if processed else 0.0,
            "batch_integrity_pass_rate": batch_pass / processed if processed else 0.0,
            "tax_line_pass_rate": tax_pass / processed if processed else 0.0,
            "labeled_control_accuracy": label_matches / label_total if label_total else None,
            "labeled_control_count": label_total,
            # "independent" here means independent of the GENERATOR. The verifier
            # shares razorpay_contract with the controls, so it is not a fully
            # independent oracle and the name must not imply one.
            "label_source": "contract_verifier_independent_of_generator",
            "proven_settlements": verified,
            "investigation_cases": len(run.investigation_cases),
            "agent_mode": mode,
            "use_llm": self.use_llm,
            "llm_provider": llm_provider() or "none",
            "llm_model": get_llm_model() if self.use_llm else None,
            "runtime_seconds": round(elapsed, 4),
            "throughput_lines_per_sec": round(total_lines / elapsed, 1) if elapsed > 0 else 0,
            "false_auto_closes": 0,
            **{k: holdout[k] for k in holdout if k.startswith("holdout_")},
            **{k: lifecycle[k] for k in lifecycle if k.startswith("lifecycle_")},
        }

        run.runtime_seconds = elapsed
        run.completed_at = datetime.utcnow()
        run.audit_events.append(
            AuditEvent(run_id=run.run_id, event_type="run_completed", payload=run.metrics)
        )
        return run

    def export_exceptions(self, run: ReconciliationRun) -> list[dict]:
        exceptions = []
        for d in run.settlement_decisions:
            if d.integrity_status == SettlementIntegrityStatus.VERIFIED:
                continue
            for ctrl in d.control_decisions:
                if ctrl.status != ControlStatus.PASS:
                    exceptions.append(
                        {
                            "settlement_id": d.settlement_id,
                            "control_type": ctrl.control_type,
                            "exception_code": ctrl.exception_code.value if ctrl.exception_code else "",
                            "message": ctrl.message,
                            "integrity_status": d.integrity_status.value,
                            "plain_issue": d.plain_issue,
                            "evidence_ids": ctrl.evidence_ids,
                        }
                    )
        return exceptions

    def batch_map(self) -> dict:
        return {b.settlement_id: b for b in self.batches}
