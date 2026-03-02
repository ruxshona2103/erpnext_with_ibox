# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Exchange Rate API Endpoint — /api/core/exchange-rate uchun handler.
Internal API orqali ishlaydi (login/password token).
UZS valyuta kurslarini olish uchun ishlatiladi.
"""

from erpnext_with_ibox.ibox.config import EXCHANGE_RATE_ENDPOINT, INTERNAL_PAGE_SIZE


class ExchangeRateEndpoint:
    """
    iBox /api/core/exchange-rate endpointi uchun handler.

    Valyuta kurslarini olish uchun ishlatiladi.
    Pagination: response'dagi last_page, current_page, data fieldlaridan foydalanadi.
    """

    def __init__(self, client):
        self.client = client

    def get_page(self, page: int = 1, per_page: int = INTERNAL_PAGE_SIZE, currency_id: int = 2) -> dict:
        """
        Bitta sahifa exchange rate data olish.

        Args:
            page: Sahifa raqami (1-indexed)
            per_page: Sahifadagi yozuvlar soni
            currency_id: Valyuta ID (2 = UZS)

        Returns:
            API javobini dict shaklida
        """
        return self.client.request(
            method="GET",
            endpoint=EXCHANGE_RATE_ENDPOINT,
            params={
                "currency_id": currency_id,
                "page": page,
                "per_page": per_page,
            },
        )

    def get_all(self, per_page: int = INTERNAL_PAGE_SIZE, currency_id: int = 2):
        """
        Barcha sahifalarni ketma-ket o'qib, har bir recordni yield qilish.

        Args:
            per_page: Sahifadagi yozuvlar soni
            currency_id: Valyuta ID (2 = UZS)

        Yields:
            dict: Alohida exchange rate yozuvlari
        """
        page = 1
        total_pages = None

        while True:
            response = self.get_page(page=page, per_page=per_page, currency_id=currency_id)
            records = response.get("data", [])

            if total_pages is None:
                total_pages = response.get("last_page", 1)

            if not records:
                break

            yield from records

            if page >= total_pages or len(records) < per_page:
                break

            page += 1
