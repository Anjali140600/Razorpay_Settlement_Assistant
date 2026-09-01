"""Razorpay combined recon field contract — shared by generator and controls."""

from __future__ import annotations

GST_NUMERATOR = 18
GST_DENOMINATOR = 118  # fee is GST-inclusive for INR domestic
TAX_TOLERANCE_PAISE = 1
FEE_RATE_DEFAULT = 0.02


def paise(inr: float) -> int:
    return int(round(inr * 100))


def fee_paise_from_amount(amount_paise: int, rate: float = FEE_RATE_DEFAULT) -> int:
    return paise((amount_paise / 100) * rate)


def expected_tax_paise(fee_paise: int) -> int:
    """GST component when fee is inclusive of 18% GST."""
    if fee_paise == 0:
        return 0
    return round(fee_paise * GST_NUMERATOR / GST_DENOMINATOR)


def payment_credit_paise(amount_paise: int, fee_paise: int) -> int:
    return amount_paise - fee_paise


def transfer_debit_paise(amount_paise: int, fee_paise: int) -> int:
    """Transfer lines debit amount + fee per Razorpay recon API."""
    return amount_paise + fee_paise


def batch_net_paise(lines: list[dict]) -> int:
    return sum(int(l.get("credit", 0)) - int(l.get("debit", 0)) for l in lines)


def validate_payment_line(line: dict) -> list[str]:
    """Return human-readable violations for a payment line."""
    errors: list[str] = []
    amount = int(line["amount"])
    fee = int(line["fee"])
    tax = int(line["tax"])
    credit = int(line["credit"])
    debit = int(line["debit"])

    expected_credit = payment_credit_paise(amount, fee)
    expected_tax = expected_tax_paise(fee)

    if debit != 0:
        errors.append(f"{line['entity_id']}: payment debit must be 0")
    if credit != expected_credit:
        errors.append(f"{line['entity_id']}: credit {credit} != amount - fee ({expected_credit})")
    if abs(tax - expected_tax) > TAX_TOLERANCE_PAISE:
        errors.append(f"{line['entity_id']}: tax {tax} != expected {expected_tax} (±{TAX_TOLERANCE_PAISE})")
    return errors


def validate_transfer_line(line: dict) -> list[str]:
    errors: list[str] = []
    amount = int(line["amount"])
    fee = int(line["fee"])
    tax = int(line["tax"])
    debit = int(line["debit"])
    credit = int(line["credit"])

    expected_debit = transfer_debit_paise(amount, fee)
    expected_tax = expected_tax_paise(fee)

    if credit != 0:
        errors.append(f"{line['entity_id']}: transfer credit must be 0")
    if debit != expected_debit:
        errors.append(f"{line['entity_id']}: debit {debit} != amount + fee ({expected_debit})")
    if abs(tax - expected_tax) > TAX_TOLERANCE_PAISE:
        errors.append(f"{line['entity_id']}: tax {tax} != expected {expected_tax}")
    return errors


def validate_refund_line(line: dict) -> list[str]:
    errors: list[str] = []
    amount = int(line["amount"])
    if int(line["credit"]) != 0:
        errors.append(f"{line['entity_id']}: refund credit must be 0")
    if int(line["debit"]) != amount:
        errors.append(f"{line['entity_id']}: refund debit must equal amount")
    if int(line["fee"]) != 0 or int(line["tax"]) != 0:
        errors.append(f"{line['entity_id']}: refund fee/tax must be 0")
    return errors


def validate_adjustment_line(line: dict) -> list[str]:
    errors: list[str] = []
    amount = int(line["amount"])
    debit = int(line["debit"])
    credit = int(line["credit"])
    if debit and credit:
        errors.append(f"{line['entity_id']}: adjustment cannot have both debit and credit")
    if max(debit, credit) != amount:
        errors.append(f"{line['entity_id']}: adjustment amount must match debit or credit")
    if int(line["fee"]) != 0 or int(line["tax"]) != 0:
        errors.append(f"{line['entity_id']}: adjustment fee/tax must be 0")
    return errors


def validate_line(line: dict) -> list[str]:
    line_type = line.get("type", "payment")
    if line_type == "payment":
        return validate_payment_line(line)
    if line_type == "transfer":
        return validate_transfer_line(line)
    if line_type == "refund":
        return validate_refund_line(line)
    if line_type == "adjustment":
        return validate_adjustment_line(line)
    return [f"{line.get('entity_id')}: unsupported type {line_type}"]
