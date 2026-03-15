# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Salary API Endpoint — iBox oylik maosh ro'yxatlarini olish.

Endpoint:
  - /api/integration/document/salary/list

Integration API — Bearer token bilan ishlaydi.
Har bir record salary_details[] ichida xodimlar va summa bor.
"""

import time

from erpnext_with_ibox.ibox.config import (
    SALARY_ENDPOINT,
    API_PAGE_DELAY,
)


class SalaryEndpoint:
    """
    iBox Salary endpointi uchun handler.

    Paginated generator orqali barcha salary recordlarni yield qiladi.
    """

    def __init__(self, client):
        self.client = client

    def get_page(self, page: int = 1, per_page: int = 100) -> dict:
        """Bitta sahifa salary data olish."""
        return self.client.request(
            method="GET",
            endpoint=SALARY_ENDPOINT,
            params={"page": page, "per_page": per_page},
        )

    def get_all(self, per_page: int = 100, max_pages: int = 2):
        """
        Barcha salary sahifalarini o'qib, har bir recordni yield qilish.

        Yields:
            dict: Har bir salary record (salary_details[] bilan)
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
                yield record

            if page >= total_pages or len(records) < per_page:
                break

            time.sleep(API_PAGE_DELAY)
            page += 1
