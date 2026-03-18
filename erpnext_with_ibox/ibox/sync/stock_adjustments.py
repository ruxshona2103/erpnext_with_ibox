# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Stock Adjustment Sync Handler — iBox /api/document/stock-adjustment -> ERPNext Stock Entry.

iBox inventarizatsiya hujjatlari → ERPNext Stock Entry (DRAFT).

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
                "quantity": 2,         # Delta: +2 = ortiqcha topildi
                "stock": 5,            # Tizimda qolgan (system stock)
                "price": 0,
                "unit": {"short_name": "шт"}
            },
            {
                "quantity": -1,        # Delta: -1 = kam topildi (chiqib ketdi)
                "stock": 3,
            }
        ]
    }

quantity — DELTA (farq):
    +N → ortiqcha topildi → Material Receipt (omborga kiritish)
    -N → kam topildi → Material Issue (ombordan chiqarish)

Bitta iBox adjustment dan 2 ta Stock Entry yaratilishi mumkin:
    1. Material Receipt — barcha qty > 0 itemlar
    2. Material Issue — barcha qty < 0 itemlar
"""

from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class StockAdjustmentSyncHandler(BaseSyncHandler):
    DOCTYPE = "Stock Entry"
    NAME = "Stock Adjustments (Inventarizatsiya)"
    NEEDS_INTERNAL_API = True

    IBOX_ID_FIELD = "custom_ibox_stock_adjustment_id"

    def __init__(self, api_client, client_doc, is_cleanup_job=False, internal_api=None):
        super().__init__(api_client, client_doc, is_cleanup_job=is_cleanup_job)
        self.internal_api = internal_api

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox Internal API dan stock adjustment recordlarni yield qilish."""
        per_page = self.page_size or 100
        max_pages = self.max_pages or 0  # 0 = cheksiz

        first_page = self.internal_api.stock_adjustments.get_page(page=1, per_page=1)
        self.ibox_total = first_page.get("total", 0)

        for record in self.internal_api.stock_adjustments.get_all(per_page=per_page, max_pages=max_pages):
            yield record

    def upsert(self, record: dict) -> bool:
        """
        Bitta stock adjustment recordini ERPNext Stock Entry ga yaratish.

        quantity > 0 → Material Receipt (ortiqcha topildi, omborga kiritamiz)
        quantity < 0 → Material Issue (kam topildi, ombordan chiqaramiz)

        Bitta iBox hujjatda ham plus ham minus bo'lishi mumkin —
        shuning uchun 2 ta Stock Entry yaratiladi.
        """
        ibox_id = record.get("id")
        if not ibox_id:
            return False

        # Deduplication
        existing = frappe.db.get_value(
            "Stock Entry",
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
        posting_date = self._parse_date(raw_date) or frappe.utils.today()
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

        # Detaillarni plus va minus ga ajratish
        details = record.get("stock_adjustment_details") or []
        if not details:
            return False

        receipt_items = []  # qty > 0 → Material Receipt
        issue_items = []    # qty < 0 → Material Issue

        for detail in details:
            product = detail.get("product") or {}
            product_id = product.get("id")
            item_code = self._resolve_item(product_id)

            if not item_code:
                continue

            qty = flt(detail.get("quantity", 0))
            if qty == 0:
                continue

            uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

            item_row = {
                "item_code": item_code,
                "qty": abs(qty),
                "uom": uom,
                "stock_uom": uom,
                "conversion_factor": 1,
                "basic_rate": 0,
                "allow_zero_valuation_rate": 1,
            }

            if qty > 0:
                # Material Receipt — omborga kirish (t_warehouse)
                item_row["t_warehouse"] = warehouse_name
                receipt_items.append(item_row)
            else:
                # Material Issue — ombordan chiqish (s_warehouse)
                item_row["s_warehouse"] = warehouse_name
                issue_items.append(item_row)

        if not receipt_items and not issue_items:
            return False

        created = False

        # Orphan Cleanup uchun: agar issue_items bor bo'lsa, "{id}-issue" ni ham active ID ga qo'shish
        # (base.run() faqat "{id}" qo'shadi, lekin biz 2 ta Stock Entry yaratamiz)
        if issue_items and receipt_items:
            self._active_ibox_ids.add(f"{ibox_id}-issue")

        # 1) Material Receipt (ortiqcha topilgan mahsulotlar)
        if receipt_items:
            try:
                doc = frappe.get_doc({
                    "doctype": "Stock Entry",
                    "stock_entry_type": "Material Receipt",
                    "company": company,
                    "posting_date": posting_date,
                    "posting_time": posting_time,
                    "set_posting_time": 1,
                    "custom_ibox_stock_adjustment_id": str(ibox_id),
                    "custom_ibox_client": self.client_name,
                    "remarks": f"iBox Inventarizatsiya #{record.get('number', '')} — Ortiqcha (+)",
                    "items": receipt_items,
                })
                doc.insert(ignore_permissions=True)
                self._force_zero_rates(doc)
                created = True
            except Exception:
                frappe.log_error(
                    title=f"Stock Adjustment Receipt Error - {self.client_name}",
                    message=f"ibox_id={ibox_id}\n{frappe.get_traceback()}",
                )

        # 2) Material Issue (kam topilgan mahsulotlar)
        if issue_items:
            try:
                # Agar receipt ham bor bo'lsa, ibox_id ga suffix qo'shamiz
                adj_id = f"{ibox_id}-issue" if created else str(ibox_id)
                doc = frappe.get_doc({
                    "doctype": "Stock Entry",
                    "stock_entry_type": "Material Issue",
                    "company": company,
                    "posting_date": posting_date,
                    "posting_time": posting_time,
                    "set_posting_time": 1,
                    "custom_ibox_stock_adjustment_id": adj_id,
                    "custom_ibox_client": self.client_name,
                    "remarks": f"iBox Inventarizatsiya #{record.get('number', '')} — Kamomad (-)",
                    "items": issue_items,
                })
                doc.insert(ignore_permissions=True)
                self._force_zero_rates(doc)
                created = True
            except Exception:
                frappe.log_error(
                    title=f"Stock Adjustment Issue Error - {self.client_name}",
                    message=f"ibox_id={ibox_id}\n{frappe.get_traceback()}",
                )

        return created

    @staticmethod
    def _force_zero_rates(doc):
        """Insert dan keyin ERPNext auto-set qilgan basic_rate larni 0 ga qaytarish."""
        for item in doc.items:
            if item.basic_rate != 0:
                frappe.db.set_value(
                    "Stock Entry Detail", item.name,
                    {"basic_rate": 0, "basic_amount": 0, "amount": 0},
                    update_modified=False,
                )
        frappe.db.set_value(
            "Stock Entry", doc.name,
            {"total_incoming_value": 0, "total_outgoing_value": 0, "value_difference": 0},
            update_modified=False,
        )

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
