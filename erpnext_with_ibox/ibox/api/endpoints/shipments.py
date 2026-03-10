# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Shipment API Endpoint — iBox otgruzka (sotuv) ro'yxatlarini olish.

Endpoint:
  - /api/integration/document/shipment/list   (Sotuvlar)
"""

import time

from erpnext_with_ibox.ibox.config import (
    SHIPMENT_ENDPOINT,
    SHIPMENT_PAGE_SIZE,
    API_PAGE_DELAY,
)


class ShipmentEndpoint:
    """
    iBox Shipment endpointi uchun handler.

    Paginated generator orqali barcha sotuv recordlarni yield qiladi.
    """

    def __init__(self, client):
        self.client = client

    def get_page(self, page: int = 1, per_page: int = SHIPMENT_PAGE_SIZE) -> dict:
        """Bitta sahifa shipment data olish."""
        return self.client.request(
            method="GET",
            endpoint=SHIPMENT_ENDPOINT,
            params={"page": page, "per_page": per_page},
        )

    def get_all(self, per_page: int = SHIPMENT_PAGE_SIZE):
        """
        Barcha shipment sahifalarini o'qib, har bir recordni yield qilish.

        Yields:
            dict: Har bir shipment record
        """
        page = 1
        total_pages = None

        while True:
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
