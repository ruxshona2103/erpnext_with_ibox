# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Currency Exchange API Endpoint — iBox valyuta ayirboshlash hujjatlarini olish.

Endpoint:
  - /api/integration/document/currency-exchange/list

Bu valyuta KURSI emas, valyuta AYIRBOSHLASH tranzaksiyalari:
  - Kassadan UZS chiqadi, USD kiradi (yoki aksincha)
  - from_amount, to_amount, exchange_rate, cashbox info

Integration API — Bearer token bilan ishlaydi.
"""

import time

from erpnext_with_ibox.ibox.config import (
    CURRENCY_EXCHANGE_ENDPOINT,
    API_PAGE_DELAY,
)


class CurrencyExchangeEndpoint:
    """
    iBox Currency Exchange document endpointi uchun handler.

    Paginated generator orqali barcha valyuta ayirboshlash recordlarni yield qiladi.
    """

    def __init__(self, client):
        self.client = client

    def get_page(self, page: int = 1, per_page: int = 100) -> dict:
        """Bitta sahifa currency exchange data olish."""
        return self.client.request(
            method="GET",
            endpoint=CURRENCY_EXCHANGE_ENDPOINT,
            params={"page": page, "per_page": per_page},
        )

    def get_all(self, per_page: int = 100, max_pages: int = 2):
        """
        Barcha currency exchange sahifalarini o'qib, har bir recordni yield qilish.

        Yields:
            dict: Har bir currency exchange record
        """
        page = 1
        total_pages = None

        while max_pages == 0 or page <= max_pages:
            response = self.get_page(page=page, per_page=per_page)
            records = response.get("data", [])

            if total_pages is None:
                total_pages = response.get("last_page", 1)

            if not records:
                break

            for record in records:
                yield record

            if page >= total_pages or len(records) < per_page:
                break

            time.sleep(API_PAGE_DELAY)
            page += 1
