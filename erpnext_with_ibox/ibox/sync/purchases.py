# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Purchase Sync Handler — iBox purchase/list va supplier-return/list -> ERPNext Purchase Invoice.

Xarid (purchase)  → Purchase Invoice (is_return=0, docstatus=0)
Vozvrat (return)   → Purchase Invoice / Debit Note (is_return=1, docstatus=0)

Barcha hujjatlar DRAFT holatda saqlanadi.

Verified Field Names:
  Parent (Purchase Invoice):
    - custom_ibox_purchase_id   — iBox dagi xarid ID (deduplication key)
    - custom_ibox_client        — qaysi iBox Client dan kelgan
    - custom_ibox_total         — iBox dagi umumiy summa

  Child (Purchase Invoice Item):
    - custom_ibox_detail_id     — iBox dagi detail ID
    - custom_ibox_warehouse_id  — iBox dagi ombor ID

Lookup Fields:
    - Supplier:  custom_ibox_id          (Supplier doctype)
    - Warehouse: custom_ibox_warehouse_id (Warehouse doctype)
    - Item:      custom_ibox_id          (Item doctype)

Warehouse Fallback Zanjiri:
    1. Header dagi warehouse_id → Warehouse lookup
    2. Detail qatoridagi warehouse_id → Warehouse lookup
    3. iBox Client.default_warehouse → to'g'ridan-to'g'ri ishlatish
    4. Yuqoridagilarning barchasi None → log + skip
"""

from typing import Generator

import frappe
from frappe.utils import getdate

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class PurchaseSyncHandler(BaseSyncHandler):
    DOCTYPE = "Purchase Invoice"
    NAME = "Purchases"

    # Mirror Sync: iBox ID field nomi (deduplication va cleanup uchun)
    IBOX_ID_FIELD = "custom_ibox_purchase_id"

    # Sync mode: None = hammasi, "purchases" = faqat xarid, "returns" = faqat vozvrat
    SYNC_MODE: str | None = None

    def __init__(self, api_client, client_doc, is_cleanup_job=False):
        super().__init__(api_client, client_doc, is_cleanup_job=is_cleanup_job)
        # Per-sync-run cache: {date_str: rate} — DB ni har safar so'ramaslik uchun
        self._rate_cache: dict[str, float] = {}
        # Retry: birinchi urinishda skip qilingan recordlar (item/supplier/warehouse topilmagan)
        self._retry_queue: list[dict] = []

    def run(self) -> dict:
        """
        Override: BaseSyncHandler.run() + retry logikasi.

        100% Mirror Sync — HECH QACHON farq bo'lmasligi kerak:
          1. Asosiy sync — barcha recordlarni upsert qilish
          2. Retry — birinchi urinishda skip qilinganlarni qayta urinish
             (master data parallel sync qilingan bo'lishi mumkin)
          3. Cleanup — iBox da yo'q bo'lgan orphanlarni o'chirish
        """
        result = super().run()

        # ── Retry: skip qilingan recordlarni qayta urinish ───────────
        if self._retry_queue:
            retry_count = len(self._retry_queue)
            self._set_status(
                f"{self.NAME}: {retry_count} ta skip qilingan recordni qayta urinish..."
            )

            retry_synced = 0
            retry_errors = 0

            for record in self._retry_queue:
                try:
                    if self.upsert(record):
                        retry_synced += 1
                except Exception:
                    retry_errors += 1
                    frappe.log_error(
                        title=f"{self.NAME} Retry Error - {self.client_name}",
                        message=(
                            f"record_id={record.get('id')}\n"
                            f"{frappe.get_traceback()}"
                        ),
                    )

            frappe.db.commit()

            if retry_synced > 0 or retry_errors > 0:
                result["retry_synced"] = retry_synced
                result["retry_errors"] = retry_errors
                result["synced"] = result.get("synced", 0) + retry_synced

            # Retry dan keyin yakuniy holat
            erp_count = self._get_erp_count()
            cleanup = result.get("cleanup", {})
            deleted = cleanup.get("deleted", 0) if cleanup else 0
            cleanup_str = f", 🗑️ {deleted} ta o'chirildi" if deleted else ""
            still_missing = retry_count - retry_synced
            missing_str = f", ⚠️ {still_missing} ta import qilib bo'lmadi" if still_missing > 0 else ""

            self._set_status(
                f"Tayyor: iBox: {self.ibox_total} | ERPNext: {erp_count} "
                f"({result.get('synced', 0)} ta yangi, "
                f"{result.get('errors', 0)} ta xato{cleanup_str}{missing_str})"
            )

        return result

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox API dan xarid va/yoki vozvrat recordlarni yield qilish."""
        mode = getattr(self, "_sync_mode", None)
        if mode == "purchases":
            yield from self.api.purchases.get_all_purchases()
        elif mode == "returns":
            yield from self.api.purchases.get_all_returns()
        else:
            # Ikkalasi ham (default)
            yield from self.api.purchases.get_all()

    def upsert(self, record: dict) -> bool:
        """
        Bitta purchase/return recordni Purchase Invoice sifatida yaratish.
        Deduplication key: custom_ibox_purchase_id + custom_ibox_client
        """
        ibox_id = record.get("id")
        is_return = record.get("_is_return", False)
        doc_label = "Vozvrat" if is_return else "Xarid"

        # ── 1) Deduplication ───────────────────────────────────────────
        #   docstatus < 2 → Draft (0) yoki Submitted (1) mavjud bo'lsa skip.
        #   Cancelled (2) bo'lsa → qayta import qilish mumkin.
        existing = frappe.db.get_value(
            "Purchase Invoice",
            {
                "custom_ibox_purchase_id": ibox_id,
                "custom_ibox_client": self.client_name,
                "docstatus": ["<", 2],
            },
            "name",
        )
        if existing:
            return False  # allaqachon import qilingan (Draft yoki Submitted)

        # ── 2) Company ────────────────────────────────────────────────
        company = self.client_doc.company
        if not company:
            frappe.log_error(
                title=f"{doc_label} Sync - Company yo'q - {self.client_name}",
                message=f"iBox Client '{self.client_name}' da company belgilanmagan!",
            )
            return False

        # ── 3) Supplier lookup ────────────────────────────────────────
        outlet_id = record.get("outlet_id")
        supplier_name = self._resolve_supplier(outlet_id)
        if not supplier_name:
            # Retry queuega tashlash — keyinroq master data sync bo'lgandan keyin urinish
            if not record.get("_is_retry"):
                record["_is_retry"] = True
                self._retry_queue.append(record)
            else:
                frappe.log_error(
                    title=f"{doc_label} Sync - Supplier topilmadi - {self.client_name}",
                    message=(
                        f"ibox_purchase_id={ibox_id}, outlet_id={outlet_id}\n"
                        f"ERPNext'da custom_ibox_id={outlet_id} bo'lgan Supplier "
                        f"topilmadi. Retry ham muvaffaqiyatsiz."
                    ),
                )
            return False

        # ── 4) Warehouse lookup ────────────────────────────────────────
        # warehouse_id HEADER da yo'q — faqat detail qatorlarida bor.
        # Tartib: purchase_details → shipment_details → supplier_return_details → default_warehouse
        details_arrays = [
            record.get("purchase_details"),
            record.get("shipment_details"),
            record.get("supplier_return_details"),
            record.get("details"),
        ]

        warehouse_id = None
        for arr in details_arrays:
            if arr and len(arr) > 0:
                warehouse_id = arr[0].get("warehouse_id")
                if warehouse_id:
                    break

        # DB dan warehouse nomini olish
        warehouse_name = self._resolve_warehouse(warehouse_id)

        # Fallback: iBox Client.default_warehouse
        if not warehouse_name:
            fallback = getattr(self.client_doc, "default_warehouse", None)
            if fallback:
                warehouse_name = fallback
            else:
                if not record.get("_is_retry"):
                    record["_is_retry"] = True
                    self._retry_queue.append(record)
                else:
                    frappe.log_error(
                        title=f"{doc_label} Sync - Warehouse topilmadi - {self.client_name}",
                        message=(
                            f"ibox_purchase_id={ibox_id}, warehouse_id={warehouse_id}\n"
                            f"API detail qatorlarida warehouse_id yo'q va iBox Client da "
                            f"default_warehouse ham belgilanmagan.\n"
                            f"Yechim: iBox Client → 'Default Warehouse (Fallback)' ni to'ldiring."
                        ),
                    )
                return False

        # ── 5) Currency va Account ────────────────────────────────────
        currency_code = self._clean(record.get("currency_code"), "UZS").upper()
        currency, credit_to = self._resolve_currency_account(currency_code)

        if not credit_to:
            frappe.log_error(
                title=f"{doc_label} Sync - Account topilmadi - {self.client_name}",
                message=(
                    f"ibox_purchase_id={ibox_id}, currency={currency_code}\n"
                    f"iBox Client '{self.client_name}' da "
                    f"{'uzs' if currency == 'UZS' else 'usd'}_payable_account "
                    f"belgilanmagan! Record o'tkazib yuborildi."
                ),
            )
            return False

        # ── 5.1) Conversion Rate — valyuta kursi ──────────────────────
        posting_date = record.get("date", "")[:10]  # "2026-01-31T03:41:..." → "2026-01-31"
        conversion_rate = self._get_conversion_rate(posting_date, currency)

        if currency == "USD" and (not conversion_rate or conversion_rate <= 0):
            frappe.log_error(
                title=f"CRITICAL: {doc_label} Sync - Exchange Rate topilmadi - {self.client_name}",
                message=(
                    f"ibox_purchase_id={ibox_id}, date={posting_date}, currency=USD\n"
                    f"Currency Exchange jadvalida mos kurs topilmadi!\n"
                    f"Avval 'Valyuta Kurslarini Yuklash' tugmasini bosing."
                ),
            )
            return False

        # ── 6) iBox Total ─────────────────────────────────────────────
        ibox_total = self._parse_float(
            record.get("total") or record.get("amount") or record.get("sum")
        )

        # ── 7) Item table ─────────────────────────────────────────────
        details = (
            record.get("purchase_details")
            or record.get("shipment_details")
            or record.get("supplier_return_details")
            or record.get("details")
            or []
        )
        items = []

        for detail in details:
            product_id = detail.get("product_id")
            item_code = self._resolve_item(product_id)

            if not item_code:
                # Item topilmadi — bu detail qatorini skip
                # Agar barcha itemlar topilmasa, record retry queuega tushadi
                continue

            # Row-level warehouse (header dan ustun turadi)
            row_wh_id = detail.get("warehouse_id") or warehouse_id
            row_wh_name = self._resolve_warehouse(row_wh_id) or warehouse_name

            qty = abs(self._parse_float(
                detail.get("quantity") or detail.get("qty")
            ))
            # ERPNext vozvrat uchun manfiy qty talab qiladi
            if is_return:
                qty = -qty

            final_qty = qty if qty != 0 else (-1 if is_return else 1)

            # ── UOM — Item dan stock_uom olish ───────────────────────
            uom = self._resolve_uom(item_code)

            # ── Rate — iBox dan haqiqiy narx ─────────────────────────
            rate = abs(self._parse_float(
                detail.get("price") or detail.get("cost") or detail.get("rate") or 0
            ))
            amount = abs(self._parse_float(detail.get("amount"))) or (abs(final_qty) * rate)
            if is_return:
                amount = -amount

            # ── Item Name ─────────────────────────────────────────────
            item_name = self._resolve_item_name(item_code)

            items.append({
                "item_code": item_code,
                "item_name": item_name,
                "warehouse": row_wh_name,
                "qty": final_qty,
                "rate": rate,
                "amount": amount,
                "base_rate": rate * conversion_rate,
                "base_amount": amount * conversion_rate,
                "uom": uom,
                "stock_uom": uom,
                "stock_qty": final_qty,
                "conversion_factor": 1,
                "custom_ibox_detail_id": detail.get("id"),
                "custom_ibox_warehouse_id": row_wh_id,
            })

        if not items:
            if not record.get("_is_retry"):
                record["_is_retry"] = True
                self._retry_queue.append(record)
            else:
                frappe.log_error(
                    title=f"{doc_label} Sync - Bo'sh items - {self.client_name}",
                    message=(
                        f"ibox_purchase_id={ibox_id}: Hech qanday item mapping "
                        f"topilmadi. Retry ham muvaffaqiyatsiz."
                    ),
                )
            return False

        # ── 8) Purchase Invoice DRAFT ─────────────────────────────────
        pi = frappe.new_doc("Purchase Invoice")
        pi.supplier = supplier_name
        pi.company = company
        pi.currency = currency
        pi.credit_to = credit_to
        pi.buying_price_list = "Standard Buying"
        pi.price_list_currency = currency
        pi.conversion_rate = conversion_rate
        pi.plc_conversion_rate = conversion_rate
        pi.is_return = 1 if is_return else 0
        pi.update_stock = 1
        pi.set_warehouse = warehouse_name
        pi.custom_ibox_purchase_id = ibox_id
        pi.custom_ibox_client = self.client_name
        pi.custom_ibox_total = ibox_total

        for row in items:
            pi.append("items", row)

        # ── 8.1) set_missing_values() → keyin OVERWRITE ─────────────
        #    set_missing_values har xil default qiymatlarni to'ldiradi.
        #    Property Setter orqali item_name uzunligi 1000 ga ko'tarilgan,
        #    shuning uchun insert_item_price patchga hojat yo'q.
        from unittest.mock import patch

        with patch(
            "erpnext.controllers.accounts_controller.get_exchange_rate",
            return_value=conversion_rate,
        ):
            pi.set_missing_values()

        # OVERWRITE — set_missing_values qayta yozgan bo'lishi mumkin
        pi.currency = currency
        pi.credit_to = credit_to
        pi.conversion_rate = conversion_rate
        pi.plc_conversion_rate = conversion_rate

        with patch(
            "erpnext.controllers.accounts_controller.get_exchange_rate",
            return_value=conversion_rate,
        ):
            pi.insert(ignore_permissions=True)

        # ── 9) Har bir muvaffaqiyatli hujjatdan keyin commit ─────────
        frappe.db.commit()

        return True

    # ══════════════════════════════════════════════════════════════════
    # Resolver Methods
    # ══════════════════════════════════════════════════════════════════

    def _resolve_supplier(self, outlet_id) -> str | None:
        """
        iBox outlet_id → ERPNext Supplier.name  (field: custom_ibox_id)

        Topilmasa → placeholder Supplier avtomatik yaratiladi.
        Bu 100% mirror sync kafolatini beradi — hech qanday purchase
        supplier topilmaganidan skip qilinmaydi.
        """
        if not outlet_id:
            return None
        name = frappe.db.get_value(
            "Supplier",
            {"custom_ibox_id": outlet_id, "custom_ibox_client": self.client_name},
            "name",
        )
        if name:
            return name

        # Auto-create: placeholder supplier
        try:
            supplier_name = f"iBox-Supplier-{outlet_id}"
            doc = frappe.new_doc("Supplier")
            doc.supplier_name = supplier_name
            doc.supplier_group = "All Supplier Groups"
            doc.custom_ibox_id = str(outlet_id)
            doc.custom_ibox_client = self.client_name
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            frappe.log_error(
                title=f"Auto-created Supplier - {self.client_name}",
                message=f"Supplier '{supplier_name}' (ibox_id={outlet_id}) avtomatik yaratildi.",
            )
            return doc.name
        except Exception:
            frappe.log_error(
                title=f"Supplier Auto-Create Error - {self.client_name}",
                message=f"outlet_id={outlet_id}\n{frappe.get_traceback()}",
            )
            return None

    def _resolve_warehouse(self, warehouse_id) -> str | None:
        """iBox warehouse_id → ERPNext Warehouse.name  (field: custom_ibox_warehouse_id)"""
        if not warehouse_id:
            return None
        return frappe.db.get_value(
            "Warehouse",
            {"custom_ibox_warehouse_id": warehouse_id, "custom_ibox_client": self.client_name},
            "name",
        )

    def _resolve_item(self, product_id) -> str | None:
        """
        iBox product_id → ERPNext Item.name  (field: custom_ibox_id)

        Topilmasa → placeholder Item avtomatik yaratiladi.
        Bu 100% mirror sync kafolatini beradi — hech qanday purchase
        item topilmaganidan skip qilinmaydi.
        """
        if not product_id:
            return None
        name = frappe.db.get_value(
            "Item",
            {"custom_ibox_id": product_id, "custom_ibox_client": self.client_name},
            "name",
        )
        if name:
            return name

        # Auto-create: placeholder item
        try:
            item_name = f"iBox-Product-{product_id}"
            doc = frappe.new_doc("Item")
            doc.item_code = item_name
            doc.item_name = item_name
            doc.item_group = "All Item Groups"
            doc.stock_uom = "Nos"
            doc.is_stock_item = 1
            doc.custom_ibox_id = str(product_id)
            doc.custom_ibox_client = self.client_name
            doc.append("uoms", {"uom": "Nos", "conversion_factor": 1.0})
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            frappe.log_error(
                title=f"Auto-created Item - {self.client_name}",
                message=f"Item '{item_name}' (ibox_id={product_id}) avtomatik yaratildi.",
            )
            return doc.name
        except Exception:
            frappe.log_error(
                title=f"Item Auto-Create Error - {self.client_name}",
                message=f"product_id={product_id}\n{frappe.get_traceback()}",
            )
            return None

    def _resolve_uom(self, item_code: str) -> str:
        """Item.stock_uom ni olish. Topilmasa 'Nos' (ERPNext default)."""
        if not item_code:
            return "Nos"
        uom = frappe.db.get_value("Item", item_code, "stock_uom")
        return uom or "Nos"

    def _resolve_item_name(self, item_code: str) -> str:
        """Item.item_name ni olish. Topilmasa item_code qaytaradi."""
        if not item_code:
            return ""
        name = frappe.db.get_value("Item", item_code, "item_name")
        return name or item_code

    def _resolve_currency_account(self, currency_code: str) -> tuple:
        """
        currency_code → (ERPNext currency str, credit_to account str | None)
        iBox Client fieldlari: uzs_payable_account, usd_payable_account
        """
        if currency_code == "USD":
            return "USD", self.client_doc.usd_payable_account
        return "UZS", self.client_doc.uzs_payable_account

    def _get_conversion_rate(self, date_str: str, currency: str) -> float:
        """
        Berilgan sana va valyuta uchun conversion rate topish.

        Logika:
          - UZS → har doim 1.0
          - USD → Currency Exchange jadvalidan date <= transaction_date
            bo'lgan eng so'nggi kursni olish.
            Masalan: xarid 2026-01-31 da bo'lgan, lekin kurs faqat
            2026-01-29 da kiritilgan → 2026-01-29 dagi kurs ishlatiladi.
          - Topilmasa → tizimdagi eng oxirgi kurs (fallback).

        Performance: per-sync-run cache — har bir unique date uchun
        DB faqat 1 marta so'raladi.
        """
        if currency == "UZS":
            return 1.0

        # Cache tekshirish
        cache_key = f"{date_str}_{currency}"
        if cache_key in self._rate_cache:
            return self._rate_cache[cache_key]

        rate = 0.0

        try:
            transaction_date = getdate(date_str) if date_str else None
        except Exception:
            transaction_date = None

        if transaction_date:
            # O'sha sana yoki undan oldingi eng yaqin kurs
            result = frappe.db.get_value(
                "Currency Exchange",
                filters={
                    "from_currency": "USD",
                    "to_currency": "UZS",
                    "date": ["<=", transaction_date],
                },
                fieldname="exchange_rate",
                order_by="date desc",
            )
            if result:
                rate = float(result)

        # Fallback — tizimdagi eng oxirgi kurs
        if not rate:
            result = frappe.db.get_value(
                "Currency Exchange",
                filters={
                    "from_currency": "USD",
                    "to_currency": "UZS",
                },
                fieldname="exchange_rate",
                order_by="date desc",
            )
            if result:
                rate = float(result)

        self._rate_cache[cache_key] = rate
        return rate

    # ══════════════════════════════════════════════════════════════════
    # Sub-handlers (Purchases-only / Returns-only)
    # ══════════════════════════════════════════════════════════════════

    @classmethod
    def purchases_only(cls, api_client, client_doc):
        """Faqat xaridlarni yuklash uchun handler (vozvratlar yuklanmaydi)."""
        handler = cls(api_client, client_doc)
        handler._sync_mode = "purchases"
        handler.NAME = "Purchases (Xaridlar)"
        return handler

    @classmethod
    def returns_only(cls, api_client, client_doc):
        """Faqat vozvratlarni yuklash uchun handler (xaridlar yuklanmaydi)."""
        handler = cls(api_client, client_doc)
        handler._sync_mode = "returns"
        handler.NAME = "Returns (Vozvratlar)"
        return handler

    # ══════════════════════════════════════════════════════════════════
    # Utility
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _clean(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default

    @staticmethod
    def _parse_float(value, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
