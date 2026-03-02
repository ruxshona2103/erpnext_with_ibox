# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Purchase API Endpoint — iBox xarid va vozvrat ro'yxatlarini olish.

Ikki endpoint bilan ishlaydi:
  - /api/integration/document/purchase/list         (Xaridlar)
  - /api/integration/document/supplier-return/list   (Vozvratlar / Debit Note)
"""

from erpnext_with_ibox.ibox.config import (
    PURCHASE_ENDPOINT,
    PURCHASE_RETURN_ENDPOINT,
    PURCHASE_PAGE_SIZE,
)


class PurchaseEndpoint:
    """
    iBox Purchase va Purchase Return endpointlari uchun handler.

    Har bir endpoint alohida get_page/get_all juftligiga ega.
    Recordlar yield qilinganida har biriga `_is_return` flag qo'shiladi
    — sync handler bu flag orqali Purchase Invoice yoki Debit Note yaratishni aniqlaydi.
    """

    def __init__(self, client):
        self.client = client

    # ── Purchase (Xarid) ──────────────────────────────────────────────

    def get_purchase_page(self, page: int = 1, per_page: int = PURCHASE_PAGE_SIZE) -> dict:
        """Bitta sahifa xarid data olish."""
        return self.client.request(
            method="GET",
            endpoint=PURCHASE_ENDPOINT,
            params={"page": page, "per_page": per_page},
        )

    def get_all_purchases(self, per_page: int = PURCHASE_PAGE_SIZE):
        """
        Barcha xarid sahifalarini o'qib, har bir recordni yield qilish.

        Yields:
            dict: Har bir record + _is_return=False flag
        """
        page = 1
        total_pages = None

        while True:
            response = self.get_purchase_page(page=page, per_page=per_page)
            records = response.get("data", [])

            if total_pages is None:
                total_pages = response.get("last_page", 1)

            if not records:
                break

            for record in records:
                record["_is_return"] = False
                yield record

            if page >= total_pages or len(records) < per_page:
                break

            page += 1

    # ── Purchase Return (Vozvrat) ─────────────────────────────────────

    def get_return_page(self, page: int = 1, per_page: int = PURCHASE_PAGE_SIZE) -> dict:
        """Bitta sahifa vozvrat data olish."""
        return self.client.request(
            method="GET",
            endpoint=PURCHASE_RETURN_ENDPOINT,
            params={"page": page, "per_page": per_page},
        )

    def get_all_returns(self, per_page: int = PURCHASE_PAGE_SIZE):
        """
        Barcha vozvrat sahifalarini o'qib, har bir recordni yield qilish.

        Yields:
            dict: Har bir record + _is_return=True flag
        """
        page = 1
        total_pages = None

        while True:
            response = self.get_return_page(page=page, per_page=per_page)
            records = response.get("data", [])

            if total_pages is None:
                total_pages = response.get("last_page", 1)

            if not records:
                break

            for record in records:
                record["_is_return"] = True
                yield record

            if page >= total_pages or len(records) < per_page:
                break

            page += 1

    # ── Combined Generator ────────────────────────────────────────────

    def get_all(self, per_page: int = PURCHASE_PAGE_SIZE):
        """
        Avval barcha xaridlar, keyin barcha vozvratlarni yield qilish.
        Har bir record'da _is_return flag bor.

        Yields:
            dict: Xarid yoki vozvrat record (with _is_return flag)
        """
        yield from self.get_all_purchases(per_page=per_page)
        yield from self.get_all_returns(per_page=per_page)
