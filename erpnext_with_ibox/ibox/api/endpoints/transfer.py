# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Transfer API Endpoint — iBox omborlar orasidagi ko'chirish ro'yxatlarini olish.

Endpoints:
  - /api/document/transfer           (List — summary)
  - /api/document/transfer/{id}      (Detail — transfer_details[])

List API faqat summary qaytaradi (id, number, date, warehouse_from, warehouse_to).
Detail API har bir record uchun alohida chaqiriladi — transfer_details[] olish uchun.
"""

import time

from erpnext_with_ibox.ibox.config import (
    TRANSFER_ENDPOINT,
    API_PAGE_DELAY,
)


class TransferEndpoint:
    """
    iBox Transfer endpointi uchun handler.

    List → Detail pattern:
      1. List API dan barcha record ID larni olish (paginated)
      2. Har bir ID uchun Detail API chaqirib to'liq data olish
    """

    def __init__(self, client):
        self.client = client

    def get_page(self, page: int = 1, per_page: int = 100) -> dict:
        """Bitta sahifa transfer list olish."""
        return self.client.request(
            method="GET",
            endpoint=TRANSFER_ENDPOINT,
            params={
                "page": page,
                "per_page": per_page,
                "sort_by": "created_at",
                "desc": 1,
                "available": 1,
            },
        )

    def get_detail(self, record_id: int) -> dict:
        """Bitta transfer ning to'liq detaillarini olish."""
        return self.client.request(
            method="GET",
            endpoint=f"{TRANSFER_ENDPOINT}/{record_id}",
        )

    def get_all(self, per_page: int = 100, max_pages: int = 2):
        """
        List dan ID larni olib, har biri uchun detail olish.

        Yields:
            dict: To'liq transfer record (detail bilan)
        """
        page = 1
        total_pages = None

        while page <= max_pages:
            response = self.get_page(page=page, per_page=per_page)
            records = response.get("data", [])

            if total_pages is None:
                total_pages = response.get("last_page", 1)

            if not records:
                break

            for record in records:
                record_id = record.get("id")
                if not record_id:
                    continue

                try:
                    detail = self.get_detail(record_id)
                    yield detail
                except Exception:
                    continue

                time.sleep(0.5)

            if page >= total_pages or len(records) < per_page:
                break

            time.sleep(API_PAGE_DELAY)
            page += 1
