# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sales Return API Endpoint — iBox sales return (credit note) ro'yxatlarini olish.

Endpoint:
  - /api/integration/document/return/list   (Sotuv vozvratlari)

Joriy faza:
  - faqat eng so'nggi 200 ta record olinadi
"""

import requests

from erpnext_with_ibox.ibox.config import (
    SALES_RETURN_ENDPOINT,
    SALES_RETURN_PAGE_SIZE,
)


class SalesReturnsEndpoint:
    """iBox sales return endpointi uchun handler."""

    def __init__(self, client):
        self.client = client

    def get_page(
        self,
        page: int = 1,
        per_page: int = SALES_RETURN_PAGE_SIZE,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> dict:
        """Bitta sahifa return data olish."""
        effective_per_page = min(int(per_page or SALES_RETURN_PAGE_SIZE), SALES_RETURN_PAGE_SIZE, 100)
        params = {"page": page, "per_page": effective_per_page}
        if period_from:
            params["period[from]"] = period_from
        if period_to:
            params["period[to]"] = period_to

        return self.client.request(
            method="GET",
            endpoint=SALES_RETURN_ENDPOINT,
            params=params,
        )

    def get_latest(
        self,
        limit: int = SALES_RETURN_PAGE_SIZE,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> dict:
        """Eng so'nggi return recordlarni olish (joriy limit bilan)."""
        preferred = min(int(limit or SALES_RETURN_PAGE_SIZE), SALES_RETURN_PAGE_SIZE, 100)
        candidates = [preferred, 50, 20, 10]

        tried = set()
        for per_page in candidates:
            if per_page in tried or per_page <= 0:
                continue
            tried.add(per_page)
            try:
                return self.get_page(
                    page=1,
                    per_page=per_page,
                    period_from=period_from,
                    period_to=period_to,
                )
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else 0
                if status_code != 422:
                    raise

        return self.get_page(page=1, per_page=10, period_from=period_from, period_to=period_to)


# Backward compatibility: eski nom bilan import qilingan joylar buzilmasin
SalesReturnEndpoint = SalesReturnsEndpoint