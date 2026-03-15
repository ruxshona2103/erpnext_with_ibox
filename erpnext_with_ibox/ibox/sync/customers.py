# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Customer Sync Handler — iBox outlet_client -> ERPNext Customer.
"""

from typing import Generator

import frappe

from erpnext_with_ibox.ibox.config import SLUG_CUSTOMERS
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class CustomerSyncHandler(BaseSyncHandler):
    DOCTYPE = "Customer"
    NAME = "Mijozlar"
    IBOX_ID_FIELD = "custom_ibox_id"

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox mijozlarni yield + total saqlash."""
        page = 1
        total_pages = None

        while True:
            response = self.api.directory.get_page(slug=SLUG_CUSTOMERS, page=page, per_page=1000)
            records = response.get("data", [])

            if total_pages is None:
                self.ibox_total = response.get("total", 0)
                last_page = response.get("last_page")
                total_pages = last_page or max(1, -(-self.ibox_total // 1000))

            if not records:
                break

            yield from records

            if page >= total_pages or len(records) < 1000:
                break

            import time
            from erpnext_with_ibox.ibox.config import API_PAGE_DELAY
            time.sleep(API_PAGE_DELAY)
            page += 1

    def upsert(self, record: dict) -> bool:
        ibox_id = record.get("id")
        name = self._clean(record.get("name"), "Noma'lum mijoz")
        phone = self._clean(record.get("main_phone"))

        existing = frappe.db.get_value(
            "Customer",
            {"custom_ibox_id": ibox_id, "custom_ibox_client": self.client_name},
            "name",
        )

        if existing:
            changed = False
            if frappe.db.get_value("Customer", existing, "customer_name") != name:
                frappe.db.set_value("Customer", existing, "customer_name", name)
                changed = True
            if phone and frappe.db.get_value("Customer", existing, "custom_main_phone") != phone:
                frappe.db.set_value("Customer", existing, "custom_main_phone", phone)
                changed = True
            return changed

        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": name,
            "customer_type": "Individual",
            "customer_group": "All Customer Groups",
            "territory": "All Territories",
            "custom_ibox_id": ibox_id,
            "custom_ibox_client": self.client_name,
            "custom_main_phone": phone,
        }).insert(ignore_permissions=True)
        return True

    @staticmethod
    def _clean(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default
