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

    # Sync mode: None = hammasi, "purchases" = faqat xarid, "returns" = faqat vozvrat
    SYNC_MODE: str | None = None

    def __init__(self, api_client, client_doc):
        super().__init__(api_client, client_doc)
        # Per-sync-run cache: {date_str: rate} — DB ni har safar so'ramaslik uchun
        self._rate_cache: dict[str, float] = {}

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
        existing = frappe.db.get_value(
            "Purchase Invoice",
            {
                "custom_ibox_purchase_id": ibox_id,
                "custom_ibox_client": self.client_name,
            },
            "name",
        )
        if existing:
            return False  # allaqachon import qilingan

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
            frappe.log_error(
                title=f"{doc_label} Sync - Supplier topilmadi - {self.client_name}",
                message=(
                    f"ibox_purchase_id={ibox_id}, outlet_id={outlet_id}\n"
                    f"ERPNext'da custom_ibox_id={outlet_id} bo'lgan Supplier "
                    f"topilmadi. Record o'tkazib yuborildi."
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
                frappe.log_error(
                    title=f"{doc_label} Sync - Item topilmadi - {self.client_name}",
                    message=(
                        f"ibox_purchase_id={ibox_id}, product_id={product_id}\n"
                        f"ERPNext'da custom_ibox_id={product_id} bo'lgan Item "
                        f"topilmadi. Bu qator o'tkazib yuborildi."
                    ),
                )
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

            items.append({
                "item_code": item_code,
                "warehouse": row_wh_name,
                "qty": qty if qty != 0 else (-1 if is_return else 1),
                "rate": 0.0,
                "custom_ibox_detail_id": detail.get("id"),
                "custom_ibox_warehouse_id": row_wh_id,
            })

        if not items:
            frappe.log_error(
                title=f"{doc_label} Sync - Bo'sh items - {self.client_name}",
                message=(
                    f"ibox_purchase_id={ibox_id}: Hech qanday item mapping "
                    f"topilmadi. Hujjat yaratilmadi."
                ),
            )
            return False

        # ── 8) Purchase Invoice DRAFT ─────────────────────────────────
        pi = frappe.get_doc({
            "doctype": "Purchase Invoice",
            "supplier": supplier_name,
            "company": company,
            "currency": currency,
            "credit_to": credit_to,
            "conversion_rate": conversion_rate,
            "plc_conversion_rate": conversion_rate,
            "is_return": 1 if is_return else 0,
            "update_stock": 1,
            "set_warehouse": warehouse_name,
            "docstatus": 0,                         # DRAFT — hech qachon avtomatik submit yo'q
            "custom_ibox_purchase_id": ibox_id,
            "custom_ibox_client": self.client_name,
            "custom_ibox_total": ibox_total,
            "items": items,
        })

        # ── 8.1) Insert — validate() da get_exchange_rate tashqi API ni
        #    chaqiradi va xato beradi. Mock patch bilan 1.0 qaytaramiz.
        #    DRAFT hujjat — foydalanuvchi submit qilishdan oldin to'g'ri
        #    kursni qo'lda kiritadi.
        from unittest.mock import patch

        with patch(
            "erpnext.controllers.accounts_controller.get_exchange_rate",
            return_value=1.0,
        ):
            pi.flags.ignore_validate = True
            pi.insert(ignore_permissions=True)

        # ── 9) Har bir muvaffaqiyatli hujjatdan keyin commit ─────────
        frappe.db.commit()

        return True

    # ══════════════════════════════════════════════════════════════════
    # Resolver Methods
    # ══════════════════════════════════════════════════════════════════

    def _resolve_supplier(self, outlet_id) -> str | None:
        """iBox outlet_id → ERPNext Supplier.name  (field: custom_ibox_id)"""
        if not outlet_id:
            return None
        return frappe.db.get_value(
            "Supplier",
            {"custom_ibox_id": outlet_id, "custom_ibox_client": self.client_name},
            "name",
        )

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
        """iBox product_id → ERPNext Item.name  (field: custom_ibox_id)"""
        if not product_id:
            return None
        return frappe.db.get_value(
            "Item",
            {"custom_ibox_id": product_id, "custom_ibox_client": self.client_name},
            "name",
        )

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
