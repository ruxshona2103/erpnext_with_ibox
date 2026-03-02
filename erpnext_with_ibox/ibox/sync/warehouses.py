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
    NAME = "Warehouses"

    def fetch_data(self) -> Generator[dict, None, None]:
        yield from self.api.warehouses.get_all()

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
