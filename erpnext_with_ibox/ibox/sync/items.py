# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Item Sync Handler — iBox product_product -> ERPNext Item.
"""

import re
from typing import Generator

import frappe

from erpnext_with_ibox.ibox.config import SLUG_ITEMS
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class ItemSyncHandler(BaseSyncHandler):
    DOCTYPE = "Item"
    NAME = "Items"

    def fetch_data(self) -> Generator[dict, None, None]:
        yield from self.api.directory.get_all(slug=SLUG_ITEMS)

    def upsert(self, record: dict) -> bool:
        ibox_id = record.get("id")
        item_name = self._clean(record.get("name"), "Noma'lum mahsulot")
        item_code = self._sanitize(item_name)[:140] or f"IBOX-{ibox_id}"

        item_group = (
            "Products"
            if frappe.db.exists("Item Group", "Products")
            else "All Item Groups"
        )

        existing = frappe.db.get_value(
            "Item",
            {"custom_ibox_id": ibox_id, "custom_ibox_client": self.client_name},
            "name",
        )

        if existing:
            changed = False
            if frappe.db.get_value("Item", existing, "item_name") != item_name:
                frappe.db.set_value("Item", existing, {
                    "item_name": item_name,
                    "item_code": item_code,
                })
                changed = True
            return changed

        frappe.get_doc({
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_name,
            "item_group": item_group,
            "stock_uom": "Nos",
            "is_stock_item": 1,
            "is_sales_item": 1,
            "is_purchase_item": 1,
            "custom_ibox_id": ibox_id,
            "custom_ibox_client": self.client_name,
        }).insert(ignore_permissions=True)
        return True

    @staticmethod
    def _clean(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default

    @staticmethod
    def _sanitize(text: str) -> str:
        return re.sub(r"[^A-Za-z0-9\u0400-\u04FF\s.\-]", "", text).strip()
