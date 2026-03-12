

import time
from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.config import SLUG_PAYMENTS
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class PaymentSyncHandler(BaseSyncHandler):
    DOCTYPE = "Payment Entry"
    NAME = "Payments"

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox API dan barcha to'lovlarni sahifa-sahifa yield qilish."""
        page = 1
        per_page = 100
        total_pages = None

        while True:
            response = self.api.request(
                method="GET",
                endpoint=SLUG_PAYMENTS,
                params={"page": page, "per_page": per_page}
            )
            records = response.get("data", [])

            if total_pages is None:
                total_pages = response.get("last_page", 1)

            if not records:
                break

            for record in records:
                yield record

            if page >= total_pages or len(records) < per_page:
                break

            page += 1
            time.sleep(1)  # Rate limit — 429 xatosidan saqlash

    def upsert(self, record: dict) -> bool:
        """
        Bitta iBox to'lov recordini ERPNext Payment Entry ga aylantiradi.
        Faqat payment_type=1 ("Оплата от клиента") qayta ishlanadi.

        Returns:
            True — kamida 1 ta Payment Entry yaratilsa.
            False — zapis o'tkazib yuborilsa.
        """
        # Faqat "Оплата от клиента" (payment_type == 1)
        if record.get("payment_type") != 1:
            return False

        ibox_payment_id = str(record.get("id"))
        outlet_id = record.get("outlet_id")
        posting_date = (record.get("date") or "").split("T")[0] or frappe.utils.today()

        # Customer topamiz (outlet_id → Customer)
        customer = frappe.db.get_value(
            "Customer",
            {"custom_ibox_id": outlet_id, "custom_ibox_client": self.client_name},
            "name"
        )
        if not customer:
            return False  # Mijoz sync qilinmagan — o'tkazib yuboramiz

        # Kompaniya default valyutasi
        company = self.client_doc.company
        company_currency = frappe.db.get_value(
            "Company", company, "default_currency"
        ) or "USD"

        # paid_from — mijozning Receivable (Debitor) accounti
        # Payment Entry type=Receive uchun MAJBURIY maydon
        paid_from = self._get_receivable_account()
        if not paid_from:
            frappe.log_error(
                title=f"Payments Config Error - {self.client_name}",
                message=(
                    f"payment_id={ibox_payment_id}: Kompaniya '{company}' uchun "
                    f"Receivable account topilmadi. "
                    f"ERPNext → Chart of Accounts dan account_type='Receivable' mavjudligini tekshiring."
                )
            )
            return False

        changed = False

        for detail in record.get("payment_details", []):
            detail_id = str(detail.get("id"))
            amount = flt(detail.get("amount", 0))
            cashbox_id = str(detail.get("cashbox_id"))
            payment_currency = (detail.get("currency") or {}).get("code") or company_currency

            # Mode of Payment — cashbox mapping dan
            mode_of_payment = self._get_mode_of_payment(cashbox_id, payment_currency)
            if not mode_of_payment:
                # Cashbox mapping yo'q — bu detail ni o'tkazib yuboramiz
                continue

            # Deduplication — bir xil detail qayta kiritilmasin
            if frappe.db.get_value(
                "Payment Entry",
                {"custom_ibox_payment_detail_id": detail_id},
                "name"
            ):
                continue

            # paid_to — Mode of Payment dan topamiz
            paid_to = self._get_paid_to_account(mode_of_payment, company_currency)
            if not paid_to:
                frappe.log_error(
                    title=f"Payments Config Error - {self.client_name}",
                    message=(
                        f"payment_id={ibox_payment_id} detail_id={detail_id}: "
                        f"Mode of Payment '{mode_of_payment}' uchun account topilmadi. "
                        f"ERPNext → Mode of Payment → Accounts jadvalini to'ldiring."
                    )
                )
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
                ) or 1.0

            # paid_amount  = mijoz valyutasidagi summa (iBox dan keladi)
            # received_amount = kompaniya valyutasidagi summa (konvertatsiyadan keyin)
            paid_amount = flt(amount, 2)
            received_amount = flt(amount * exchange_rate, 2)

            try:
                doc = frappe.get_doc({
                    "doctype": "Payment Entry",
                    "payment_type": "Receive",
                    "party_type": "Customer",
                    "party": customer,
                    "company": company,
                    "posting_date": posting_date,
                    "mode_of_payment": mode_of_payment,
                    # Hisob raqamlar
                    "paid_from": paid_from,               # Receivable (Debitor) — MAJBURIY
                    "paid_to": paid_to,                   # Cash/Bank
                    # Valyutalar
                    "paid_from_account_currency": payment_currency,
                    "paid_to_account_currency": company_currency,
                    # Miqdorlar
                    "paid_amount": paid_amount,
                    "received_amount": received_amount,
                    # Exchange rates
                    "source_exchange_rate": exchange_rate,
                    "target_exchange_rate": 1.0,
                    # iBox meta
                    "custom_ibox_client": self.client_name,
                    "custom_ibox_payment_id": ibox_payment_id,
                    "custom_ibox_payment_detail_id": detail_id,
                })
                doc.setup_party_account_field()
                doc.set_missing_values()
                doc.insert(ignore_permissions=True)
                changed = True
            except Exception:
                frappe.log_error(
                    title=f"Payments Upsert Error - {self.client_name}",
                    message=(
                        f"payment_id={ibox_payment_id} "
                        f"detail_id={detail_id}\n"
                        f"{frappe.get_traceback()}"
                    )
                )

        return changed

    def _get_mode_of_payment(self, cashbox_id: str, currency: str | None = None) -> str:
        """iBox Client dagi Cashbox Mapping jadvalidan Mode of Payment topish."""
        fallback_mode_of_payment = None
        cashbox_name = None

        for row in self.client_doc.get("cashboxes", []):
            if str(row.cashbox_id) == str(cashbox_id):
                fallback_mode_of_payment = row.mode_of_payment
                cashbox_name = row.cashbox_name
                break

        if currency and cashbox_name:
            preferred_mode_of_payment = self._build_currency_mode_of_payment(cashbox_name, currency)
            if frappe.db.exists("Mode of Payment", preferred_mode_of_payment):
                return preferred_mode_of_payment

        return fallback_mode_of_payment

    def _build_currency_mode_of_payment(self, cashbox_name: str, currency: str) -> str:
        return f"iBox - {cashbox_name} ({currency})"

    def _get_receivable_account(self) -> str:
        """
        Kompaniyaning Receivable (Debitor) accountini topish.
        Payment Entry type=Receive uchun paid_from field ga kerak.
        """
        company = self.client_doc.company

        # 1. Company default receivable account
        receivable = frappe.db.get_value(
            "Company", company, "default_receivable_account"
        )
        if receivable:
            return receivable

        # 2. Chart of Accounts dan account_type=Receivable qidirish
        receivable = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Receivable", "is_group": 0},
            "name"
        )
        return receivable or ""

    def _get_paid_to_account(self, mode_of_payment: str, currency: str) -> str:
        """
        paid_to accountni topish:
        1. Mode of Payment > Accounts jadvalidan (company bo'yicha)
        2. Fallback: kompaniyaning default Cash accounti
        """
        company = self.client_doc.company

        # 1. Mode of Payment dan account topamiz
        mop_account = frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": mode_of_payment, "company": company},
            "default_account"
        )
        if mop_account:
            return mop_account

        # 2. Fallback: kompaniyaning Cash accountini topamiz
        cash_account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_type": "Cash",
                "is_group": 0,
            },
            "name"
        )
        if cash_account:
            return cash_account

        # 3. Oxirgi fallback: ism bo'yicha qidirish
        return frappe.db.get_value(
            "Account",
            {"company": company, "account_name": "Cash", "is_group": 0},
            "name"
        ) or ""
