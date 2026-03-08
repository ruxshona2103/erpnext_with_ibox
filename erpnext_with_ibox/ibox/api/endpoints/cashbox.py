# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

from erpnext_with_ibox.ibox.config import CASHBOX_ENDPOINT, INTERNAL_PAGE_SIZE

class CashboxEndpoint:
    """Finance Cashbox API Endpoint Handler"""

    def __init__(self, client):
        self.client = client

    def get_list(self, active=True, page=1, per_page=INTERNAL_PAGE_SIZE):
        """
        Kassalar ro'yxatini olish.
        """
        filters = {}
        if active is not None:
            # iBox API filter parsing: filters={"active":[true]}
            filters["active"] = [True] if active else [False]
            
        import json
            
        params = {
            "filters": json.dumps(filters),
            "sort_by": "created_at",
            "desc": 1,
            "available": 1,
            "page": page,
            "per_page": per_page
        }

        # Request to /api/finance/cashbox
        return self.client.request(
            method="GET",
            endpoint=CASHBOX_ENDPOINT,
            params=params
        )

    def get_all(self, active=True):
        """Barcha kassalarni pagination orqali bitta ro'yxatga yig'ib qaytarish"""
        all_data = []
        page = 1

        while True:
            response = self.get_list(active=active, page=page, per_page=INTERNAL_PAGE_SIZE)
            data = response.get("data", [])
            
            if not data:
                break
                
            all_data.extend(data)
            
            # Agar 'last_page' bersa va joriy sahifa oxirgisi bo'lsa
            last_page = response.get("last_page")
            if last_page and page >= last_page:
                break
                
            # Agar qaytgan data so'ralgan per_page dan kam bo'lsa
            if len(data) < INTERNAL_PAGE_SIZE:
                 break
                 
            page += 1

        return all_data
