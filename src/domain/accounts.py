"""Merchant chart of accounts and journal templates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    account_type: str  # asset, liability, expense, revenue


CHART_OF_ACCOUNTS: dict[str, Account] = {
    "1100": Account("1100", "Bank - Current", "asset"),
    "1200": Account("1200", "Gateway Clearing", "asset"),
    "1210": Account("1210", "Settlement-in-Transit", "asset"),
    "2100": Account("2100", "Customer Receivable", "asset"),
    "4100": Account("4100", "Gateway Fee Expense", "expense"),
    "4110": Account("4110", "Fee Tax Suspense", "expense"),
    "5100": Account("5100", "Customer Refunds", "expense"),
}


@dataclass(frozen=True)
class JournalTemplate:
    template_id: str
    name: str
    description: str
    debit_account: str
    credit_account: str
    # For fee correction: split debit across expense + tax suspense
    split_debit: tuple[str, str] | None = None


JOURNAL_TEMPLATES: dict[str, JournalTemplate] = {
    "missing_fee_posting": JournalTemplate(
        template_id="missing_fee_posting",
        name="Missing fee/tax posting",
        description="Debit fee expense and tax suspense; credit Gateway Clearing",
        debit_account="4100",
        credit_account="1200",
        split_debit=("4100", "4110"),
    ),
    "settlement_transit": JournalTemplate(
        template_id="settlement_transit",
        name="Settlement to transit",
        description="Debit Settlement-in-Transit; credit Gateway Clearing",
        debit_account="1210",
        credit_account="1200",
    ),
    "bank_receipt": JournalTemplate(
        template_id="bank_receipt",
        name="Bank receipt",
        description="Debit Bank; credit Settlement-in-Transit",
        debit_account="1100",
        credit_account="1210",
    ),
    "fee_misposted": JournalTemplate(
        template_id="fee_misposted",
        name="Misclassified fee",
        description="Reclassify fee from wrong account to correct expense",
        debit_account="4100",
        credit_account="4100",  # reclassification handled in action layer
    ),
}

# Bank arrival SLA in working days after settlement processed
BANK_ARRIVAL_SLA_DAYS = 3
