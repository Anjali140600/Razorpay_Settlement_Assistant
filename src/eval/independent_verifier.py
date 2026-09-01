"""Independent label verification — ground truth from contract only, not generator logic."""

from __future__ import annotations

from src.domain.razorpay_contract import batch_net_paise, payment_credit_paise, validate_line


def compute_expected_label(settlement_id: str, header_amount: int, lines: list[dict]) -> dict:
    """Derive expected pass/fail from field contract independently of generator."""
    sid_lines = [l for l in lines if l.get("settlement_id") == settlement_id]
    net = batch_net_paise(sid_lines)
    batch_ok = net == header_amount

    for line in sid_lines:
        if line.get("type") == "payment":
            expected_credit = payment_credit_paise(int(line["amount"]), int(line["fee"]))
            if int(line.get("debit", 0)) != 0 or int(line.get("credit", 0)) != expected_credit:
                batch_ok = False

    tax_errors: list[str] = []
    for line in sid_lines:
        tax_errors.extend(validate_line(line))

    tax_ok = len(tax_errors) == 0
    verified = batch_ok and tax_ok

    label: dict = {
        "status": "verified" if verified else "needs_attention",
        "batch_integrity": "pass" if batch_ok else "fail",
        "tax_lines": "pass" if tax_ok else "fail",
        "label_source": "independent_verifier",
        "expected_net_paise": net,
        "header_amount_paise": header_amount,
    }
    if not batch_ok:
        label["reason"] = f"Header {header_amount} != recon net {net}"
    elif not tax_ok:
        label["reason"] = tax_errors[0]
        if sid_lines:
            for line in sid_lines:
                errs = validate_line(line)
                if errs:
                    label["bad_line_id"] = line.get("entity_id")
                    break
    return label


def verify_labels_against_contract(
    settlements: list[dict], recon_lines: list[dict], labels: dict[str, dict]
) -> tuple[int, int, list[str]]:
    """Return matches, total, mismatches."""
    matches = 0
    total = 0
    errors: list[str] = []
    for s in settlements:
        sid = s["id"]
        if sid not in labels:
            continue
        total += 1
        expected = compute_expected_label(sid, int(s["amount"]), recon_lines)
        actual = labels[sid]
        exp_status = expected["status"]
        act_status = actual.get("status")
        if exp_status == act_status and expected["batch_integrity"] == actual.get("batch_integrity") and expected["tax_lines"] == actual.get("tax_lines"):
            matches += 1
        else:
            errors.append(f"{sid}: expected {exp_status}, got {act_status}")
    return matches, total, errors
