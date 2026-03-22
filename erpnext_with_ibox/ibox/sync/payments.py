

import time
from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.config import SLUG_PAYMENTS
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class PaymentSyncHandler(BaseSyncHandler):
    DOCTYPE = "Payment Entry"
    NAME = "Payments"
    IBOX_ID_FIELD = "custom_ibox_payment_id"

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox API dan barcha to'lovlarni sahifa-sahifa yield qilish."""
        per_page = self.page_size or 100
        max_pages = self.max_pages or 0  # 0 = cheksiz

        page = 1
        while True:
            if max_pages and page > max_pages:
                break

            response = self.api.request(
                method="GET",
                endpoint=SLUG_PAYMENTS,
                params={"page": page, "per_page": per_page}
            )
            records = response.get("data", [])

            if page == 1:
                total = int(flt(response.get("total", 0)))
                self.ibox_total = min(total, max_pages * per_page) if max_pages else total

            if not records:
                break

            for record in records:
                yield record

            if len(records) < per_page:
                break

            time.sleep(1)
            page += 1

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

        changed = False

        for detail in record.get("payment_details", []):
            detail_id = str(detail.get("id"))
            amount = flt(detail.get("amount", 0))
            cashbox_id = str(detail.get("cashbox_id"))
            payment_currency = (detail.get("currency") or {}).get("code") or company_currency

            # Mode of Payment — cashbox mapping dan
            mode_of_payment = self._get_mode_of_payment(cashbox_id, payment_currency)
            if not mode_of_payment:
                continue

            # Deduplication — bir xil detail qayta kiritilmasin
            if frappe.db.get_value(
                "Payment Entry",
                {"custom_ibox_payment_detail_id": detail_id},
                "name"
            ):
                continue

            # paid_from — Receivable account (currency bo'yicha)
            paid_from = self._get_receivable_account(payment_currency)
            if not paid_from:
                frappe.log_error(
                    title=f"Payments Config Error - {self.client_name}",
                    message=(
                        f"payment_id={ibox_payment_id} detail_id={detail_id}: "
                        f"Receivable account topilmadi (currency={payment_currency})."
                    )
                )
                continue

            # paid_to — Mode of Payment dan topamiz
            paid_to = self._get_paid_to_account(mode_of_payment, payment_currency)
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

            # Haqiqiy account valyutalarini aniqlash
            paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or company_currency
            paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or company_currency

            # Exchange rate hisoblash
            source_exchange_rate = self._get_exchange_rate(paid_from_currency, company_currency, posting_date)
            target_exchange_rate = self._get_exchange_rate(paid_to_currency, company_currency, posting_date)

            # paid_amount  = paid_from account valyutasidagi summa
            # received_amount = paid_to account valyutasidagi summa
            paid_amount = flt(amount, 2)
            if source_exchange_rate == target_exchange_rate:
                received_amount = paid_amount
            else:
                received_amount = flt(paid_amount * source_exchange_rate / target_exchange_rate, 2)

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
                    "paid_from": paid_from,               # Receivable (Debitor)
                    "paid_to": paid_to,                   # Cash/Bank
                    # Valyutalar — HAQIQIY account valyutalari
                    "paid_from_account_currency": paid_from_currency,
                    "paid_to_account_currency": paid_to_currency,
                    # Miqdorlar
                    "paid_amount": paid_amount,
                    "received_amount": received_amount,
                    # Exchange rates
                    "source_exchange_rate": source_exchange_rate,
                    "target_exchange_rate": target_exchange_rate,
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

        if not fallback_mode_of_payment:
            return ""

        if not currency:
            return fallback_mode_of_payment

        candidates = [self._replace_currency_suffix(fallback_mode_of_payment, currency)]

        if cashbox_name:
            candidates.append(f"iBox Kassa - {cashbox_name} ({currency})")
            candidates.append(self._build_currency_mode_of_payment(cashbox_name, currency))

        candidates.append(fallback_mode_of_payment)

        for mop in candidates:
            if mop and frappe.db.exists("Mode of Payment", mop):
                return mop

        return fallback_mode_of_payment

    def _build_currency_mode_of_payment(self, cashbox_name: str, currency: str) -> str:
        return f"iBox - {cashbox_name} ({currency})"

    @staticmethod
    def _replace_currency_suffix(mode_of_payment: str, currency: str) -> str:
        if not mode_of_payment:
            return mode_of_payment

        if " (" in mode_of_payment and mode_of_payment.endswith(")"):
            base = mode_of_payment.rsplit(" (", 1)[0]
            return f"{base} ({currency})"

        return mode_of_payment

    def _get_receivable_account(self, currency: str = "") -> str:
        """
        Kompaniyaning Receivable (Debitor) accountini topish.
        iBox Client dagi uzs/usd_receivable_account dan olinadi.
        """
        # 1. iBox Client da currency bo'yicha belgilangan receivable account
        if currency == "UZS" and self.client_doc.get("uzs_receivable_account"):
            return self.client_doc.uzs_receivable_account
        if currency == "USD" and self.client_doc.get("usd_receivable_account"):
            return self.client_doc.usd_receivable_account

        # 2. Company default receivable account
        company = self.client_doc.company
        receivable = frappe.db.get_value(
            "Company", company, "default_receivable_account"
        )
        if receivable:
            return receivable

        # 3. Chart of Accounts dan account_type=Receivable qidirish
        receivable = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Receivable", "is_group": 0},
            "name"
        )
        return receivable or ""

    def _get_exchange_rate(self, from_currency: str, company_currency: str, posting_date: str) -> float:
        """Valyuta kursini aniqlash."""
        if from_currency == company_currency:
            return 1.0

        exchange_rate = flt(
            frappe.db.get_value(
                "Currency Exchange",
                {"from_currency": from_currency, "to_currency": company_currency},
                "exchange_rate"
            )
        )

        # UZS dan USD ga: agar kurs 12300 qilib kiritilgan bo'lsa inversiya
        if exchange_rate > 1 and from_currency == "UZS" and company_currency in ["USD", "EUR", "RUB"]:
            exchange_rate = 1.0 / exchange_rate

        if exchange_rate:
            return exchange_rate

        # Teskari yo'nalishni tekshirish
        reverse_rate = flt(
            frappe.db.get_value(
                "Currency Exchange",
                {"from_currency": company_currency, "to_currency": from_currency},
                "exchange_rate"
            )
        )
        if reverse_rate:
            return 1.0 / reverse_rate

        return 1.0

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
            acc_currency = frappe.db.get_value("Account", mop_account, "account_currency")
            if not acc_currency or acc_currency == currency:
                return mop_account

            currency_cash = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_type": "Cash",
                    "is_group": 0,
                    "account_currency": currency,
                },
                "name"
            )
            if currency_cash:
                return currency_cash
            return mop_account

        currency_cash = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_type": "Cash",
                "is_group": 0,
                "account_currency": currency,
            },
            "name"
        )
        if currency_cash:
            return currency_cash

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
