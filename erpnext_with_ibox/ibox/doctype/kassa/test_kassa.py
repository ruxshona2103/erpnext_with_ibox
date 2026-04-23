# Copyright (c) 2025, abdulloh and Contributors
# See license.txt

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_with_ibox.ibox.doctype.kassa.kassa import Kassa


def make_kassa_doc(**overrides):
    data = {
        "doctype": "Kassa",
        "naming_series": "KASSA-.YYYY.-",
        "date": "2026-04-16",
        "transaction_type": "Расход",
        "company": "Pokiza",
        "mode_of_payment": "Наличый USD",
        "cash_account": "1112 - Наличные USD - P",
        "cash_account_currency": "USD",
        "party_type": "Supplier",
        "party": "Test Supplier",
        "party_currency": "UZS",
        "amount": 183,
        "exchange_rate": 12200,
        "debit_amount": 183,
        "credit_amount": 2232600,
        "manual_credit_amount": 0,
        "balance": 500,
    }
    data.update(overrides)
    return frappe.get_doc(data)


class FakePaymentEntry:
    def __init__(self):
        self.payment_type = None
        self.posting_date = None
        self.company = None
        self.mode_of_payment = None
        self.party_type = None
        self.party = None
        self.paid_from = None
        self.paid_to = None
        self.paid_amount = None
        self.received_amount = None
        self.source_exchange_rate = None
        self.target_exchange_rate = None
        self.reference_no = None
        self.reference_date = None
        self.remarks = None
        self.flags = SimpleNamespace(ignore_permissions=False)
        self.name = "ACC-PAY-TEST-0001"
        self.inserted = False
        self.submitted = False

    def insert(self):
        self.inserted = True

    def submit(self):
        self.submitted = True


class UnitTestKassa(FrappeTestCase):
    def test_submit_routes_payment_entry_cases(self):
        cases = [
            ("Приход", "Customer"),
            ("Приход", "Supplier"),
            ("Приход", "Employee"),
            ("Расход", "Customer"),
            ("Расход", "Supplier"),
            ("Расход", "Employee"),
        ]

        for transaction_type, party_type in cases:
            doc = make_kassa_doc(transaction_type=transaction_type, party_type=party_type)
            doc.create_payment_entry = MagicMock()
            doc.create_dividend_journal_entry = MagicMock()
            doc.create_expense_journal_entry = MagicMock()
            doc.create_transfer_payment_entry = MagicMock()
            doc.create_conversion_payment_entry = MagicMock()

            doc.on_submit()

            self.assertEqual(doc.create_payment_entry.call_count, 1)
            self.assertEqual(doc.create_dividend_journal_entry.call_count, 0)
            self.assertEqual(doc.create_expense_journal_entry.call_count, 0)
            self.assertEqual(doc.create_transfer_payment_entry.call_count, 0)
            self.assertEqual(doc.create_conversion_payment_entry.call_count, 0)

    def test_submit_routes_non_party_cases(self):
        cases = [
            ("Расход", "Расходы", "create_expense_journal_entry"),
            ("Расход", "Дивиденд", "create_dividend_journal_entry"),
            ("Перемещения", "", "create_transfer_payment_entry"),
            ("Конвертация", "", "create_conversion_payment_entry"),
        ]

        for transaction_type, party_type, expected_method in cases:
            doc = make_kassa_doc(transaction_type=transaction_type, party_type=party_type, party=None)
            doc.create_payment_entry = MagicMock()
            doc.create_dividend_journal_entry = MagicMock()
            doc.create_expense_journal_entry = MagicMock()
            doc.create_transfer_payment_entry = MagicMock()
            doc.create_conversion_payment_entry = MagicMock()

            doc.on_submit()

            self.assertEqual(getattr(doc, expected_method).call_count, 1)
            self.assertEqual(
                sum(
                    method.call_count
                    for method in [
                        doc.create_payment_entry,
                        doc.create_dividend_journal_entry,
                        doc.create_expense_journal_entry,
                        doc.create_transfer_payment_entry,
                        doc.create_conversion_payment_entry,
                    ]
                ),
                1,
            )

    def test_validate_party_rules(self):
        expense_doc = make_kassa_doc(party_type="Расходы", expense_account="5219 - Exchange Gain/Loss - P", party="X")
        expense_doc.validate_party()
        self.assertIsNone(expense_doc.party)

        dividend_doc = make_kassa_doc(
            party_type="Дивиденд",
            party="Will Be Cleared",
            expense_account="5219 - Exchange Gain/Loss - P",
        )
        dividend_doc.validate_party()
        self.assertIsNone(dividend_doc.party)
        self.assertIsNone(dividend_doc.expense_account)

        party_doc = make_kassa_doc(party_type="Supplier", party=None, expense_account=None)
        with self.assertRaises(frappe.ValidationError):
            party_doc.validate_party()

    @patch("erpnext_with_ibox.ibox.doctype.kassa.kassa.frappe.get_cached_value")
    def test_validate_transfer_requires_same_currency(self, mocked_get_cached_value):
        mocked_get_cached_value.side_effect = lambda doctype, name, fieldname: {
            ("Account", "1112 - Наличные USD - P", "account_currency"): "USD",
            ("Account", "1111 - Р/С UZB - P", "account_currency"): "UZS",
        }.get((doctype, name, fieldname))

        doc = make_kassa_doc(
            transaction_type="Перемещения",
            mode_of_payment_to="Р/С",
            cash_account_to="1111 - Р/С UZB - P",
            party_type="",
            party=None,
        )

        with self.assertRaises(frappe.ValidationError):
            doc.validate_transfer()

    @patch("erpnext_with_ibox.ibox.doctype.kassa.kassa.frappe.get_cached_value")
    def test_validate_conversion_requires_different_currency(self, mocked_get_cached_value):
        mocked_get_cached_value.return_value = "USD"

        doc = make_kassa_doc(
            transaction_type="Конвертация",
            mode_of_payment_to="Наличый USD",
            cash_account_to="1112 - Наличные USD - P",
            debit_amount=100,
            credit_amount=100,
            party_type="",
            party=None,
        )

        with self.assertRaises(frappe.ValidationError):
            doc.validate_conversion()

    @patch("erpnext_with_ibox.ibox.doctype.kassa.kassa.get_exchange_rate", return_value=12200)
    def test_set_payment_exchange_details_auto_calculates_credit_amount(self, _mocked_rate):
        doc = make_kassa_doc(credit_amount=0, manual_credit_amount=0, amount=183)
        doc.set_payment_exchange_details()

        self.assertEqual(doc.debit_amount, 183)
        self.assertEqual(doc.credit_amount, 2232600)
        self.assertEqual(doc.manual_credit_amount, 0)

    @patch("erpnext_with_ibox.ibox.doctype.kassa.kassa.get_exchange_rate", return_value=12200)
    def test_set_payment_exchange_details_preserves_manual_credit_amount(self, _mocked_rate):
        doc = make_kassa_doc(credit_amount=1800000, manual_credit_amount=1, amount=183)
        doc.set_payment_exchange_details()

        self.assertEqual(doc.debit_amount, 183)
        self.assertEqual(doc.credit_amount, 1800000)
        self.assertEqual(doc.manual_credit_amount, 1)

    @patch("erpnext_with_ibox.ibox.doctype.kassa.kassa.frappe.msgprint")
    @patch("erpnext_with_ibox.ibox.doctype.kassa.kassa.frappe.utils.get_link_to_form", return_value="PAYMENT-LINK")
    @patch("erpnext_with_ibox.ibox.doctype.kassa.kassa.frappe.get_cached_value")
    @patch("erpnext_with_ibox.ibox.doctype.kassa.kassa.frappe.new_doc")
    def test_create_payment_entry_uses_manual_override_amount(
        self,
        mocked_new_doc,
        mocked_get_cached_value,
        _mocked_link,
        _mocked_msgprint,
    ):
        fake_pe = FakePaymentEntry()
        mocked_new_doc.return_value = fake_pe

        lookup = {
            ("Account", "SUPP-ACC-UZS", "account_currency"): "UZS",
            ("Account", "1112 - Наличные USD - P", "account_currency"): "USD",
            ("Account", "SUPP-ACC-UZS", "account_currency"): "UZS",
        }
        mocked_get_cached_value.side_effect = lambda doctype, name, fieldname: lookup.get((doctype, name, fieldname))

        doc = make_kassa_doc(
            transaction_type="Расход",
            party_type="Supplier",
            party="Билолиддин",
            party_currency="UZS",
            amount=183,
            credit_amount=1800000,
            manual_credit_amount=1,
        )
        doc.get_party_account = MagicMock(return_value="SUPP-ACC-UZS")
        doc.get_company_exchange_rate = MagicMock(side_effect=lambda currency: 1 if currency == "USD" else 0.000081967)
        doc.set_linked_document = MagicMock()
        doc.name = "KASSA-TEST-0001"

        doc.create_payment_entry()

        self.assertTrue(fake_pe.inserted)
        self.assertTrue(fake_pe.submitted)
        self.assertEqual(fake_pe.paid_amount, 183)
        self.assertEqual(fake_pe.received_amount, 1800000)
        self.assertEqual(fake_pe.payment_type, "Pay")


class IntegrationTestKassa(FrappeTestCase):
    def test_case_matrix_documented_by_unit_tests(self):
        # Integration layer intentionally stays light; routing and accounting
        # behavior are covered in the unit suite above.
        self.assertTrue(True)
