# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Stock Adjustment Sync Handler — iBox /api/document/stock-adjustment -> ERPNext Stock Reconciliation.

iBox inventarizatsiya hujjatlari → ERPNext Stock Reconciliation (DRAFT).

iBox API javobi (detail):
    {
        "id": 152530,
        "number": "161",
        "date": "2026-03-15T03:20:25.000000Z",
        "warehouse": {"id": 1, "name": "Asosiy ombor"},
        "stock_adjustment_details": [
            {
                "id": 112910,
                "product": {"id": 9055, "name": "..."},
                "quantity": 1,         # Haqiqiy soni (actual count)
                "stock": 0,            # Tizimda qolgan (system stock)
                "price": 0,
                "unit": {"short_name": "шт"}
            }
        ]
    }

ERPNext Stock Reconciliation:
    - purpose = "Stock Reconciliation"
    - items[]: item_code, warehouse, qty (actual), valuation_rate
"""

import time
from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class StockAdjustmentSyncHandler(BaseSyncHandler):
    DOCTYPE = "Stock Reconciliation"
    NAME = "Stock Adjustments (Inventarizatsiya)"

    IBOX_ID_FIELD = "custom_ibox_stock_adjustment_id"

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox API dan stock adjustment recordlarni yield qilish."""
        first_page = self.api.stock_adjustments.get_page(page=1, per_page=1)
        self.ibox_total = first_page.get("total", 0)

        for record in self.api.stock_adjustments.get_all(per_page=100, max_pages=2):
            yield record

    def upsert(self, record: dict) -> bool:
        """
        Bitta stock adjustment recordini ERPNext Stock Reconciliation ga yaratish.
        Deduplication key: custom_ibox_stock_adjustment_id + custom_ibox_client
        """
        ibox_id = record.get("id")
        if not ibox_id:
            return False

        # Deduplication
        existing = frappe.db.get_value(
            "Stock Reconciliation",
            {
                "custom_ibox_stock_adjustment_id": str(ibox_id),
                "custom_ibox_client": self.client_name,
            },
            "name",
        )
        if existing:
            return False

        company = self.client_doc.company
        raw_date = record.get("date", "")
        posting_date = self._parse_date(raw_date)
        posting_time = self._parse_time(raw_date)

        # Warehouse
        warehouse_data = record.get("warehouse") or {}
        warehouse_id = warehouse_data.get("id")
        warehouse_name = self._resolve_warehouse(warehouse_id)

        if not warehouse_name:
            fallback = getattr(self.client_doc, "default_warehouse", None)
            if fallback:
                warehouse_name = fallback
            else:
                frappe.log_error(
                    title=f"Stock Adjustment - Warehouse Not Found - {self.client_name}",
                    message=f"ibox_id={ibox_id}, warehouse_id={warehouse_id}",
                )
                return False

        # Details
        details = record.get("stock_adjustment_details") or []
        if not details:
            return False

        items = []
        for detail in details:
            product = detail.get("product") or {}
            product_id = product.get("id")
            item_code = self._resolve_item(product_id)

            if not item_code:
                continue

            qty = flt(detail.get("quantity", 0))
            valuation_rate = flt(detail.get("price", 0))

            # Agar valuation_rate 0 bo'lsa, mavjud item narxini olish
            if valuation_rate <= 0:
                valuation_rate = flt(
                    frappe.db.get_value("Item", item_code, "valuation_rate")
                ) or flt(
                    frappe.db.get_value(
                        "Bin",
                        {"item_code": item_code, "warehouse": warehouse_name},
                        "valuation_rate",
                    )
                )

            # Har bir item o'z detail warehouse ga ega bo'lishi mumkin
            # lekin stock-adjustment da warehouse header-level
            items.append({
                "item_code": item_code,
                "warehouse": warehouse_name,
                "qty": qty,
                "valuation_rate": valuation_rate if valuation_rate > 0 else 1,
            })

        if not items:
            return False

        try:
            doc = frappe.get_doc({
                "doctype": "Stock Reconciliation",
                "purpose": "Stock Reconciliation",
                "company": company,
                "posting_date": posting_date or frappe.utils.today(),
                "posting_time": posting_time,
                "set_posting_time": 1,
                "custom_ibox_stock_adjustment_id": str(ibox_id),
                "custom_ibox_client": self.client_name,
                "items": items,
            })
            doc.insert(ignore_permissions=True)
            return True

        except Exception:
            frappe.log_error(
                title=f"Stock Adjustment Upsert Error - {self.client_name}",
                message=f"ibox_id={ibox_id}\n{frappe.get_traceback()}",
            )
            return False

    def _resolve_warehouse(self, warehouse_id) -> str | None:
        """iBox warehouse_id → ERPNext Warehouse.name"""
        if not warehouse_id:
            return None
        return frappe.db.get_value(
            "Warehouse",
            {"custom_ibox_warehouse_id": warehouse_id, "custom_ibox_client": self.client_name},
            "name",
        )

    def _resolve_item(self, product_id) -> str | None:
        """iBox product_id → ERPNext Item.name"""
        if not product_id:
            return None
        return frappe.db.get_value(
            "Item",
            {"custom_ibox_id": product_id, "custom_ibox_client": self.client_name},
            "name",
        )

    @staticmethod
    def _parse_date(raw: str) -> str:
        if not raw:
            return ""
        return raw[:10]

    @staticmethod
    def _parse_time(raw: str) -> str:
        if not raw or "T" not in raw:
            return "00:00:00"
        time_part = raw[11:19]
        if len(time_part) < 8 or time_part.count(":") < 2:
            return "00:00:00"
        return time_part
