import time
from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.config import SLUG_PAYMENTS_MADE
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class PaymentMadeSyncHandler(BaseSyncHandler):
    DOCTYPE = "Payment Entry"
    NAME = "Payments Made (Chiquvchi To'lovlar)"

    def fetch_data(self) -> Generator[dict, None, None]:
        """
        iBox API dan faqatgina eng oxirgi 2 ta sahifani (maksimal 200 ta to'lov) yield qilish.
        API ga ortiqcha og'irlik tushmasligi uchun limit qat'iy belgilangan.
        """
        max_pages = 2
        per_page = 100

        for page in range(1, max_pages + 1):
            response = self.api.request(
                method="GET",
                endpoint=SLUG_PAYMENTS_MADE,
                params={"page": page, "per_page": per_page}
            )
            records = response.get("data", [])

            if not records:
                break

            for record in records:
                yield record

            # Agar kelgan ma'lumotlar per_page dan kam bo'lsa, demak oxirgi sahifaga keldik
            if len(records) < per_page:
                break

            time.sleep(1)  # Rate limit — 429 xatosidan saqlash

    def upsert(self, record: dict) -> bool:
        """
        Bitta iBox payment-made recordini ERPNext hujjatiga aylantiradi.
        - payment_type == 6: Payment Entry (Pay, Employee)
        - payment_type == null/other: Journal Entry (Expense)

        Returns:
            True — hujjat yaratilsa yoki yangilansa.
            False — zapis o'tkazib yuborilsa.
        """
        ibox_payment_id = str(record.get("id"))
        posting_date = (record.get("date") or "").split("T")[0] or frappe.utils.today()
        payment_type = record.get("payment_type")
        outlet_id = record.get("outlet_id")

        # Kompaniya default valyutasi
        company = self.client_doc.company
        company_currency = frappe.db.get_value("Company", company, "default_currency") or "USD"

        changed = False

        for detail in record.get("payment_details", []):
            detail_id = str(detail.get("id"))
            amount = flt(detail.get("amount", 0))
            cashbox_id = str(detail.get("cashbox_id"))
            payment_currency = (detail.get("currency") or {}).get("code") or company_currency

            # Mode of Payment — cashbox mapping orqali to'lov kassa hisobini (paid_from) topish
            mode_of_payment = self._get_mode_of_payment(cashbox_id)
            if not mode_of_payment:
                continue

            paid_from_account = self._get_cashbox_account(mode_of_payment, payment_currency)
            if not paid_from_account:
                continue

            # Exchange rate hisoblash
            if payment_currency == company_currency:
                exchange_rate = 1.0
            else:
                exchange_rate = flt(
                    frappe.db.get_value(
                        "Currency Exchange",
                        {"from_currency": payment_currency, "to_currency": company_currency},
                        "exchange_rate"
                    )
                )
                
                # Agar UZS dan USD ga bo'lsa va kurs 1 dan katta (masalan 12500) qilib qo'yishgan bo'lsa:
                if exchange_rate > 1 and payment_currency == "UZS" and company_currency in ["USD", "EUR", "RUB"]:
                    exchange_rate = 1.0 / exchange_rate
                
                # Agar topa olmasa teskarisini qidirish (USD -> UZS)
                if not exchange_rate:
                    reverse_rate = flt(
                        frappe.db.get_value(
                            "Currency Exchange",
                            {"from_currency": company_currency, "to_currency": payment_currency},
                            "exchange_rate"
                        )
                    )
                    if reverse_rate:
                        exchange_rate = 1.0 / reverse_rate
                    else:
                        exchange_rate = 1.0

            paid_amount = flt(amount, 2)
            base_paid_amount = flt(amount * exchange_rate, 2)

            if payment_type == 6:
                # Oylik maosh (Employee Payment Entry)
                outlet_name = record.get("outlet_name") or "Unknown"
                if self._upsert_employee_payment(
                    ibox_payment_id, detail_id, outlet_id, outlet_name, posting_date, company, company_currency,
                    payment_currency, mode_of_payment, paid_from_account, paid_amount, base_paid_amount, exchange_rate
                ):
                    changed = True

            else:
                # Boshqa xarajatlar (Journal Entry)
                memo = record.get("payment_type_name") or f"iBox Payment: {ibox_payment_id}"
                if self._upsert_journal_entry(
                    ibox_payment_id, detail_id, posting_date, company,
                    paid_from_account, payment_currency, paid_amount, exchange_rate, memo
                ):
                    changed = True

        return changed

    def _upsert_employee_payment(self, payment_id, detail_id, outlet_id, outlet_name, posting_date, company, company_currency, 
                                 payment_currency, mode_of_payment, paid_from, paid_amount, base_paid_amount, exchange_rate):
        """Payment Entry (Pay) yaratish — Ishchi uchun."""

        if frappe.db.get_value("Payment Entry", {"custom_ibox_payment_detail_id": detail_id}, "name"):
            return False

        # Custom Employee id orqali xodimni topish
        employee = frappe.db.get_value(
            "Employee",
            {"custom_ibox_id": outlet_id, "custom_ibox_client": self.client_name},
            "name"
        )
        if not employee:
            try:
                emp_doc = frappe.get_doc({
                    "doctype": "Employee",
                    "first_name": outlet_name,
                    "company": company,
                    "date_of_joining": posting_date,
                    "gender": "Male",
                    "date_of_birth": "2005-01-01",
                    "custom_ibox_id": str(outlet_id),
                    "custom_ibox_client": self.client_name
                })
                emp_doc.insert(ignore_permissions=True)
                employee = emp_doc.name
            except Exception:
                frappe.log_error(
                    title=f"Employee Auto-Create Error - {self.client_name}",
                    message=f"payment_id={payment_id}: Employee (outlet_id={outlet_id}, name={outlet_name}) yaratishda xatolik!\n{frappe.get_traceback()}"
                )
                return False

        # Status Active ekanligiga ishonch hosil qilish
        if frappe.db.get_value("Employee", employee, "status") != "Active":
            frappe.db.set_value("Employee", employee, "status", "Active")

        # Default Payable hisobi (Masalan, ish haqi qarzdorligi)
        paid_to = self.client_doc.get("uzs_payable_account") if payment_currency == "UZS" else self.client_doc.get("usd_payable_account")
        if not paid_to:
            paid_to = frappe.db.get_value("Company", company, "default_payable_account")

        if not paid_to:
            frappe.log_error(
                title=f"Payment Made Config Error - {self.client_name}",
                message=f"payment_id={payment_id}: Kompaniya yoki iBox Client uchun Payable Account ko'rsatilmagan!"
            )
            return False

        # Tushuvchi hisob valyutasiga qarab tushum (received) miqdorini aniqlash. 12 Trillionga oshib ketmasligi uchun
        paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or company_currency
        target_amount = paid_amount if paid_to_currency == payment_currency else base_paid_amount
        target_exchange_rate = 1.0 if paid_to_currency == company_currency else exchange_rate
        source_exchange_rate = exchange_rate if payment_currency != company_currency else 1.0

        try:
            doc = frappe.get_doc({
                "doctype": "Payment Entry",
                "payment_type": "Pay",
                "party_type": "Employee",
                "party": employee,
                "company": company,
                "posting_date": posting_date,
                "mode_of_payment": mode_of_payment,
                "paid_from": paid_from,
                "paid_to": paid_to,
                "paid_from_account_currency": payment_currency,
                "paid_to_account_currency": paid_to_currency,
                "paid_amount": paid_amount,
                "received_amount": target_amount,
                "source_exchange_rate": source_exchange_rate,
                "target_exchange_rate": target_exchange_rate,
                "custom_ibox_client": self.client_name,
                "custom_ibox_payment_id": payment_id,
                "custom_ibox_payment_detail_id": detail_id,
            })
            doc.setup_party_account_field()
            doc.set_missing_values()
            doc.insert(ignore_permissions=True)
            return True
        except Exception:
            frappe.log_error(
                title=f"Payment Made Upsert Error - {self.client_name}",
                message=f"payment_id={payment_id} detail_id={detail_id}\n{frappe.get_traceback()}"
            )
            return False

    def _upsert_journal_entry(self, payment_id, detail_id, posting_date, company, paid_from_account, 
                              payment_currency, paid_amount, exchange_rate, memo):
        """Journal Entry yaratish — Maxsus (Expense) xarajatlar uchun."""

        # Deduplication tekshiruvi (Biz custom field qoshishimiz yoki remark ni tekshirishimiz kerak bo'ladi.
        # Hoziroq aniq custom fieldlar bo'lmagani uchun user remark orqali dublikatlarni yo'qotmoqdamiz)
        if frappe.db.exists("Journal Entry", {"user_remark": f"iBox Payment Detail ID: {detail_id}"}):
            return False

        # Tushum qilinadigan xarajat hisobini (Expense Account) topish (Hozircha default payable sifatida kiritib qolamiz, chunki maxsus account so'ralmagan)
        target_account = self.client_doc.get("uzs_payable_account") if payment_currency == "UZS" else self.client_doc.get("usd_payable_account")
        if not target_account:
            target_account = frappe.db.get_value("Company", company, "default_payable_account")
            if not target_account:
                frappe.log_error(
                    title=f"Payment Made Config Error - {self.client_name}",
                    message=f"payment_id={payment_id}: Journal target (Expense/Payable) yozilmagan!"
                )
                return False

        try:
            je = frappe.get_doc({
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "posting_date": posting_date,
                "company": company,
                "multi_currency": 1,
                "user_remark": f"iBox Payment Detail ID: {detail_id}",
                "accounts": [
                    {
                        "account": target_account,
                        "debit_in_account_currency": paid_amount,
                        "exchange_rate": exchange_rate,
                    },
                    {
                        "account": paid_from_account,
                        "credit_in_account_currency": paid_amount,
                        "exchange_rate": exchange_rate,
                    }
                ]
            })
            je.insert(ignore_permissions=True)
            je.submit() # Kassadan to'g'ridan to'g'ri chiqib ketgani uchun submit ham bo'lishi kerak.
            return True

        except Exception:
            frappe.log_error(
                title=f"Payment Made Journal Error - {self.client_name}",
                message=f"payment_id={payment_id} detail_id={detail_id}\n{frappe.get_traceback()}"
            )
            return False

    def _get_mode_of_payment(self, cashbox_id: str) -> str:
        """Kassani o'rnatish."""
        for row in self.client_doc.get("cashboxes", []):
            if str(row.cashbox_id) == str(cashbox_id):
                return row.mode_of_payment
        return None

    def _get_cashbox_account(self, mode_of_payment: str, currency: str) -> str:
        """Kassani (paid_from_account) hisobiga erishish."""
        company = self.client_doc.company

        mop_account = frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": mode_of_payment, "company": company},
            "default_account"
        )
        if mop_account:
            return mop_account

        return frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Cash", "is_group": 0},
            "name"
        ) or ""
