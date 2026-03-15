# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Salary Sync Handler — iBox /api/integration/document/salary/list -> ERPNext Journal Entry.

iBox oylik maosh hujjatlari → ERPNext Journal Entry (DRAFT).

Salary Slip ERPNext da murakkab setup talab qiladi (Salary Structure, Payroll Entry).
Shuning uchun hozircha Journal Entry ishlatamiz — sodda va tez ishlaydi.

iBox API javobi:
    {
        "id": 146686,
        "currency_code": "UZS",
        "number": "172",
        "date": "2026-03-01T11:49:25.000000Z",
        "total": 51842000,
        "salary_details": [
            {
                "id": 450,
                "user_id": 3,
                "amount": 21275000,
                "comment": null,
                "user": {"id": 3, "name": "Rushana"}
            }
        ]
    }

Employee mapping: user.id == outlet_id (payment_made dagi bir xil).
    custom_ibox_id → Employee.
    Agar Employee topilmasa → avtomatik yaratiladi.

Journal Entry:
    - Debit: Salary Expense account (har bir xodim uchun)
    - Credit: Cash/Bank account (kassadan chiqdi)
"""

from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class SalarySyncHandler(BaseSyncHandler):
    DOCTYPE = "Journal Entry"
    NAME = "Salaries (Oylik maoshlar)"

    IBOX_ID_FIELD = "custom_ibox_salary_id"

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox API dan salary recordlarni yield qilish."""
        first_page = self.api.salaries.get_page(page=1, per_page=1)
        self.ibox_total = first_page.get("total", 0)

        for record in self.api.salaries.get_all(per_page=100, max_pages=2):
            yield record

    def upsert(self, record: dict) -> bool:
        """
        Bitta salary recordini ERPNext Journal Entry ga yaratish.
        Har bir salary_detail uchun alohida Journal Entry yaratiladi
        (xodim bo'yicha tracking uchun).
        """
        ibox_id = record.get("id")
        if not ibox_id:
            return False

        # Deduplication — butun salary hujjat uchun
        if frappe.db.exists(
            "Journal Entry",
            {
                "custom_ibox_salary_id": str(ibox_id),
                "custom_ibox_client": self.client_name,
            },
        ):
            return False

        company = self.client_doc.company
        raw_date = record.get("date", "")
        posting_date = self._parse_date(raw_date) or frappe.utils.today()
        currency_code = record.get("currency_code") or "UZS"
        total = flt(record.get("total", 0))
        number = record.get("number", "")

        details = record.get("salary_details") or []
        if not details:
            return False

        company_currency = frappe.db.get_value("Company", company, "default_currency") or "USD"

        # Expense account (salary uchun)
        salary_expense_account = self._get_salary_expense_account(company)
        if not salary_expense_account:
            frappe.log_error(
                title=f"Salary Config Error - {self.client_name}",
                message=f"ibox_id={ibox_id}: Salary Expense Account topilmadi!",
            )
            return False

        # Paid from account (kassa)
        paid_from_account = self._get_salary_payable_account(currency_code, company)
        if not paid_from_account:
            frappe.log_error(
                title=f"Salary Config Error - {self.client_name}",
                message=f"ibox_id={ibox_id}: Payable/Cash account topilmadi!",
            )
            return False

        # Exchange rate
        if currency_code == company_currency:
            exchange_rate = 1.0
        else:
            exchange_rate = self._get_exchange_rate(currency_code, company_currency)

        # Journal Entry accounts
        accounts = []

        for detail in details:
            user = detail.get("user") or {}
            user_id = user.get("id") or detail.get("user_id")
            user_name = user.get("name") or "Unknown"
            amount = flt(detail.get("amount", 0))
            comment = detail.get("comment") or ""

            if amount <= 0:
                continue

            # Employee auto-create
            employee = self._get_or_create_employee(user_id, user_name, company, posting_date)

            party_info = ""
            if employee:
                party_info = f" ({user_name})"

            # Debit — Salary Expense
            accounts.append({
                "account": salary_expense_account,
                "debit_in_account_currency": amount,
                "exchange_rate": exchange_rate,
                "party_type": "Employee" if employee else "",
                "party": employee or "",
                "user_remark": f"{user_name}: {comment}" if comment else user_name,
            })

            # Credit — Cash/Payable
            accounts.append({
                "account": paid_from_account,
                "credit_in_account_currency": amount,
                "exchange_rate": exchange_rate,
            })

        if not accounts:
            return False

        try:
            je = frappe.get_doc({
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "posting_date": posting_date,
                "company": company,
                "multi_currency": 1 if currency_code != company_currency else 0,
                "user_remark": f"iBox Salary #{number} (ID: {ibox_id})",
                "custom_ibox_salary_id": str(ibox_id),
                "custom_ibox_client": self.client_name,
                "accounts": accounts,
            })
            je.insert(ignore_permissions=True)
            return True

        except Exception:
            frappe.log_error(
                title=f"Salary Upsert Error - {self.client_name}",
                message=f"ibox_id={ibox_id}\n{frappe.get_traceback()}",
            )
            return False

    def _get_or_create_employee(self, user_id, user_name, company, posting_date) -> str | None:
        """Employee topish yoki yaratish. payment_made bilan bir xil logika."""
        if not user_id:
            return None

        employee = frappe.db.get_value(
            "Employee",
            {"custom_ibox_id": str(user_id), "custom_ibox_client": self.client_name},
            "name",
        )
        if employee:
            return employee

        try:
            emp_doc = frappe.get_doc({
                "doctype": "Employee",
                "first_name": user_name,
                "company": company,
                "date_of_joining": posting_date,
                "gender": "Male",
                "date_of_birth": "2005-01-01",
                "custom_ibox_id": str(user_id),
                "custom_ibox_client": self.client_name,
            })
            emp_doc.insert(ignore_permissions=True)
            return emp_doc.name
        except Exception:
            frappe.log_error(
                title=f"Employee Auto-Create Error - {self.client_name}",
                message=f"user_id={user_id}, name={user_name}\n{frappe.get_traceback()}",
            )
            return None

    def _get_salary_expense_account(self, company) -> str | None:
        """Salary Expense Account topish."""
        # 1) Company default_expense_account
        account = frappe.db.get_value("Company", company, "default_expense_account")
        if account:
            return account

        # 2) "Salary" yoki "Payroll" nomli expense account
        account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": "Expense",
                "is_group": 0,
                "account_name": ["like", "%Salary%"],
            },
            "name",
        )
        if account:
            return account

        # 3) Har qanday expense account
        account = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": "Expense", "is_group": 0},
            "name",
        )
        return account

    def _get_salary_payable_account(self, currency_code, company) -> str | None:
        """Salary uchun cash/payable account topish."""
        if currency_code == "UZS":
            account = getattr(self.client_doc, "uzs_payable_account", None)
        else:
            account = getattr(self.client_doc, "usd_payable_account", None)

        if account:
            return account

        return frappe.db.get_value("Company", company, "default_payable_account")

    def _get_exchange_rate(self, from_currency, to_currency) -> float:
        """Currency Exchange jadvalidan kurs olish."""
        rate = flt(
            frappe.db.get_value(
                "Currency Exchange",
                {"from_currency": from_currency, "to_currency": to_currency},
                "exchange_rate",
                order_by="date desc",
            )
        )
        if rate:
            return rate

        # Teskari kurs
        reverse = flt(
            frappe.db.get_value(
                "Currency Exchange",
                {"from_currency": to_currency, "to_currency": from_currency},
                "exchange_rate",
                order_by="date desc",
            )
        )
        if reverse:
            return 1.0 / reverse

        return 1.0

    @staticmethod
    def _parse_date(raw: str) -> str:
        if not raw:
            return ""
        return raw[:10]
