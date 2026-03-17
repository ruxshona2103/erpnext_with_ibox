# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Transfer Sync Handler — iBox /api/document/transfer -> ERPNext Stock Entry (Material Transfer).

iBox omborlar orasidagi ko'chirish → ERPNext Stock Entry (DRAFT).

iBox API javobi (detail):
    {
        "id": 152539,
        "number": "3927",
        "date": "2026-03-15T03:16:15.000000Z",
        "status": 51,
        "transfer_details": [
            {
                "id": 1080424,
                "product_id": 9221,
                "quantity": 1,
                "product": {"id": 9221, "name": "..."},
                "unit": {"short_name": "шт"}
            }
        ]
    }

Transfer da warehouse_from va warehouse_to list API dan olinadi.
Detail API da bu ma'lumot header level da yo'q, lekin list da bor.
Shuning uchun list dan warehouse nomlarini yig'ib, detail ga qo'shib yuboramiz.
"""

from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class TransferSyncHandler(BaseSyncHandler):
    DOCTYPE = "Stock Entry"
    NAME = "Transfers (Omborlar arasi ko'chirish)"
    NEEDS_INTERNAL_API = True

    IBOX_ID_FIELD = "custom_ibox_transfer_id"

    def __init__(self, api_client, client_doc, is_cleanup_job=False, internal_api=None):
        super().__init__(api_client, client_doc, is_cleanup_job=is_cleanup_job)
        self.internal_api = internal_api

    def fetch_data(self) -> Generator[dict, None, None]:
        """
        iBox Internal API dan transfer recordlarni yield qilish.

        List API dan warehouse_from/warehouse_to nomlarini olib,
        detail record ga qo'shib yuboramiz.
        """
        per_page = self.page_size or 100
        max_pages = self.max_pages or 0  # 0 = cheksiz
        page = 1

        first_page = self.internal_api.transfers.get_page(page=1, per_page=1)
        self.ibox_total = first_page.get("total", 0)

        import time
        from erpnext_with_ibox.ibox.config import API_PAGE_DELAY

        while page <= max_pages:
            response = self.internal_api.transfers.get_page(page=page, per_page=per_page)
            records = response.get("data", [])

            if not records:
                break

            for record in records:
                record_id = record.get("id")
                if not record_id:
                    continue

                # List dan warehouse nomlarini saqlab qo'yish
                wh_from_name = record.get("warehouse_from")
                wh_to_name = record.get("warehouse_to")

                try:
                    detail = self.internal_api.transfers.get_detail(record_id)
                    # Warehouse nomlarini detail ga qo'shish
                    detail["_warehouse_from_name"] = wh_from_name
                    detail["_warehouse_to_name"] = wh_to_name
                    yield detail
                except Exception:
                    continue

                time.sleep(0.5)

            total_pages = response.get("last_page", 1)
            if page >= total_pages or len(records) < per_page:
                break

            time.sleep(API_PAGE_DELAY)
            page += 1

    def upsert(self, record: dict) -> bool:
        """
        Bitta transfer recordini ERPNext Stock Entry (Material Transfer) ga yaratish.
        Deduplication key: custom_ibox_transfer_id + custom_ibox_client
        """
        ibox_id = record.get("id")
        if not ibox_id:
            return False

        # Deduplication
        existing = frappe.db.get_value(
            "Stock Entry",
            {
                "custom_ibox_transfer_id": str(ibox_id),
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

        # Warehouse from/to — list API dan qo'shilgan
        wh_from_name = record.get("_warehouse_from_name")
        wh_to_name = record.get("_warehouse_to_name")

        # ERPNext warehouse nomi topish
        source_warehouse = self._resolve_warehouse_by_name(wh_from_name)
        target_warehouse = self._resolve_warehouse_by_name(wh_to_name)

        if not source_warehouse or not target_warehouse:
            frappe.log_error(
                title=f"Transfer - Warehouse Not Found - {self.client_name}",
                message=(
                    f"ibox_id={ibox_id}, "
                    f"from={wh_from_name} -> {source_warehouse}, "
                    f"to={wh_to_name} -> {target_warehouse}"
                ),
            )
            return False

        # Details
        details = record.get("transfer_details") or []
        if not details:
            return False

        items = []
        for detail in details:
            product = detail.get("product") or {}
            product_id = detail.get("product_id") or product.get("id")
            item_code = self._resolve_item(product_id)

            if not item_code:
                continue

            qty = flt(detail.get("quantity", 0))
            if qty <= 0:
                continue

            # Stock Entry item uchun basic_rate (valuation uchun)
            basic_rate = flt(detail.get("price", 0))
            if basic_rate <= 0:
                basic_rate = flt(
                    frappe.db.get_value("Item", item_code, "valuation_rate")
                ) or flt(
                    frappe.db.get_value(
                        "Bin",
                        {"item_code": item_code, "warehouse": source_warehouse},
                        "valuation_rate",
                    )
                )

            uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

            items.append({
                "item_code": item_code,
                "qty": qty,
                "uom": uom,
                "stock_uom": uom,
                "conversion_factor": 1,
                "s_warehouse": source_warehouse,
                "t_warehouse": target_warehouse,
                "basic_rate": basic_rate if basic_rate > 0 else 0,
                "allow_zero_valuation_rate": 1 if basic_rate <= 0 else 0,
            })

        if not items:
            return False

        try:
            doc = frappe.get_doc({
                "doctype": "Stock Entry",
                "stock_entry_type": "Material Transfer",
                "company": company,
                "posting_date": posting_date or frappe.utils.today(),
                "posting_time": posting_time,
                "set_posting_time": 1,
                "custom_ibox_transfer_id": str(ibox_id),
                "custom_ibox_client": self.client_name,
                "items": items,
            })
            doc.insert(ignore_permissions=True)
            return True

        except Exception:
            frappe.log_error(
                title=f"Transfer Upsert Error - {self.client_name}",
                message=f"ibox_id={ibox_id}\n{frappe.get_traceback()}",
            )
            return False

    def _resolve_warehouse_by_name(self, ibox_warehouse_name: str) -> str | None:
        """
        iBox warehouse nomi → ERPNext Warehouse.name

        iBox dagi "Asosiy ombor", "Magazin", "Showroom" nomlarini
        custom_ibox_warehouse_name orqali ERPNext da topish.
        """
        if not ibox_warehouse_name:
            return None

        # Avval custom_ibox_warehouse_name bo'yicha qidirish
        result = frappe.db.get_value(
            "Warehouse",
            {
                "custom_ibox_warehouse_name": ibox_warehouse_name,
                "custom_ibox_client": self.client_name,
            },
            "name",
        )
        if result:
            return result

        # Fallback: warehouse_name bo'yicha qidirish
        result = frappe.db.get_value(
            "Warehouse",
            {"warehouse_name": ibox_warehouse_name},
            "name",
        )
        return result

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
