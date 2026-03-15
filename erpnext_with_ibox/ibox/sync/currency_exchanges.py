# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Currency Exchange Sync Handler — iBox valyuta ayirboshlash hujjatlari -> ERPNext Journal Entry.

Bu valyuta KURSI emas (exchange_rates.py uni qiladi).
Bu kassada valyuta sotib olish/sotish TRANZAKSIYALARI.

iBox API javobi:
    {
        "id": 152538,
        "filial_id": 1,
        "number": "884",
        "date": "2026-03-15T03:34:01.000000Z",
        "status": 152,
        "exchange_rate": "12300",
        "cashbox_id": 7,
        "cashbox_name": "Kunlik kassa",
        "from_amount": "187944000",
        "from_currency_id": 2,
        "from_currency_code": "UZS",
        "to_amount": "15280",
        "to_currency_id": 1,
        "to_currency_code": "USD",
    }

ERPNext Journal Entry:
    - Debit:  USD hisobi (to_amount — valyuta kirib keldi)
    - Credit: UZS hisobi (from_amount — valyuta chiqib ketdi)
    - Exchange rate: iBox dan kelgan kurs
"""

from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class CurrencyExchangeSyncHandler(BaseSyncHandler):
    DOCTYPE = "Journal Entry"
    NAME = "Currency Exchanges (Valyuta ayirboshlash)"

    IBOX_ID_FIELD = "custom_ibox_currency_exchange_id"

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox API dan currency exchange recordlarni yield qilish."""
        per_page = self.page_size or 100
        max_pages = self.max_pages or 2

        first_page = self.api.currency_exchanges.get_page(page=1, per_page=1)
        self.ibox_total = first_page.get("total", 0)

        for record in self.api.currency_exchanges.get_all(per_page=per_page, max_pages=max_pages):
            yield record

    def upsert(self, record: dict) -> bool:
        """
        Bitta currency exchange recordini ERPNext Journal Entry ga yaratish.

        Journal Entry:
          - Debit:  to_currency hisobi  (valyuta kirib keldi)
          - Credit: from_currency hisobi (valyuta chiqib ketdi)
        """
        ibox_id = record.get("id")
        if not ibox_id:
            return False

        # Deduplication
        if frappe.db.exists(
            "Journal Entry",
            {
                "custom_ibox_currency_exchange_id": str(ibox_id),
                "custom_ibox_client": self.client_name,
            },
        ):
            return False

        company = self.client_doc.company
        company_currency = frappe.db.get_value("Company", company, "default_currency") or "USD"
        raw_date = record.get("date", "")
        posting_date = self._parse_date(raw_date) or frappe.utils.today()
        number = record.get("number", "")

        from_amount = flt(record.get("from_amount", 0))
        to_amount = flt(record.get("to_amount", 0))
        from_currency = record.get("from_currency_code") or "UZS"
        to_currency = record.get("to_currency_code") or "USD"
        exchange_rate = flt(record.get("exchange_rate", 0))

        if from_amount <= 0 or to_amount <= 0:
            return False

        # Account topish — cashbox + valyutaga mos
        cashbox_id = str(record.get("cashbox_id") or "")
        from_account = self._get_account_for_currency(from_currency, company, cashbox_id)
        to_account = self._get_account_for_currency(to_currency, company, cashbox_id)

        if not from_account or not to_account:
            frappe.log_error(
                title=f"Currency Exchange Config Error - {self.client_name}",
                message=(
                    f"ibox_id={ibox_id}: Account topilmadi! "
                    f"from={from_currency} -> {from_account}, to={to_currency} -> {to_account}"
                ),
            )
            return False

        # Exchange rate hisoblash
        from_exchange_rate = self._calc_exchange_rate(from_currency, company_currency, exchange_rate)
        to_exchange_rate = self._calc_exchange_rate(to_currency, company_currency, exchange_rate)

        try:
            je = frappe.get_doc({
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "posting_date": posting_date,
                "company": company,
                "multi_currency": 1,
                "user_remark": f"iBox Currency Exchange #{number} (ID: {ibox_id})",
                "custom_ibox_currency_exchange_id": str(ibox_id),
                "custom_ibox_client": self.client_name,
                "accounts": [
                    {
                        "account": to_account,
                        "debit_in_account_currency": to_amount,
                        "exchange_rate": to_exchange_rate,
                    },
                    {
                        "account": from_account,
                        "credit_in_account_currency": from_amount,
                        "exchange_rate": from_exchange_rate,
                    },
                ],
            })
            je.insert(ignore_permissions=True)
            return True

        except Exception:
            frappe.log_error(
                title=f"Currency Exchange Upsert Error - {self.client_name}",
                message=f"ibox_id={ibox_id}\n{frappe.get_traceback()}",
            )
            return False

    def _get_account_for_currency(self, currency_code: str, company: str, cashbox_id: str = "") -> str | None:
        """Cashbox mapping dan valyutaga mos account topish."""
        # 1) Cashbox mapping dan account topish
        if cashbox_id:
            for row in self.client_doc.get("cashboxes") or []:
                if str(row.cashbox_id) == cashbox_id:
                    if currency_code == "UZS" and row.uzs_account:
                        return row.uzs_account
                    elif currency_code != "UZS" and row.usd_account:
                        return row.usd_account
                    break

        # 2) Fallback: har qanday Cash account — valyutaga mos
        account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_currency": currency_code,
                "account_type": "Cash",
                "is_group": 0,
            },
            "name",
        )
        return account

    def _calc_exchange_rate(self, currency: str, company_currency: str, ibox_rate: float) -> float:
        """Exchange rate hisoblash — company currency ga nisbatan."""
        if currency == company_currency:
            return 1.0

        # Company currency USD bo'lsa va currency UZS bo'lsa:
        # 1 UZS = 1/12300 USD → exchange_rate = 1/12300
        if company_currency == "USD" and currency == "UZS":
            if ibox_rate > 0:
                return 1.0 / ibox_rate
            return 1.0

        # Company currency UZS bo'lsa va currency USD bo'lsa:
        # 1 USD = 12300 UZS → exchange_rate = 12300
        if company_currency == "UZS" and currency == "USD":
            return ibox_rate if ibox_rate > 0 else 1.0

        return 1.0

    @staticmethod
    def _parse_date(raw: str) -> str:
        if not raw:
            return ""
        return raw[:10]
