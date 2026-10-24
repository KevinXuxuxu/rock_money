"""Tests for export.py — pure CSV rendering, no DB involved."""

import csv
import io
from datetime import date
from pathlib import Path

from export import (
    CSV_HEADER,
    account_type_label,
    format_amount,
    render_transactions_csv,
    rocket_money_category,
)

EXAMPLE_CSV = Path(__file__).resolve().parent.parent / "example_output.csv"


class TestFormatAmount:
    def test_two_decimals_unchanged(self):
        assert format_amount(44.84) == "44.84"

    def test_trailing_zero_stripped(self):
        assert format_amount(102.60) == "102.6"

    def test_whole_number(self):
        assert format_amount(3.0) == "3"

    def test_negative(self):
        assert format_amount(-40.8) == "-40.8"

    def test_zero(self):
        assert format_amount(0) == "0"


class TestRocketMoneyCategory:
    def test_title_case_passthrough(self):
        assert rocket_money_category("GROCERIES") == "Groceries"
        assert rocket_money_category("INVESTMENT") == "Investment"
        assert rocket_money_category("INCOME") == "Income"

    def test_underscores_become_spaces(self):
        assert rocket_money_category("CREDIT_CARD_PAYMENT") == "Credit Card Payment"
        assert rocket_money_category("LOAN_PAYMENT") == "Loan Payment"

    def test_explicit_mappings(self):
        assert rocket_money_category("INTERNAL TRANSFER") == "Internal Transfers"
        assert rocket_money_category("CREDIT PAYMENT") == "Credit Card Payment"
        assert (
            rocket_money_category("ENTERTAINMENT & RECREATION")
            == "Entertainment & Rec."
        )
        assert rocket_money_category("AUTO & TRANSPORTATION") == "Auto & Transport"
        assert rocket_money_category("TRANSFER_IN") == "Internal Transfers"
        assert rocket_money_category("TRANSFER_OUT") == "Internal Transfers"

    def test_empty(self):
        assert rocket_money_category(None) == ""
        assert rocket_money_category("") == ""


class TestAccountTypeLabel:
    def test_deposit_accounts_are_cash(self):
        assert account_type_label("DEPOSITORY", "CHECKING") == "Cash"
        assert account_type_label("DEPOSITORY", "SAVINGS") == "Cash"
        assert account_type_label("DEPOSITORY", None) == "Cash"

    def test_credit_card(self):
        assert account_type_label("CREDIT", "CREDIT_CARD") == "Credit Card"
        assert account_type_label("CREDIT", None) == "Credit Card"

    def test_loans(self):
        assert account_type_label("LOAN", "MORTGAGE") == "Loan"
        assert account_type_label("LOAN", "AUTO_LOAN") == "Loan"
        assert account_type_label("LOAN", None) == "Loan"

    def test_other_types(self):
        assert account_type_label("INVESTMENT", None) == "Investment"
        assert account_type_label("PROPERTY", None) == "Property"

    def test_case_insensitive(self):
        assert account_type_label("depository", "checking") == "Cash"
        assert account_type_label("credit", "credit_card") == "Credit Card"

    def test_unknown(self):
        assert account_type_label(None, None) == "Other"


class TestRenderTransactionsCsv:
    def test_header_matches_rocket_money_example(self):
        """The header must exactly match the shipped Rocket Money sample."""
        with open(EXAMPLE_CSV) as f:
            expected = f.readline().strip()
        assert CSV_HEADER == expected.split(",")

    def test_empty_rows_header_only(self):
        out = render_transactions_csv([])
        assert out == ",".join(CSV_HEADER) + "\n"

    def test_lf_line_endings(self):
        out = render_transactions_csv([self._row()])
        assert "\r" not in out

    def test_row_values(self):
        rows = list(csv.reader(io.StringIO(render_transactions_csv([self._row()]))))
        assert len(rows) == 2
        r = rows[1]
        assert r[0] == "2026-01-15"  # Date
        assert r[1] == "2026-01-15"  # Original Date
        assert r[2] == "Cash"  # Account Type
        assert r[3] == "Checking"  # Account Name
        assert r[4] == "1234"  # Account Number (mask)
        assert r[5] == "Test Bank"  # Institution Name
        assert r[6] == "QFC #5807"  # Name (merchant_name)
        assert r[7] == ""  # Custom Name
        assert r[8] == "102.6"  # Amount (trailing zero stripped)
        assert r[9] == "QFC 5807 SEATTLE WA"  # Description (raw name)
        assert r[10] == "Groceries"  # Category
        assert r[11] == "weekly shop"  # Note
        assert r[12] == ""  # Ignored From
        assert r[13] == ""  # Tax Deductible
        assert r[14] == "bulk, groceries"  # Tags joined

    def test_name_falls_back_to_raw_name(self):
        row = self._row(merchant_name=None)
        rows = list(csv.reader(io.StringIO(render_transactions_csv([row]))))
        assert rows[1][6] == "QFC 5807 SEATTLE WA"

    def test_missing_category_becomes_uncategorized(self):
        row = self._row(effective_category=None)
        rows = list(csv.reader(io.StringIO(render_transactions_csv([row]))))
        assert rows[1][10] == "Uncategorized"

    def test_comma_in_field_is_quoted_and_round_trips(self):
        row = self._row(merchant_name="PAU HANA POKE CO., LLC")
        rows = list(csv.reader(io.StringIO(render_transactions_csv([row]))))
        assert rows[1][6] == "PAU HANA POKE CO., LLC"

    def test_date_object_and_string_both_render(self):
        obj_row = self._row(date=date(2026, 1, 15))
        str_row = self._row(date="2026-01-15")
        rows = list(
            csv.reader(io.StringIO(render_transactions_csv([obj_row, str_row])))
        )
        assert rows[1][0] == "2026-01-15"
        assert rows[2][0] == "2026-01-15"

    def test_row_order_is_preserved(self):
        rows = list(
            csv.reader(
                io.StringIO(
                    render_transactions_csv(
                        [
                            self._row(date="2026-01-01", name="A"),
                            self._row(date="2026-01-02", name="B"),
                        ]
                    )
                )
            )
        )
        assert rows[1][0] == "2026-01-01"
        assert rows[2][0] == "2026-01-02"

    @staticmethod
    def _row(**overrides) -> dict:
        base = {
            "transaction_id": "t1",
            "date": "2026-01-15",
            "amount": 102.6,
            "name": "QFC 5807 SEATTLE WA",
            "merchant_name": "QFC #5807",
            "effective_category": "GROCERIES",
            "account_name": "Checking",
            "account_mask": "1234",
            "account_type": "DEPOSITORY",
            "account_subtype": "CHECKING",
            "institution_name": "Test Bank",
            "note": "weekly shop",
            "tags": ["bulk", "groceries"],
        }
        return {**base, **overrides}
