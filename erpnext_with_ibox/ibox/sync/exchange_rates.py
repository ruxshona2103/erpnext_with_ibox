# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Exchange Rate Sync Handler — iBox /api/core/exchange-rate -> ERPNext Currency Exchange.
Internal API (login/password token) orqali ishlaydi.
USD → UZS valyuta kurslarini sinxronlashtirish.
"""

from typing import Generator

import frappe
from frappe.utils import getdate

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class ExchangeRateSyncHandler(BaseSyncHandler):
    DOCTYPE = "Currency Exchange"
    NAME = "Exchange Rates"
    NEEDS_INTERNAL_API = True

    FROM_CURRENCY = "USD"
    TO_CURRENCY = "UZS"

    def __init__(self, api_client, client_doc, internal_api=None):
        super().__init__(api_client, client_doc)
        self.internal_api = internal_api

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox /api/core/exchange-rate dan UZS kurslarini yield qilish."""
        yield from self.internal_api.exchange_rate.get_all(currency_id=2)

    def upsert(self, record: dict) -> bool:
        """
        Bitta exchange rate recordini ERPNext Currency Exchange ga insert/update qilish.

        iBox API javobi (kutilgan format):
            {
                "id": 123,
                "rate": 12850.50,
                "date": "2026-02-28",
                "currency_id": 2,
                ...
            }
        """
        rate = record.get("rate")
        date_str = record.get("date")

        if not rate or not date_str:
            return False

        rate = float(rate)
        date_val = getdate(date_str)

        # Mavjud yozuvni tekshirish (date + from_currency + to_currency bo'yicha)
        existing = frappe.db.get_value(
            "Currency Exchange",
            {
                "date": date_val,
                "from_currency": self.FROM_CURRENCY,
                "to_currency": self.TO_CURRENCY,
            },
            ["name", "exchange_rate"],
            as_dict=True,
        )

        if existing:
            # Kurs o'zgargan bo'lsa — yangilash
            if float(existing.exchange_rate) != rate:
                frappe.db.set_value(
                    "Currency Exchange", existing.name,
                    "exchange_rate", rate,
                )
                return True
            return False  # O'zgarmagan — skip

        # Yangi yozuv yaratish
        frappe.get_doc({
            "doctype": "Currency Exchange",
            "date": date_val,
            "from_currency": self.FROM_CURRENCY,
            "to_currency": self.TO_CURRENCY,
            "exchange_rate": rate,
            "for_buying": 1,
            "for_selling": 1,
        }).insert(ignore_permissions=True)
        return True
