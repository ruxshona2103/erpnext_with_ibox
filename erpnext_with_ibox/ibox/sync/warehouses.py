# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Warehouse Sync Handler — iBox core_warehouse -> ERPNext Warehouse.
"""

from typing import Generator

import frappe

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class WarehouseSyncHandler(BaseSyncHandler):
    DOCTYPE = "Warehouse"
    NAME = "Omborlar"
    IBOX_ID_FIELD = "custom_ibox_warehouse_id"

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox omborlarni yield + total saqlash."""
        page = 1
        total_pages = None

        while True:
            response = self.api.warehouses.get_page(page=page, per_page=1000)
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
        warehouse_name = self._clean(record.get("name"), "Noma'lum ombor")

        # Company ni iBox Client documentdan avtomatik olish
        company = self.client_doc.company
        if not company:
            frappe.throw(f"iBox Client '{self.client_name}' da company belgilanmagan!")

        # Composite key bilan mavjudlikni tekshirish (ibox_id + ibox_client)
        existing = frappe.db.get_value(
            "Warehouse",
            {
                "custom_ibox_warehouse_id": ibox_id,
                "custom_ibox_client": self.client_name,
            },
            "name",
        )

        if existing:
            changed = False
            current = frappe.db.get_value(
                "Warehouse",
                existing,
                ["warehouse_name", "custom_ibox_warehouse_name"],
                as_dict=True,
            )

            if current.warehouse_name != warehouse_name or current.custom_ibox_warehouse_name != warehouse_name:
                frappe.db.set_value("Warehouse", existing, {
                    "warehouse_name": warehouse_name,
                    "custom_ibox_warehouse_name": warehouse_name,
                })
                changed = True
            return changed

        # Parent warehouse ni aniqlash
        parent = frappe.db.get_value(
            "Warehouse",
            {"is_group": 1, "company": company},
            "name",
        )

        frappe.get_doc({
            "doctype": "Warehouse",
            "warehouse_name": warehouse_name,
            "company": company,
            "parent_warehouse": parent,
            "custom_ibox_warehouse_id": ibox_id,
            "custom_ibox_warehouse_name": warehouse_name,
            "custom_ibox_client": self.client_name,
        }).insert(ignore_permissions=True)
        return True

    @staticmethod
    def _clean(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default
