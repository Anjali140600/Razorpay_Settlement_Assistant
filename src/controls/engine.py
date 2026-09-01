"""Deterministic control engine."""

from __future__ import annotations

from datetime import date, timedelta

from rapidfuzz import fuzz

from src.connectors.loaders import _extract_utr_from_narration
from src.domain.razorpay_contract import (
    TAX_TOLERANCE_PAISE,
    expected_tax_paise,
    payment_credit_paise,
    validate_line,
)
from src.domain.accounts import BANK_ARRIVAL_SLA_DAYS
from src.domain.formatting import format_inr
from src.domain.models import (
    BankEntry,
    CaseOutcome,
    CheckCalculationDetail,
    ControlDecision,
    ControlStatus,
    ExceptionCode,
    InvestigationCase,
    LedgerEntry,
    SettlementBatch,
    SettlementCloseDecision,
    SettlementIntegrityStatus,
    SettlementStatus,
)


BATCH_CHECK_NAME = "Settlement batch amounts add up"
TAX_CHECK_NAME = "Fees & GST lines"


def _batch_calc_detail(
    *,
    formula: str,
    expected_display: str,
    actual_display: str,
    delta_display: str | None,
    line_id: str | None,
    error: str,
) -> CheckCalculationDetail:
    return CheckCalculationDetail(
        check_name=BATCH_CHECK_NAME,
        formula=formula,
        expected_display=expected_display,
        actual_display=actual_display,
        delta_display=delta_display,
        line_id=line_id,
        error=error,
    )


def _tax_calc_detail(
    *,
    formula: str,
    expected_display: str,
    actual_display: str,
    delta_display: str | None,
    line_id: str | None,
    error: str,
) -> CheckCalculationDetail:
    return CheckCalculationDetail(
        check_name=TAX_CHECK_NAME,
        formula=formula,
        expected_display=expected_display,
        actual_display=actual_display,
        delta_display=delta_display,
        line_id=line_id,
        error=error,
    )


def validate_batch_integrity(batch: SettlementBatch) -> ControlDecision:
    """Control 2: sum(credit) - sum(debit) == settlement header amount."""
    if batch.status == "failed":
        return ControlDecision(
            settlement_id=batch.settlement_id,
            control_type="batch_integrity",
            status=ControlStatus.ESCALATED,
            exception_code=ExceptionCode.SETTLEMENT_FAILED,
            message="Settlement failed — no cash movement expected",
        )

    if not batch.lines:
        return ControlDecision(
            settlement_id=batch.settlement_id,
            control_type="batch_integrity",
            status=ControlStatus.FAIL,
            exception_code=ExceptionCode.SETTLEMENT_TOTAL_MISMATCH,
            message="No recon lines for settlement",
        )

    net = batch.net_from_lines
    if net != batch.amount:
        gap = abs(batch.amount - net)
        return ControlDecision(
            settlement_id=batch.settlement_id,
            control_type="batch_integrity",
            status=ControlStatus.FAIL,
            exception_code=ExceptionCode.SETTLEMENT_TOTAL_MISMATCH,
            message=f"Batch mismatch: lines net {net} != header {batch.amount}",
            evidence_ids=[l.entity_id for l in batch.lines],
            calculation_detail=_batch_calc_detail(
                formula="sum(credit) − sum(debit) = header amount",
                expected_display=f"{format_inr(batch.amount)} (header)",
                actual_display=f"{format_inr(net)} (recon lines)",
                delta_display=format_inr(gap),
                line_id=None,
                error="Batch mismatch — lines net does not match settlement header",
            ),
        )

    # Validate payment line semantics
    for line in batch.lines:
        if line.line_type == "payment":
            expected_credit = payment_credit_paise(line.amount, line.fee)
            if line.debit != 0 or line.credit != expected_credit:
                return ControlDecision(
                    settlement_id=batch.settlement_id,
                    control_type="batch_integrity",
                    status=ControlStatus.FAIL,
                    exception_code=ExceptionCode.UNSUPPORTED_LINE_SEMANTICS,
                    message=f"Payment line {line.entity_id} semantics invalid",
                    evidence_ids=[line.entity_id],
                    calculation_detail=_batch_calc_detail(
                        formula="credit = amount − fee; debit = 0",
                        expected_display=f"credit {format_inr(expected_credit)}, debit {format_inr(0)}",
                        actual_display=f"credit {format_inr(line.credit)}, debit {format_inr(line.debit)}",
                        delta_display=None,
                        line_id=line.entity_id,
                        error=f"Payment line {line.entity_id} has invalid debit/credit semantics",
                    ),
                )

    return ControlDecision(
        settlement_id=batch.settlement_id,
        control_type="batch_integrity",
        status=ControlStatus.PASS,
        message="Batch integrity verified",
        evidence_ids=[l.entity_id for l in batch.lines],
        auto_closed=True,
    )


def _line_to_dict(line) -> dict:
    return {
        "entity_id": line.entity_id,
        "type": line.line_type,
        "debit": line.debit,
        "credit": line.credit,
        "amount": line.amount,
        "fee": line.fee,
        "tax": line.tax,
    }


def validate_tax_lines(batch: SettlementBatch) -> ControlDecision:
    """Control: fee, tax, and line semantics follow Razorpay field contract."""
    if not batch.lines:
        return ControlDecision(
            settlement_id=batch.settlement_id,
            control_type="tax_lines",
            status=ControlStatus.PASS,
            message="No lines to validate",
        )

    bad_lines: list[str] = []
    messages: list[str] = []
    for line in batch.lines:
        errors = validate_line(_line_to_dict(line))
        if errors:
            bad_lines.append(line.entity_id)
            messages.extend(errors)

    if bad_lines:
        first = messages[0] if messages else "Fee or GST line invalid"
        line = next(l for l in batch.lines if l.entity_id == bad_lines[0])
        line_dict = _line_to_dict(line)
        exp_tax = expected_tax_paise(line.fee)
        calc_detail: CheckCalculationDetail | None = None
        if "tax" in first and line.fee > 0:
            gap = abs(line.tax - exp_tax)
            calc_detail = _tax_calc_detail(
                formula="tax = round(fee × 18/118)",
                expected_display=f"GST {format_inr(exp_tax)} (fee {format_inr(line.fee)})",
                actual_display=f"GST {format_inr(line.tax)}",
                delta_display=format_inr(gap) if gap else None,
                line_id=line.entity_id,
                error="GST does not match fee × 18/118",
            )
        elif "credit" in first or "debit" in first:
            calc_detail = _tax_calc_detail(
                formula="line debit/credit must match Razorpay field contract",
                expected_display=first.split(": ", 1)[-1] if ": " in first else "contract values",
                actual_display=f"debit {format_inr(line.debit)}, credit {format_inr(line.credit)}",
                delta_display=None,
                line_id=line.entity_id,
                error=first,
            )
        else:
            calc_detail = _tax_calc_detail(
                formula="fee and GST lines follow Razorpay field contract",
                expected_display="valid fee/GST semantics",
                actual_display=first,
                delta_display=None,
                line_id=line.entity_id,
                error=first,
            )
        return ControlDecision(
            settlement_id=batch.settlement_id,
            control_type="tax_lines",
            status=ControlStatus.FAIL,
            exception_code=ExceptionCode.FEE_OR_TAX_MISPOSTED,
            message=first,
            evidence_ids=bad_lines,
            calculation_detail=calc_detail,
        )

    total_fee = sum(l.fee for l in batch.lines)
    total_tax = sum(l.tax for l in batch.lines)
    expected_total_tax = sum(expected_tax_paise(l.fee) for l in batch.lines)
    if abs(total_tax - expected_total_tax) > TAX_TOLERANCE_PAISE * max(len(batch.lines), 1):
        gap = abs(total_tax - expected_total_tax)
        return ControlDecision(
            settlement_id=batch.settlement_id,
            control_type="tax_lines",
            status=ControlStatus.FAIL,
            exception_code=ExceptionCode.FEE_OR_TAX_MISPOSTED,
            message=f"Batch tax rollup {total_tax} != expected {expected_total_tax}",
            evidence_ids=[l.entity_id for l in batch.lines if l.fee > 0],
            calculation_detail=_tax_calc_detail(
                formula="Σ tax on lines = Σ expected_tax(fee)",
                expected_display=f"{format_inr(expected_total_tax)} (expected total GST)",
                actual_display=f"{format_inr(total_tax)} (actual total GST)",
                delta_display=format_inr(gap),
                line_id=None,
                error="Batch GST total does not match sum of expected fee taxes",
            ),
        )

    return ControlDecision(
        settlement_id=batch.settlement_id,
        control_type="tax_lines",
        status=ControlStatus.PASS,
        message="Fees and GST lines verified",
        evidence_ids=[l.entity_id for l in batch.lines if l.fee > 0],
        auto_closed=True,
    )


def compose_settlement_integrity_decision(
    batch: SettlementBatch,
    batch_ctrl: ControlDecision,
    tax_ctrl: ControlDecision,
) -> SettlementCloseDecision:
    """Two-check decision: batch integrity + fee/GST lines."""
    controls = [batch_ctrl, tax_ctrl]
    all_pass = all(c.status == ControlStatus.PASS for c in controls)

    if all_pass:
        integrity = SettlementIntegrityStatus.VERIFIED
        status = SettlementStatus.PROVEN
        plain_issue = ""
    else:
        integrity = SettlementIntegrityStatus.NEEDS_ATTENTION
        status = SettlementStatus.REVIEW_REQUIRED
        if batch_ctrl.status != ControlStatus.PASS:
            plain_issue = "Settlement batch amounts don't add up"
        elif tax_ctrl.status != ControlStatus.PASS:
            plain_issue = "Fees & GST issue"
            if tax_ctrl.evidence_ids:
                plain_issue += f" on {tax_ctrl.evidence_ids[0]}"
        else:
            plain_issue = "Needs attention"

    return SettlementCloseDecision(
        settlement_id=batch.settlement_id,
        status=status,
        integrity_status=integrity,
        batch_integrity=batch_ctrl.status,
        tax_lines=tax_ctrl.status,
        bank_receipt=ControlStatus.PASS,
        gl_posting=ControlStatus.PASS,
        net_amount_paise=batch.amount,
        utr=batch.utr,
        processed_at=batch.processed_at,
        control_decisions=controls,
        plain_issue=plain_issue,
    )


def build_settlement_exception_case(
    decision: SettlementCloseDecision,
) -> InvestigationCase | None:
    failed = [c for c in decision.control_decisions if c.status != ControlStatus.PASS]
    if not failed:
        return None

    codes = [c.exception_code for c in failed if c.exception_code]
    return InvestigationCase(
        settlement_id=decision.settlement_id,
        exception_codes=codes,
        control_decisions=failed,
        outcome=CaseOutcome.UNRESOLVED,
    )


def match_bank_credit(
    batch: SettlementBatch,
    bank_entries: list[BankEntry],
    eval_date: date,
) -> tuple[ControlDecision, BankEntry | None, list[dict]]:
    """Control 3: Match settlement to bank credit via UTR and amount."""
    if batch.status != "processed":
        return (
            ControlDecision(
                settlement_id=batch.settlement_id,
                control_type="bank_receipt",
                status=ControlStatus.PENDING,
                message="Settlement not yet processed",
            ),
            None,
            [],
        )

    candidates: list[tuple[BankEntry, int, str]] = []
    normalized_utr = _normalize_utr(batch.utr)

    for entry in bank_entries:
        if entry.amount != batch.amount:
            continue
        entry_utr = _normalize_utr(entry.utr or _extract_utr_from_narration(entry.narration))
        score = 0
        reason = ""
        if normalized_utr and entry_utr:
            if normalized_utr == entry_utr:
                score = 100
                reason = "exact_utr"
            elif normalized_utr in entry_utr or entry_utr in normalized_utr:
                score = 85
                reason = "partial_utr"
            else:
                fuzz_score = fuzz.partial_ratio(normalized_utr, entry_utr)
                if fuzz_score >= 80:
                    score = fuzz_score
                    reason = "fuzzy_utr"
        elif normalized_utr:
            # UTR in narration only
            narr_upper = entry.narration.upper()
            if normalized_utr in narr_upper.replace(" ", ""):
                score = 75
                reason = "utr_in_narration"
        candidates.append((entry, score, reason))

    candidates.sort(key=lambda x: x[1], reverse=True)
    candidate_info = [
        {
            "entry_id": c[0].entry_id,
            "score": c[1],
            "reason": c[2],
            "narration": c[0].narration[:80],
            "utr": c[0].utr,
        }
        for c in candidates[:5]
    ]

    # Exact UTR + amount match → auto-close
    strong = [c for c in candidates if c[1] >= 85]
    if len(strong) == 1:
        entry = strong[0][0]
        return (
            ControlDecision(
                settlement_id=batch.settlement_id,
                control_type="bank_receipt",
                status=ControlStatus.PASS,
                message=f"Bank credit matched via {strong[0][2]}",
                evidence_ids=[entry.entry_id],
                auto_closed=True,
            ),
            entry,
            candidate_info,
        )

    if len(strong) > 1:
        return (
            ControlDecision(
                settlement_id=batch.settlement_id,
                control_type="bank_receipt",
                status=ControlStatus.REVIEW,
                exception_code=ExceptionCode.BANK_REFERENCE_AMBIGUOUS,
                message="Multiple bank candidates with similar UTR evidence",
                evidence_ids=[c[0].entry_id for c in strong],
            ),
            None,
            candidate_info,
        )

    # Amount matches but no UTR — ambiguous
    amount_matches = [c for c in candidates if c[1] == 0 and c[0].amount == batch.amount]
    if len(amount_matches) > 1:
        return (
            ControlDecision(
                settlement_id=batch.settlement_id,
                control_type="bank_receipt",
                status=ControlStatus.REVIEW,
                exception_code=ExceptionCode.BANK_REFERENCE_AMBIGUOUS,
                message="Multiple same-amount bank entries without UTR discriminator",
                evidence_ids=[c[0].entry_id for c in amount_matches],
            ),
            None,
            candidate_info,
        )

    if len(amount_matches) == 1 and not normalized_utr:
        return (
            ControlDecision(
                settlement_id=batch.settlement_id,
                control_type="bank_receipt",
                status=ControlStatus.REVIEW,
                exception_code=ExceptionCode.BANK_REFERENCE_AMBIGUOUS,
                message="Single amount match but no UTR confirmation",
                evidence_ids=[amount_matches[0][0].entry_id],
            ),
            None,
            candidate_info,
        )

    # No match — check SLA
    if batch.processed_at:
        processed_date = batch.processed_at.date()
        sla_deadline = processed_date + timedelta(days=BANK_ARRIVAL_SLA_DAYS)
        if eval_date <= sla_deadline:
            return (
                ControlDecision(
                    settlement_id=batch.settlement_id,
                    control_type="bank_receipt",
                    status=ControlStatus.PENDING,
                    exception_code=ExceptionCode.PROCESSED_AWAITING_BANK,
                    message=f"Processed settlement awaiting bank credit (SLA until {sla_deadline})",
                ),
                None,
                candidate_info,
            )
        return (
            ControlDecision(
                settlement_id=batch.settlement_id,
                control_type="bank_receipt",
                status=ControlStatus.ESCALATED,
                exception_code=ExceptionCode.MISSING_BANK_CREDIT,
                message=f"No bank credit after SLA ({BANK_ARRIVAL_SLA_DAYS} days)",
            ),
            None,
            candidate_info,
        )

    return (
        ControlDecision(
            settlement_id=batch.settlement_id,
            control_type="bank_receipt",
            status=ControlStatus.FAIL,
            exception_code=ExceptionCode.MISSING_BANK_CREDIT,
            message="No matching bank credit found",
        ),
        None,
        candidate_info,
    )


def validate_gl_posting(
    batch: SettlementBatch,
    ledger_entries: list[LedgerEntry],
) -> ControlDecision:
    """Control 4: Verify required GL entries for settlement."""
    settlement_id = batch.settlement_id
    related = [e for e in ledger_entries if e.settlement_id == settlement_id]

    # Required: settlement transit journal (1210 debit, 1200 credit)
    transit_debit = sum(e.debit for e in related if e.account_code == "1210")
    transit_credit_gc = sum(e.credit for e in related if e.account_code == "1200")
    has_transit = transit_debit >= batch.amount and transit_credit_gc >= batch.amount

    # Required: fee posting if fees exist
    total_fee = sum(l.fee for l in batch.lines if l.line_type == "payment")
    fee_debit = sum(e.debit for e in related if e.account_code in ("4100", "4110"))
    has_fee = total_fee == 0 or fee_debit >= total_fee

    if not has_transit and total_fee > 0 and not has_fee:
        return ControlDecision(
            settlement_id=settlement_id,
            control_type="gl_posting",
            status=ControlStatus.FAIL,
            exception_code=ExceptionCode.LEDGER_ENTRY_MISSING,
            message="Missing settlement transit and fee journal entries",
            evidence_ids=[e.entry_id for e in related],
        )

    if not has_transit:
        return ControlDecision(
            settlement_id=settlement_id,
            control_type="gl_posting",
            status=ControlStatus.FAIL,
            exception_code=ExceptionCode.LEDGER_ENTRY_MISSING,
            message="Missing settlement-in-transit reclassification journal",
            evidence_ids=[e.entry_id for e in related],
        )

    if total_fee > 0 and not has_fee:
        return ControlDecision(
            settlement_id=settlement_id,
            control_type="gl_posting",
            status=ControlStatus.FAIL,
            exception_code=ExceptionCode.LEDGER_ENTRY_MISSING,
            message=f"Missing fee journal (expected {total_fee} paise)",
            evidence_ids=[e.entry_id for e in related],
        )

    return ControlDecision(
        settlement_id=settlement_id,
        control_type="gl_posting",
        status=ControlStatus.PASS,
        message="GL postings verified",
        evidence_ids=[e.entry_id for e in related],
        auto_closed=True,
    )


def compose_settlement_decision(
    batch: SettlementBatch,
    batch_ctrl: ControlDecision,
    bank_ctrl: ControlDecision,
    gl_ctrl: ControlDecision,
    bank_entry: BankEntry | None,
) -> SettlementCloseDecision:
    controls = [batch_ctrl, bank_ctrl, gl_ctrl]
    all_green = all(c.status == ControlStatus.PASS for c in controls)

    if all_green:
        status = SettlementStatus.PROVEN
    elif bank_ctrl.exception_code == ExceptionCode.PROCESSED_AWAITING_BANK:
        status = SettlementStatus.PENDING_BANK_WITHIN_POLICY
    elif bank_ctrl.status == ControlStatus.ESCALATED or gl_ctrl.status == ControlStatus.FAIL:
        status = SettlementStatus.REVIEW_REQUIRED
        if bank_ctrl.exception_code == ExceptionCode.MISSING_BANK_CREDIT:
            status = SettlementStatus.ESCALATED
    elif bank_ctrl.status == ControlStatus.REVIEW:
        status = SettlementStatus.REVIEW_REQUIRED
    elif batch_ctrl.status != ControlStatus.PASS:
        status = SettlementStatus.UNRESOLVED
    else:
        status = SettlementStatus.REVIEW_REQUIRED

    return SettlementCloseDecision(
        settlement_id=batch.settlement_id,
        status=status,
        batch_integrity=batch_ctrl.status,
        bank_receipt=bank_ctrl.status,
        gl_posting=gl_ctrl.status,
        net_amount_paise=batch.amount,
        utr=batch.utr,
        bank_entry_id=bank_entry.entry_id if bank_entry else None,
        control_decisions=controls,
    )


def build_investigation_case(
    decision: SettlementCloseDecision,
    bank_candidates: list[dict],
) -> InvestigationCase | None:
    failed = [
        c
        for c in decision.control_decisions
        if c.status in (ControlStatus.FAIL, ControlStatus.REVIEW, ControlStatus.ESCALATED, ControlStatus.PENDING)
    ]
    if not failed:
        return None

    codes = [c.exception_code for c in failed if c.exception_code]
    outcome = CaseOutcome.UNRESOLVED
    if ExceptionCode.PROCESSED_AWAITING_BANK in codes:
        outcome = CaseOutcome.PENDING_EVIDENCE
    elif ExceptionCode.MISSING_BANK_CREDIT in codes:
        outcome = CaseOutcome.ESCALATED

    return InvestigationCase(
        settlement_id=decision.settlement_id,
        exception_codes=codes,
        control_decisions=failed,
        outcome=outcome,
        bank_candidates=bank_candidates,
    )


def _normalize_utr(utr: str) -> str:
    return utr.upper().replace(" ", "").replace("-", "")
