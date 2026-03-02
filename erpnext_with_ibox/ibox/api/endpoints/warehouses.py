# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Warehouse API Endpoint — /core/directory?data=core_warehouse uchun handler.
Directory API orqali omborxona ma'lumotlarini olish.
"""

from erpnext_with_ibox.ibox.config import DIRECTORY_ENDPOINT, PAGE_SIZE, SLUG_WAREHOUSES


class WarehouseEndpoint:
    """
    iBox /api/integration/core/directory endpointi uchun warehouse handler.

    `data=core_warehouse` slug bilan ishlaydi.
    """

    def __init__(self, client):
        self.client = client

    def get_page(self, page: int = 1, per_page: int = PAGE_SIZE) -> dict:
        """
        Bitta sahifa omborxona data olish.

        Args:
            page: Sahifa raqami (1-indexed)
            per_page: Sahifadagi yozuvlar soni

        Returns:
            API javobini dict shaklida (data, total, last_page, current_page)
        """
        return self.client.request(
            method="GET",
            endpoint=DIRECTORY_ENDPOINT,
            params={"data": SLUG_WAREHOUSES, "page": page, "per_page": per_page},
        )

    def get_all(self, per_page: int = PAGE_SIZE):
        """
        Barcha sahifalarni ketma-ket o'qib, har bir recordni yield qilish.

        Yields:
            dict: "data" massividagi alohida warehouse yozuvlari
        """
        page = 1
        total_pages = None

        while True:
            response = self.get_page(page=page, per_page=per_page)
            records = response.get("data", [])

            if total_pages is None:
                total = response.get("total", 0)
                last_page = response.get("last_page")
                total_pages = last_page or max(1, -(-total // per_page))

            if not records:
                break

            yield from records

            if page >= total_pages or len(records) < per_page:
                break

            page += 1
