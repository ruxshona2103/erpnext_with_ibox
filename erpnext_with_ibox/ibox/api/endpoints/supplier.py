# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Supplier API Endpoint — /api/outlet/supplier uchun handler.
Internal API orqali ishlaydi (login/password token).
"""

from erpnext_with_ibox.ibox.config import SUPPLIER_ENDPOINT, INTERNAL_PAGE_SIZE


class SupplierEndpoint:
    """
    iBox /api/outlet/supplier endpointi uchun handler.

    Pagination: response'dagi last_page, current_page, data fieldlaridan foydalanadi.
    """

    def __init__(self, client):
        self.client = client

    def get_page(self, page: int = 1, per_page: int = INTERNAL_PAGE_SIZE) -> dict:
        """
        Bitta sahifa supplier data olish.

        Args:
            page: Sahifa raqami (1-indexed)
            per_page: Sahifadagi yozuvlar soni

        Returns:
            API javobini dict shaklida (data, total, last_page, current_page)
        """
        return self.client.request(
            method="GET",
            endpoint=SUPPLIER_ENDPOINT,
            params={
                "sort_by": "created_at",
                "desc": 1,
                "available": 1,
                "page": page,
                "per_page": per_page,
            },
        )

    def get_all(self, per_page: int = INTERNAL_PAGE_SIZE):
        """
        Barcha sahifalarni ketma-ket o'qib, har bir recordni yield qilish.

        Yields:
            dict: "data" massividagi alohida yozuvlar
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

            yield from records

            if page >= total_pages or len(records) < per_page:
                break

            page += 1
