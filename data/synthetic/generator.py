"""Generate realistic Razorpay-shaped merchant mess dataset + honest failure mix.

Outputs:
  - data/synthetic/demo/settlements.json, recon.json, manifest.json
  - data/eval_labels.json (via independent_verifier — not inline generator truth)

Independent holdout (NOT from this generator): data/fixtures/holdout/
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.domain.razorpay_contract import (
    batch_net_paise,
    expected_tax_paise,
    fee_paise_from_amount,
    paise,
    payment_credit_paise,
    transfer_debit_paise,
)
from src.eval.independent_verifier import compute_expected_label, verify_labels_against_contract

BASE_DATE = date(2026, 8, 1)
METHODS = ("upi", "card", "netbanking", "wallet")


def generate_demo_dataset(output_dir: Path, seed: int = 42, repo_root: Path | None = None) -> dict:
    random.seed(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    repo_root = repo_root or output_dir.parent.parent.parent

    settlements: list[dict] = []
    recon_lines: list[dict] = []
    line_counter = 0
    payment_counter = 0
    unix_line_ids: set[str] = set()

    def _ts(day_offset: int, hour: int = 0, use_unix: bool = False) -> str | int:
        dt = datetime.combine(BASE_DATE + timedelta(days=day_offset), datetime.min.time()) + timedelta(hours=hour)
        if use_unix:
            return int(dt.timestamp())
        return dt.isoformat()

    def _line_base(settlement_id: str, utr: str, proc_day: int, entity_id: str) -> dict:
        use_unix = entity_id in unix_line_ids or random.random() < 0.35
        return {
            "currency": "INR",
            "on_hold": False,
            "settled": True,
            "settlement_id": settlement_id,
            "settlement_utr": utr,
            "settled_at": _ts(proc_day, use_unix=use_unix),
        }

    def add_payment(
        settlement_id: str,
        utr: str,
        proc_day: int,
        amount_inr: float,
        *,
        fee_paise_override: int | None = None,
        tax_paise_override: int | None = None,
        credit_override: int | None = None,
        pay_idx: int = 0,
        method: str | None = None,
        zero_fee: bool = False,
    ) -> str:
        nonlocal line_counter, payment_counter
        amount = paise(amount_inr)
        if zero_fee:
            fee, tax = 0, 0
        else:
            fee = fee_paise_override if fee_paise_override is not None else fee_paise_from_amount(amount)
            tax = tax_paise_override if tax_paise_override is not None else expected_tax_paise(fee)
        credit = credit_override if credit_override is not None else payment_credit_paise(amount, fee)
        payment_counter += 1
        line_counter += 1
        eid = f"pay_{settlement_id}_{pay_idx}"
        if random.random() < 0.35:
            unix_line_ids.add(eid)
        recon_lines.append(
            {
                **_line_base(settlement_id, utr, proc_day, eid),
                "entity_id": eid,
                "type": "payment",
                "debit": 0,
                "credit": credit,
                "amount": amount,
                "fee": fee,
                "tax": tax,
                "created_at": _ts(proc_day - 1, hour=random.randint(0, 23), use_unix=eid in unix_line_ids),
                "payment_id": None,
                "order_id": f"ord_{line_counter}",
                "method": method or random.choice(METHODS),
            }
        )
        return eid

    def add_pending_payment(
        captured_day: int,
        amount_inr: float,
        *,
        idx: int,
        instant_eligible: str,
        method: str | None = None,
    ) -> None:
        """A payment captured but not yet settled — no settlement_id, no UTR."""
        nonlocal line_counter, payment_counter
        amount = paise(amount_inr)
        payment_counter += 1
        line_counter += 1
        eid = f"pay_pending_{idx:03d}"
        cycle_type = "instant_eligible" if instant_eligible == "yes" else "standard"
        recon_lines.append(
            {
                "currency": "INR",
                "on_hold": False,
                "settled": False,
                "settlement_id": None,
                "settlement_utr": None,
                "settled_at": None,
                "entity_id": eid,
                "type": "payment",
                "debit": 0,
                "credit": 0,
                "amount": amount,
                "fee": 0,
                "tax": 0,
                "created_at": _ts(captured_day, hour=random.randint(0, 23)),
                "captured_at": _ts(captured_day, hour=random.randint(0, 23)),
                "payment_id": None,
                "order_id": f"ord_pending_{idx}",
                "method": method or random.choice(METHODS),
                "cycle_type": cycle_type,
                "instant_eligible": instant_eligible,
            }
        )

    def add_refund(
        settlement_id: str,
        utr: str,
        proc_day: int,
        amount_inr: float,
        linked_payment_id: str,
        idx: int,
        *,
        debit_override: int | None = None,
    ) -> None:
        nonlocal line_counter
        amount = paise(amount_inr)
        debit = debit_override if debit_override is not None else amount
        line_counter += 1
        eid = f"rfnd_{settlement_id}_{idx}"
        if random.random() < 0.35:
            unix_line_ids.add(eid)
        recon_lines.append(
            {
                **_line_base(settlement_id, utr, proc_day, eid),
                "entity_id": eid,
                "type": "refund",
                "debit": debit,
                "credit": 0,
                "amount": amount,
                "fee": 0,
                "tax": 0,
                "created_at": _ts(proc_day - 1, use_unix=eid in unix_line_ids),
                "payment_id": linked_payment_id,
                "order_id": f"ord_ref_{line_counter}",
                "method": random.choice(METHODS),
            }
        )

    def add_transfer(
        settlement_id: str,
        utr: str,
        proc_day: int,
        amount_inr: float,
        linked_payment_id: str,
        idx: int,
        *,
        tax_override: int | None = None,
    ) -> None:
        nonlocal line_counter
        amount = paise(amount_inr)
        fee = fee_paise_from_amount(amount)
        tax = tax_override if tax_override is not None else expected_tax_paise(fee)
        debit = transfer_debit_paise(amount, fee)
        line_counter += 1
        eid = f"trf_{settlement_id}_{idx}"
        recon_lines.append(
            {
                **_line_base(settlement_id, utr, proc_day, eid),
                "entity_id": eid,
                "type": "transfer",
                "debit": debit,
                "credit": 0,
                "amount": amount,
                "fee": fee,
                "tax": tax,
                "created_at": _ts(proc_day - 1, use_unix=False),
                "payment_id": linked_payment_id,
                "method": None,
            }
        )

    def add_adjustment(
        settlement_id: str,
        utr: str,
        proc_day: int,
        amount_inr: float,
        description: str,
        idx: int,
        *,
        debit: bool = False,
        reference_settlement_id: str | None = None,
    ) -> None:
        nonlocal line_counter
        amount = paise(amount_inr)
        line_counter += 1
        eid = f"adj_{settlement_id}_{idx}"
        recon_lines.append(
            {
                **_line_base(settlement_id, utr, proc_day, eid),
                "entity_id": eid,
                "type": "adjustment",
                "debit": amount if debit else 0,
                "credit": 0 if debit else amount,
                "amount": amount,
                "fee": 0,
                "tax": 0,
                "created_at": _ts(proc_day - 1, use_unix=False),
                "description": description,
                "method": None,
                "reference_settlement_id": reference_settlement_id,
            }
        )

    def finalize_settlement(sid: str, utr: str, proc_day: int, net_override: int | None = None) -> None:
        lines = [l for l in recon_lines if l["settlement_id"] == sid]
        net = net_override if net_override is not None else batch_net_paise(lines)
        settlements.append(
            {
                "id": sid,
                "amount": net,
                "utr": utr,
                "status": "processed",
                "processed_at": _ts(proc_day),
            }
        )

    # --- Profile: everyday D2C (18 settlements, varied volume) ---
    for i in range(18):
        sid = f"setl_merchant_d2c_{i:03d}"
        utr = f"UTR2026080{i:05d}D2C"
        proc_day = i + 1
        n = random.randint(3, 8)
        for j in range(n):
            add_payment(sid, utr, proc_day, random.uniform(199, 4999), pay_idx=j)
        if i % 5 == 0:
            pid = f"pay_{sid}_0"
            add_refund(sid, utr, proc_day, random.uniform(50, 400), pid, 0)
        finalize_settlement(sid, utr, proc_day)

    # --- Profile: flash sale micro-payments (messy volume) ---
    sid = "setl_messy_flash_sale"
    utr = "UTR20260810001FLASH"
    proc_day = 8
    for j in range(16):
        add_payment(sid, utr, proc_day, random.uniform(49, 299), pay_idx=j, method="upi")
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: SaaS — large tickets + partial refund ---
    sid = "setl_messy_saas"
    utr = "UTR20260810002SAAS"
    proc_day = 9
    p0 = add_payment(sid, utr, proc_day, 24999, pay_idx=0, method="card")
    add_payment(sid, utr, proc_day, 14999, pay_idx=1, method="card")
    add_refund(sid, utr, proc_day, 5000, p0, 0)
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: marketplace transfers ---
    sid = "setl_messy_marketplace"
    utr = "UTR20260810003MKT"
    proc_day = 11
    p0 = add_payment(sid, utr, proc_day, 85000, pay_idx=0)
    add_payment(sid, utr, proc_day, 42000, pay_idx=1)
    add_transfer(sid, utr, proc_day, 35000, p0, 0)
    add_transfer(sid, utr, proc_day, 12000, p0, 1)
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: refund-heavy day (still valid if math correct) ---
    sid = "setl_messy_refund_day"
    utr = "UTR20260810004RFD"
    proc_day = 13
    p0 = add_payment(sid, utr, proc_day, 15000, pay_idx=0)
    p1 = add_payment(sid, utr, proc_day, 22000, pay_idx=1)
    add_payment(sid, utr, proc_day, 8900, pay_idx=2)
    add_refund(sid, utr, proc_day, 3500, p0, 0)
    add_refund(sid, utr, proc_day, 1200, p1, 1)
    add_refund(sid, utr, proc_day, 800, p0, 2)
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: chargebacks / adjustments ---
    sid = "setl_messy_chargebacks"
    utr = "UTR20260810005CBK"
    proc_day = 14
    add_payment(sid, utr, proc_day, 18000, pay_idx=0)
    add_adjustment(sid, utr, proc_day, 450, "Chargeback reversal credit", 0)
    add_adjustment(sid, utr, proc_day, 120, "Manual fee reversal", 1)
    add_adjustment(sid, utr, proc_day, 75, "Dispute hold release", 2, debit=False)
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: zero-fee UPI promo (real merchant pattern) ---
    sid = "setl_messy_zero_fee_upi"
    utr = "UTR20260810006UPI0"
    proc_day = 15
    for j in range(6):
        add_payment(sid, utr, proc_day, random.uniform(100, 2500), pay_idx=j, method="upi", zero_fee=True)
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: rounding edge — passes within ±1 paise ---
    sid = "setl_messy_rounding_ok"
    utr = "UTR20260810007RND"
    proc_day = 16
    fee = fee_paise_from_amount(paise(500))
    tax_ok = expected_tax_paise(fee)
    tax_off_by_one = tax_ok + (1 if tax_ok > 0 else 0)
    add_payment(sid, utr, proc_day, 500, pay_idx=0, fee_paise_override=fee, tax_paise_override=tax_off_by_one)
    add_payment(sid, utr, proc_day, 1200, pay_idx=1)
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: high-ticket B2B ---
    sid = "setl_messy_b2b"
    utr = "UTR20260810008B2B"
    proc_day = 17
    add_payment(sid, utr, proc_day, 125000, pay_idx=0, method="netbanking")
    add_payment(sid, utr, proc_day, 89000, pay_idx=1, method="netbanking")
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: combo mess (everything in one settlement) ---
    sid = "setl_messy_combo"
    utr = "UTR20260810009ALL"
    proc_day = 18
    p0 = add_payment(sid, utr, proc_day, 35000, pay_idx=0)
    add_payment(sid, utr, proc_day, 12000, pay_idx=1, method="wallet")
    add_refund(sid, utr, proc_day, 2000, p0, 0)
    add_transfer(sid, utr, proc_day, 5000, p0, 0)
    add_adjustment(sid, utr, proc_day, 199, "Promo credit", 0)
    finalize_settlement(sid, utr, proc_day)

    # --- Profile: pending payments (captured, not yet settled) ---
    add_pending_payment(30, 499.0, idx=0, instant_eligible="no", method="upi")
    add_pending_payment(31, 12500.0, idx=1, instant_eligible="yes", method="card")
    add_pending_payment(32, 899.0, idx=2, instant_eligible="unknown", method="upi")

    # ========== FAILURES (honest exception list) ==========

    # GST wrong on fee line
    sid = "setl_tax_mismatch"
    utr = "UTR20260809999TAX1"
    proc_day = 10
    add_payment(sid, utr, proc_day, 10000, pay_idx=0)
    add_payment(sid, utr, proc_day, 8500, pay_idx=1)
    bad = next(l for l in recon_lines if l["entity_id"] == "pay_setl_tax_mismatch_1")
    bad["tax"] = bad["tax"] + 200

    lines = [l for l in recon_lines if l["settlement_id"] == sid]
    settlements.append({"id": sid, "amount": batch_net_paise(lines), "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    # Header ≠ recon net (export drift)
    sid = "setl_batch_mismatch"
    utr = "UTR20260808888BCH1"
    proc_day = 12
    add_payment(sid, utr, proc_day, 25000, pay_idx=0)
    add_payment(sid, utr, proc_day, 18000, pay_idx=1)
    true_net = batch_net_paise([l for l in recon_lines if l["settlement_id"] == sid])
    settlements.append({"id": sid, "amount": true_net + 50000, "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    # Payment credit ≠ amount − fee
    sid = "setl_fee_semantic_error"
    utr = "UTR20260807777SEM1"
    proc_day = 19
    add_payment(sid, utr, proc_day, 15000, pay_idx=0, credit_override=14800)
    lines = [l for l in recon_lines if l["settlement_id"] == sid]
    settlements.append({"id": sid, "amount": batch_net_paise(lines), "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    # Refund debit ≠ amount
    sid = "setl_refund_wrong_amount"
    utr = "UTR20260806666RFD1"
    proc_day = 20
    p0 = add_payment(sid, utr, proc_day, 20000, pay_idx=0)
    add_refund(sid, utr, proc_day, 2500, p0, 0, debit_override=3000)
    lines = [l for l in recon_lines if l["settlement_id"] == sid]
    settlements.append({"id": sid, "amount": batch_net_paise(lines), "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    # Transfer tax wrong
    sid = "setl_transfer_tax_wrong"
    utr = "UTR20260805555TRF1"
    proc_day = 21
    p0 = add_payment(sid, utr, proc_day, 50000, pay_idx=0)
    add_transfer(sid, utr, proc_day, 8000, p0, 0, tax_override=999)
    lines = [l for l in recon_lines if l["settlement_id"] == sid]
    settlements.append({"id": sid, "amount": batch_net_paise(lines), "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    # Batch fail: header missing refund impact
    sid = "setl_orphan_header_drift"
    utr = "UTR20260804444ORP1"
    proc_day = 22
    add_payment(sid, utr, proc_day, 30000, pay_idx=0)
    add_payment(sid, utr, proc_day, 15000, pay_idx=1)
    true_net = batch_net_paise([l for l in recon_lines if l["settlement_id"] == sid])
    settlements.append({"id": sid, "amount": true_net + 10000, "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    # ========== TRIAGE SCENARIOS (query auto-resolution vs support escalation) ==========
    # Every shortfall below is the same SETTLEMENT_TOTAL_MISMATCH shape as setl_batch_mismatch
    # above; what differs is the adjustment evidence elsewhere in the same recon feed, which is
    # exactly what src/agent/triage.py inspects to decide auto-compensable vs needs-support.

    # Clean shortfall, later compensated by a matching adjustment on another settlement.
    sid = "setl_short_compensated"
    utr = "UTR20260803333CMP1"
    proc_day = 23
    add_payment(sid, utr, proc_day, 12000, pay_idx=0)
    true_net = batch_net_paise([l for l in recon_lines if l["settlement_id"] == sid])
    settlements.append({"id": sid, "amount": true_net + 3000, "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    fix_sid = "setl_short_compensated_fix"
    fix_utr = "UTR20260803333CMP2"
    fix_day = proc_day + 1
    add_adjustment(fix_sid, fix_utr, fix_day, 30.0, f"Recon correction for {sid}", 0, reference_settlement_id=sid)
    finalize_settlement(fix_sid, fix_utr, fix_day)

    # Clean shortfall, but two adjustments elsewhere both cleanly reference it — ambiguous,
    # so neither auto-binds and a person has to pick the right one.
    sid = "setl_ambiguous_shortfall"
    utr = "UTR20260802222AMB1"
    proc_day = 25
    add_payment(sid, utr, proc_day, 9000, pay_idx=0)
    true_net = batch_net_paise([l for l in recon_lines if l["settlement_id"] == sid])
    settlements.append({"id": sid, "amount": true_net + 4000, "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    fix_a_sid, fix_a_utr = "setl_ambiguous_fix_a", "UTR20260802222AMB2"
    add_adjustment(fix_a_sid, fix_a_utr, proc_day + 1, 40.0, f"Correction for {sid}", 0, reference_settlement_id=sid)
    finalize_settlement(fix_a_sid, fix_a_utr, proc_day + 1)

    fix_b_sid, fix_b_utr = "setl_ambiguous_fix_b", "UTR20260802222AMB3"
    add_adjustment(fix_b_sid, fix_b_utr, proc_day + 1, 40.0, f"Correction for {sid}", 0, reference_settlement_id=sid)
    finalize_settlement(fix_b_sid, fix_b_utr, proc_day + 1)

    # Clean shortfall; an adjustment elsewhere names this settlement but the amount is one
    # paise short — it doesn't cleanly reconcile, so it needs a person, not an auto-claim.
    sid = "setl_unreconciled_shortfall"
    utr = "UTR20260801111UNR1"
    proc_day = 27
    add_payment(sid, utr, proc_day, 7000, pay_idx=0)
    true_net = batch_net_paise([l for l in recon_lines if l["settlement_id"] == sid])
    settlements.append({"id": sid, "amount": true_net + 2500, "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    fix_sid = "setl_unreconciled_fix"
    fix_utr = "UTR20260801111UNR2"
    fix_day = proc_day + 1
    add_adjustment(fix_sid, fix_utr, fix_day, 24.99, f"Partial correction for {sid}", 0, reference_settlement_id=sid)
    finalize_settlement(fix_sid, fix_utr, fix_day)

    # Lines net MORE than the header — the merchant received extra. That's Razorpay's
    # recovery to pursue, never a claim the agent offers to file.
    sid = "setl_over_settled"
    utr = "UTR20260800000OVR1"
    proc_day = 29
    add_payment(sid, utr, proc_day, 20000, pay_idx=0)
    true_net = batch_net_paise([l for l in recon_lines if l["settlement_id"] == sid])
    settlements.append({"id": sid, "amount": true_net - 1500, "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    # A settlement header with no recon lines at all — no evidence to compute a compensable
    # amount from, so it can never be auto-compensable regardless of the header value.
    sid = "setl_no_recon_lines"
    utr = "UTR20260899999ZER1"
    proc_day = 31
    settlements.append({"id": sid, "amount": 5000, "utr": utr, "status": "processed", "processed_at": _ts(proc_day)})

    # --- Labels via independent verifier (not inline generator truth) ---
    eval_labels: dict[str, dict] = {}
    for s in settlements:
        eval_labels[s["id"]] = compute_expected_label(s["id"], int(s["amount"]), recon_lines)

    matches, total, label_errors = verify_labels_against_contract(settlements, recon_lines, eval_labels)
    assert not label_errors, f"Label verification failed: {label_errors}"

    (output_dir / "settlements.json").write_text(json.dumps({"items": settlements}, indent=2))
    (output_dir / "recon.json").write_text(json.dumps({"items": recon_lines}, indent=2))
    activity = [{"id": f"act_{i}", "status": "captured"} for i in range(payment_counter)]
    (output_dir / "activity.json").write_text(json.dumps({"items": activity, "count": payment_counter}, indent=2))

    verified = sum(1 for v in eval_labels.values() if v["status"] == "verified")
    needs = sum(1 for v in eval_labels.values() if v["status"] == "needs_attention")
    exception_ids = [sid for sid, v in eval_labels.items() if v["status"] == "needs_attention"]

    eval_doc = {
        "version": "2",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "hackathon_track": "04_ai_finance_controller",
        "label_source": "independent_verifier",
        "label_verification": {"matches": matches, "total": total},
        "dataset_profile": "realistic_merchant_mess",
        "requirements": {
            "min_recon_lines": 50,
            "min_settlements": 25,
            "exception_settlements": exception_ids,
        },
        "summary": {
            "total_settlements": len(settlements),
            "total_recon_lines": len(recon_lines),
            "verified": verified,
            "needs_attention": needs,
            "integrity_rate": round(verified / len(settlements), 4) if settlements else 0,
            "line_types": _count_line_types(recon_lines),
            "merchant_profiles": [
                "d2c_volume", "flash_sale", "saas", "marketplace", "refund_heavy",
                "chargebacks", "zero_fee_upi", "rounding_edge", "b2b", "combo_mess",
            ],
            "failure_types": [
                "tax_mismatch", "batch_mismatch", "fee_semantic", "refund_wrong",
                "transfer_tax", "header_drift", "already_compensated", "ambiguous_adjustment",
                "unreconciled_adjustment", "over_settlement", "no_recon_lines",
            ],
        },
        "labels": eval_labels,
        "holdout_note": "Independent holdout eval: data/fixtures/holdout/ — NOT from this generator",
    }
    eval_path = repo_root / "data" / "eval_labels.json"
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.write_text(json.dumps(eval_doc, indent=2))

    manifest = {
        "settlements": len(settlements),
        "recon_lines": len(recon_lines),
        "payment_lines": sum(1 for l in recon_lines if l["type"] == "payment"),
        "refund_lines": sum(1 for l in recon_lines if l["type"] == "refund"),
        "transfer_lines": sum(1 for l in recon_lines if l["type"] == "transfer"),
        "adjustment_lines": sum(1 for l in recon_lines if l["type"] == "adjustment"),
        "verified_settlements": verified,
        "exception_settlements": needs,
        "exception_ids": exception_ids,
        "unix_timestamp_lines": sum(1 for l in recon_lines if isinstance(l.get("created_at"), int)),
        "pending_payment_lines": sum(1 for l in recon_lines if l.get("settlement_id") is None),
        "settlement_cycle": {"standard_days": 2, "instant_available": True},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _count_line_types(lines: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in lines:
        t = line.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    stats = generate_demo_dataset(Path(__file__).parent / "demo", repo_root=root)
    print("Generated realistic merchant dataset:", stats)
