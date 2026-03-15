# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Item Sync Handler — iBox product_product -> ERPNext Item.
"""

import re
import time
from typing import Generator

import frappe

from erpnext_with_ibox.ibox.config import SLUG_ITEMS, API_PAGE_DELAY
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class ItemSyncHandler(BaseSyncHandler):
    DOCTYPE = "Item"
    NAME = "Mahsulotlar"
    IBOX_ID_FIELD = "custom_ibox_id"

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox directory API dan mahsulotlarni yield qilish + total ni saqlash."""
        page = 1
        total_pages = None

        while True:
            response = self.api.directory.get_page(slug=SLUG_ITEMS, page=page, per_page=1000)
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

            time.sleep(API_PAGE_DELAY)
            page += 1

    def upsert(self, record: dict) -> bool:
        ibox_id = record.get("id")
        item_name = self._clean(record.get("name"), "Noma'lum mahsulot")
        base_code = self._sanitize(item_name)[:130] or f"IBOX-{ibox_id}"
        item_code = base_code

        dup = frappe.db.get_value(
            "Item",
            {"name": item_code},
            ["name", "custom_ibox_id"],
            as_dict=True,
        )
        if dup and str(dup.custom_ibox_id) != str(ibox_id):
            item_code = f"{base_code}-{ibox_id}"

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

        doc = frappe.get_doc({
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
        })
        doc.flags.ignore_validate = True
        doc.insert(ignore_permissions=True)
        return True

    @staticmethod
    def _clean(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default

    @staticmethod
    def _sanitize(text: str) -> str:
        return re.sub(r"[^A-Za-z0-9\u0400-\u04FF\s.\-]", "", text).strip()
