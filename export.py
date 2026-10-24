"""
CSV export rendering for the transactions page.

Produces CSV in the same shape as Rocket Money's transaction export, so the
result can be re-imported into Rocket Money (or any tool that reads that
format) without a custom import. The header row below must keep exactly that
column layout.

Column mapping from rock_money data:
  Date / Original Date  -> transactions.date
  Account Type          -> accounts.type/subtype, mapped to Rocket Money labels
  Account Name          -> accounts.name
  Account Number        -> accounts.mask (last four digits)
  Institution Name      -> items.institution_name
  Name                  -> merchant_name, falling back to the raw name
  Custom Name           -> (not tracked — left blank)
  Amount                -> raw amount (positive = spend, negative = income)
  Description           -> the raw Plaid transaction name
  Category              -> effective category (override > Plaid), mapped to
                           Rocket Money's category vocabulary
  Note                  -> transaction_notes.note
  Ignored From          -> (not tracked — left blank)
  Tax Deductible        -> (not tracked — left blank)
  Transaction Tags      -> transaction_tags, joined with ", "
"""

import csv
import io

# Exact header of a Rocket Money CSV export.
CSV_HEADER = [
    "Date",
    "Original Date",
    "Account Type",
    "Account Name",
    "Account Number",
    "Institution Name",
    "Name",
    "Custom Name",
    "Amount",
    "Description",
    "Category",
    "Note",
    "Ignored From",
    "Tax Deductible",
    "Transaction Tags",
]

# Effective categories whose Rocket Money label differs from a plain title
# case (everything else falls back to title case in rocket_money_category()).
_CATEGORY_MAP = {
    "ENTERTAINMENT & RECREATION": "Entertainment & Rec.",
    "AUTO & TRANSPORTATION": "Auto & Transport",
    "CREDIT PAYMENT": "Credit Card Payment",
    "INTERNAL TRANSFER": "Internal Transfers",
    "TRANSFER_IN": "Internal Transfers",
    "TRANSFER_OUT": "Internal Transfers",
}


def format_amount(value) -> str:
    """
    Render an amount the way Rocket Money does: no currency symbol, no
    thousands separators, trailing zeros stripped ('102.60' -> '102.6',
    '3.00' -> '3').
    """
    s = f"{float(value):.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def rocket_money_category(category: str | None) -> str:
    """
    Map an effective category to Rocket Money's category vocabulary.
    Unknown/custom categories fall back to title case with underscores as
    spaces ('CREDIT_CARD_PAYMENT' -> 'Credit Card Payment').
    """
    if not category:
        return ""
    if category in _CATEGORY_MAP:
        return _CATEGORY_MAP[category]
    return category.replace("_", " ").title()


def account_type_label(account_type: str | None, account_subtype: str | None) -> str:
    """
    Map a Plaid account type/subtype to Rocket Money's account type labels
    (deposit accounts show as 'Cash', e.g. 'Cash' for checking/savings).
    Input is case-insensitive (Plaid sends uppercase).
    """
    t = (account_type or "").upper()
    s = (account_subtype or "").upper()
    if t == "CREDIT" or s == "CREDIT_CARD":
        return "Credit Card"
    if t == "DEPOSITORY" or s in {"CHECKING", "SAVINGS", "MONEY_MARKET", "REWARD"}:
        return "Cash"
    if t == "LOAN" or s in {
        "MORTGAGE",
        "STUDENT_LOAN",
        "AUTO_LOAN",
        "CREDIT_LOAN",
        "PERSONAL_LOAN",
    }:
        return "Loan"
    if t == "INVESTMENT":
        return "Investment"
    if t == "PROPERTY":
        return "Property"
    return t.title() if t else "Other"


def render_transactions_csv(rows: list[dict]) -> str:
    """
    Render export rows (as returned by analytics.get_export_rows) to CSV text
    with LF line endings, matching Rocket Money's export file.

    Each row dict needs: date, amount, name, merchant_name, effective_category,
    account_name, account_mask, account_type, account_subtype, institution_name,
    note, tags (list of str). Rows are written in the order given — pass them
    oldest-first, like Rocket Money does.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for r in rows:
        raw_date = r.get("date")
        date_str = (
            raw_date.strftime("%Y-%m-%d")
            if hasattr(raw_date, "strftime")
            else str(raw_date or "")
        )
        name = r.get("merchant_name") or r.get("name") or ""
        writer.writerow(
            [
                date_str,  # Date
                date_str,  # Original Date
                account_type_label(r.get("account_type"), r.get("account_subtype")),
                r.get("account_name") or "",  # Account Name
                r.get("account_mask") or "",  # Account Number
                r.get("institution_name") or "",  # Institution Name
                name,  # Name
                "",  # Custom Name — not tracked
                format_amount(r.get("amount") or 0),  # Amount
                r.get("name") or "",  # Description
                rocket_money_category(r.get("effective_category")) or "Uncategorized",
                r.get("note") or "",  # Note
                "",  # Ignored From — not tracked
                "",  # Tax Deductible — not tracked
                ", ".join(r.get("tags") or []),  # Transaction Tags
            ]
        )
    return buf.getvalue()
