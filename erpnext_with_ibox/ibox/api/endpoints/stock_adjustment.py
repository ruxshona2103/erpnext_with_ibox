# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Stock Adjustment API Endpoint — iBox inventarizatsiya ro'yxatlarini olish.

Endpoints:
  - /api/document/stock-adjustment           (List — summary)
  - /api/document/stock-adjustment/{id}      (Detail — stock_adjustment_details[])

List API faqat summary qaytaradi (id, number, date, warehouse_name).
Detail API har bir record uchun alohida chaqiriladi — stock_adjustment_details[] olish uchun.
"""

import time

from erpnext_with_ibox.ibox.config import (
    STOCK_ADJUSTMENT_ENDPOINT,
    API_PAGE_DELAY,
)


class StockAdjustmentEndpoint:
    """
    iBox Stock Adjustment endpointi uchun handler.

    List → Detail pattern:
      1. List API dan barcha record ID larni olish (paginated)
      2. Har bir ID uchun Detail API chaqirib to'liq data olish
    """

    def __init__(self, client):
        self.client = client

    def get_page(self, page: int = 1, per_page: int = 100) -> dict:
        """Bitta sahifa stock adjustment list olish."""
        return self.client.request(
            method="GET",
            endpoint=STOCK_ADJUSTMENT_ENDPOINT,
            params={
                "page": page,
                "per_page": per_page,
                "sort_by": "created_at",
                "desc": 1,
                "available": 1,
            },
        )

    def get_detail(self, record_id: int) -> dict:
        """Bitta stock adjustment ning to'liq detaillarini olish."""
        return self.client.request(
            method="GET",
            endpoint=f"{STOCK_ADJUSTMENT_ENDPOINT}/{record_id}",
        )

    def get_all(self, per_page: int = 100, max_pages: int = 2):
        """
        List dan ID larni olib, har biri uchun detail olish.

        Yields:
            dict: To'liq stock adjustment record (detail bilan)
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
                record_id = record.get("id")
                if not record_id:
                    continue

                try:
                    detail = self.get_detail(record_id)
                    yield detail
                except Exception:
                    # Detail olishda xato — skip, sync to'xtamaydi
                    continue

                time.sleep(0.5)  # Detail API uchun qisqa pauza

            if page >= total_pages or len(records) < per_page:
                break

            time.sleep(API_PAGE_DELAY)
            page += 1
