# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sales Sync Handler — iBox shipment/list -> ERPNext Sales Invoice.

Otgruzka (shipment)  → Sales Invoice (docstatus=0, DRAFT)

Barcha hujjatlar DRAFT holatda saqlanadi.

Custom Field Names:
  Parent (Sales Invoice):
    - custom_ibox_sales_id    — iBox dagi sotuv ID (deduplication key)
    - custom_ibox_client      — qaysi iBox Client dan kelgan
    - custom_ibox_total       — iBox dagi umumiy summa (audit uchun)

  Child (Sales Invoice Item):
    - custom_ibox_detail_id     — iBox dagi detail ID
    - custom_ibox_warehouse_id  — iBox dagi ombor ID

Lookup Fields:
    - Customer:  custom_ibox_id            (Customer doctype)
    - Warehouse: custom_ibox_warehouse_id  (Warehouse doctype)
    - Item:      custom_ibox_id            (Item doctype)

Account Mapping (debit_to):
    - UZS → iBox Client.uzs_receivable_account  (Debitors-UZS hisobi)
    - USD → iBox Client.usd_receivable_account  (Debitors-USD hisobi)

Income Account Mapping (item qatorlari):
    - UZS → iBox Client.uzs_sales_income  (Sotuvlar-UZS hisobi)
    - USD → iBox Client.usd_sales_income  (Sotuvlar-USD hisobi)

Tax Handling:
    - iBox narxlari final (soliq kiritilgan) narxlar.
    - Hech qanday tax template qo'shilmaydi → grand_total == net_total.

Date/Time Parsing:
    - iBox format: "2025-12-31T11:47:34.000000Z"
    - posting_date = "2025-12-31"
    - posting_time = "11:47:34"
    - set_posting_time = 1  →  ERPNext Stock Ledger FIFO aniqligi

Historical Exchange Rate:
    - Currency Exchange jadvalidan date <= posting_date bo'lgan eng so'nggi kurs.
    - Hech qachon joriy sana ishlatilmaydi — tranzaksiya sanasi muhim.

Warehouse per-row mapping:
    - Har bir item qatorida alohida warehouse_id bo'lishi mumkin.
    - Fallback zanjiri: detail.warehouse_id → header.warehouse_id → default_warehouse

Non-blocking Error Handling:
    - Topilmagan Customer/Item/Warehouse ID lar yig'iladi (skip_log).
    - Sync tugaganda yagona summary yoziladi.
    - frappe.log_error chaqirilmaydi (spam oldini olish).

Permanent Draft Mode:
    - BARCHA hujjatlar DRAFT (docstatus=0) holatida saqlanadi.
    - Hech qachon submit() chaqirilmaydi.
    - insert() xato bersa → log + skip, sync to'xtamaydi.
    - frappe.db.commit() har batch tugaganda
"""

import time
from typing import Generator

import frappe
from frappe.utils import flt, getdate

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class SalesSyncHandler(BaseSyncHandler):
    DOCTYPE = "Sales Invoice"
    NAME = "Sales"

    # Mirror Sync: iBox ID field nomi (deduplication va cleanup uchun)
    IBOX_ID_FIELD = "custom_ibox_sales_id"

    def __init__(self, api_client, client_doc, is_cleanup_job=False):
        super().__init__(api_client, client_doc, is_cleanup_job=is_cleanup_job)
        # Per-sync-run cache: {"2026-01-31_USD": 12900.0}
        self._rate_cache: dict[str, float] = {}

        # Non-blocking skip log — ID larni yig'ish (log spam o'rniga)
        self._skip_log: dict[str, list] = {
            "missing_customers": [],
            "missing_items": [],
            "missing_warehouses": [],
            "missing_accounts": [],
            "missing_rates": [],
        }
        # Retry: birinchi urinishda skip qilingan recordlar
        self._retry_queue: list[dict] = []

    def run(self) -> dict:
        """
        Override: BaseSyncHandler.run() + yakuniy skip summary + cleanup info.

        run() tugagandan keyin iBox Client.sync_status ga
        skip qilingan ID lar ro'yxati yoziladi.
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

            frappe.db.commit()

            if retry_synced > 0:
                result["retry_synced"] = retry_synced
                result["synced"] = result.get("synced", 0) + retry_synced

        # ── Yakuniy skip summary ──────────────────────────────────────
        skip_parts = []
        total_skipped = 0

        for key, ids in self._skip_log.items():
            if ids:
                unique_ids = sorted(set(ids))
                total_skipped += len(unique_ids)
                label = key.replace("missing_", "")
                # Ko'p bo'lsa, birinchi 20 tasini ko'rsatish
                display = unique_ids[:20]
                suffix = f"... +{len(unique_ids) - 20}" if len(unique_ids) > 20 else ""
                skip_parts.append(f"{label}={display}{suffix}")

        synced = result.get("synced", 0)
        errors = result.get("errors", 0)

        # Cleanup info
        cleanup_info = ""
        cleanup = result.get("cleanup")
        if cleanup:
            deleted = cleanup.get("deleted", 0)
            aborted = cleanup.get("aborted", False)
            if aborted:
                cleanup_info = " ⚠️ Tozalash bekor qilindi"
            elif deleted > 0:
                cleanup_info = f" 🗑️ {deleted} ta eskirgan o'chirildi"

        if skip_parts:
            summary = (
                f"Sotuvlar: {synced} ta draft yaratildi, "
                f"{total_skipped} ta skipped, "
                f"{errors} ta xato.{cleanup_info} Missing: {', '.join(skip_parts)}"
            )
        else:
            summary = (
                f"Sotuvlar: {synced} ta draft yaratildi, "
                f"{errors} ta xato{cleanup_info} ✓"
            )

        self._set_status(summary)

        # Bitta yig'ma log — faqat skip bo'lsa
        if total_skipped > 0:
            frappe.log_error(
                title=f"Sotuv Sync - Skip Summary - {self.client_name}",
                message=summary,
            )

        return result

    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox API dan shipment recordlarni sahifa-sahifa yield qilish."""
        per_page = self.page_size or 100
        max_pages = self.max_pages or 0  # 0 = cheksiz

        page = 1
        while True:
            if max_pages and page > max_pages:
                break

            response = self.api.shipments.get_page(page=page, per_page=per_page)
            records = response.get("data", [])

            if page == 1:
                total = int(flt(response.get("total", 0)))
                self.ibox_total = min(total, max_pages * per_page) if max_pages else total

            if not records:
                break

            for record in records:
                yield record

            if len(records) < per_page:
                break

            time.sleep(1)
            page += 1

    def upsert(self, record: dict) -> bool:
        """
        Bitta shipment recordni Sales Invoice sifatida yaratish.
        Deduplication key: custom_ibox_sales_id + custom_ibox_client

        Non-blocking: topilmagan ID lar skip_log ga yoziladi,
        hujjat o'tkazib yuboriladi, lekin sync to'xtamaydi.
        """
        ibox_id = record.get("id")

        # ── 1) Deduplication (docstatus-aware) ─────────────────────────
        existing = frappe.db.get_value(
            "Sales Invoice",
            {
                "custom_ibox_sales_id": ibox_id,
                "custom_ibox_client": self.client_name,
            },
            ["name", "docstatus"],
            as_dict=True,
        )
        if existing:
            # Allaqachon mavjud (Draft, Submitted, yoki Cancelled) — skip
            return False

        # ── 2) Company ────────────────────────────────────────────────
        company = self.client_doc.company
        if not company:
            self._skip_log["missing_accounts"].append(f"company_missing")
            return False

        # ── 3) Customer lookup (non-blocking) ─────────────────────────
        outlet_id = record.get("outlet_id")
        outlet_name = self._extract_outlet_name(record)
        customer_name = self._resolve_customer(outlet_id, outlet_name)
        if not customer_name:
            if not record.get("_is_retry"):
                record["_is_retry"] = True
                self._retry_queue.append(record)
            else:
                self._skip_log["missing_customers"].append(outlet_id)
            return False

        # ── 4) Header warehouse (fallback uchun) ──────────────────────
        header_warehouse_id = record.get("warehouse_id")
        details = record.get("shipment_details") or record.get("details") or []

        # Detail qatorlaridan warehouse_id olish (header da yo'q bo'lsa)
        if not header_warehouse_id and details:
            for d in details:
                wh_id = d.get("warehouse_id")
                if wh_id:
                    header_warehouse_id = wh_id
                    break

        header_warehouse_name = self._resolve_warehouse(header_warehouse_id)

        # Fallback: iBox Client.default_warehouse
        if not header_warehouse_name:
            fallback = getattr(self.client_doc, "default_warehouse", None)
            if fallback:
                header_warehouse_name = fallback

        # ── 5) Currency & Account ─────────────────────────────────────
        # QOIDA: iBox currency_code DOIM ustunlik qiladi.
        # iBox shipmentlar FAQAT UZS da keladi. Customer ning
        # party_currency sidan qat'iy nazar, narxlar iBox dagi
        # valyutada yoziladi — aks holda narxlar 12,200x shishadi.
        currency = self._clean(record.get("currency_code"), "UZS").upper()
        if currency not in ("UZS", "USD"):
            currency = "UZS"

        _unused, debit_to = self._resolve_currency_account(currency)

        if not debit_to:
            field = "uzs_receivable_account" if currency == "UZS" else "usd_receivable_account"
            self._skip_log["missing_accounts"].append(f"{field}:{ibox_id}")
            return False

        # ── 5.0.0.1) Account Currency Validation (Currency-Account Lock) ─
        acct_currency = frappe.db.get_value("Account", debit_to, "account_currency")
        if acct_currency and acct_currency != currency:
            self._skip_log["missing_accounts"].append(
                f"currency_mismatch:{ibox_id}:debit_to={debit_to}:{acct_currency}!={currency}"
            )
            return False

        # ── 5.0.1) Income Account (har bir item qatoriga qo'yiladi) ───
        income_account = self._resolve_income_account(currency)
        if not income_account:
            field = "uzs_sales_income" if currency == "UZS" else "usd_sales_income"
            self._skip_log["missing_accounts"].append(f"{field}:{ibox_id}")
            return False

        # ── 5.1) Conversion Rate (HISTORICAL: date <= posting_date) ───
        raw_date = record.get("date", "")
        posting_date = self._parse_date(raw_date)
        conversion_rate = self._get_conversion_rate(posting_date, currency)

        if currency == "USD" and (not conversion_rate or conversion_rate <= 0):
            self._skip_log["missing_rates"].append(f"{posting_date}:{ibox_id}")
            return False

        # ── 5.2) Posting Time — FIFO & Stock Ledger aniqligi ─────────
        posting_time = self._parse_time(raw_date)

        # ── 6) iBox Total (audit uchun) ───────────────────────────────
        ibox_total = self._parse_float(
            record.get("total") or record.get("amount") or record.get("sum")
        )

        # ── 7) Item table — per-row warehouse mapping ─────────────────
        items = []

        for detail in details:
            product_id = detail.get("product_id")
            product_data = detail.get("product") or {}
            product_name = product_data.get("name") or ""
            item_code = self._resolve_item(product_id, product_name)

            if not item_code:
                self._skip_log["missing_items"].append(product_id)
                continue

            # Row-level warehouse — har bir item o'z omborida
            row_wh_id = detail.get("warehouse_id") or header_warehouse_id
            row_wh_name = self._resolve_warehouse(row_wh_id)

            # Fallback: header-level warehouse
            if not row_wh_name:
                row_wh_name = header_warehouse_name

            # Warehouse topilmadi — faqat bu qatorni skip, butun hujjatni emas
            if not row_wh_name:
                self._skip_log["missing_warehouses"].append(row_wh_id)
                continue

            qty = abs(self._parse_float(
                detail.get("quantity") or detail.get("qty")
            ))
            final_qty = qty if qty != 0 else 1

            # iBox da narx "price" fieldida keladi — final narx (soliq kiritilgan)
            rate = self._parse_float(detail.get("price"))

            # UOM & item_name — Item master dan olish
            uom = self._resolve_uom(item_code)
            self._ensure_uom_in_item(item_code, uom)
            item_name = self._resolve_item_name(item_code)[:140]

            items.append({
                "item_code":                item_code,
                "item_name":                item_name,
                "warehouse":                row_wh_name,
                "qty":                      final_qty,
                "rate":                     rate,
                "uom":                      uom,
                "stock_uom":                uom,
                "stock_qty":                final_qty,
                "conversion_factor":        1,
                "income_account":           income_account,
                "custom_ibox_detail_id":    detail.get("id"),
                "custom_ibox_warehouse_id": row_wh_id,
            })

        if not items:
            # Barcha itemlar topilmagan — retry queuega tashlash
            if not record.get("_is_retry"):
                record["_is_retry"] = True
                self._retry_queue.append(record)
            return False

        # ── 8) Sales Invoice yaratish (SURGICAL SEQUENCE) ─────────────
        # KETMA-KETLIK MUHIM:
        #   1. new_doc + identity (customer, company)
        #   2. set_missing_values() → ERPNext defaults (noto'g'ri bo'lishi mumkin)
        #   3. OVERWRITE → bizning iBox Client hisoblarimiz (YAKUNIY SO'Z)
        #   4. calculate_taxes_and_totals()

        # ── STEP 1: Initialize + Identity ─────────────────────────────
        #   Shipment Draft holatida update_stock=0 (stock entry yo'q).
        #   docstatus=0 → hujjat DOIM Draft, submit() hech qachon chaqirilmaydi.
        si = frappe.new_doc("Sales Invoice")
        si.customer             = customer_name
        si.company              = company
        si.posting_date         = posting_date
        si.posting_time         = posting_time
        si.set_posting_time     = 1
        si.update_stock         = 0   # ✅ Shipment Draft uchun stock harakat yo'q
        si.docstatus            = 0   # DOIM Draft (submit() chaqirilmaydi)
        si.custom_ibox_sales_id = ibox_id
        si.custom_ibox_client   = self.client_name
        si.custom_ibox_total    = ibox_total

        for item_row in items:
            si.append("items", item_row)

        # ── STEP 2: ERPNext defaults (AVVAL chaqiriladi) ──
        from unittest.mock import patch

        effective_conversion_rate = 1.0 if currency == "UZS" else conversion_rate

        with patch(
            "erpnext.controllers.accounts_controller.get_exchange_rate",
            return_value=effective_conversion_rate,
        ), patch(
            "erpnext.stock.get_item_details.insert_item_price",
            return_value=None,
        ):
            si.set_missing_values()

        # ── STEP 3: THE OVERWRITE (iBox — YAKUNIY SO'Z) ──────────────
        si.currency             = currency
        si.price_list_currency  = currency
        si.selling_price_list   = "Standard Selling"
        si.debit_to             = debit_to
        si.conversion_rate      = effective_conversion_rate
        si.plc_conversion_rate  = effective_conversion_rate
        si.set_warehouse        = header_warehouse_name
        si.taxes_and_charges    = ""   # Tax yo'q — iBox narxlari final

        for item in si.items:
            item.income_account = income_account

        # ── STEP 4: Recalculate ──────────────────────────────────────
        # set_missing_values() update_stock ni qayta yozgan bo'lishi mumkin — qayta ta'kidlash
        si.update_stock         = 0
        si.calculate_taxes_and_totals()

        # ── STEP 5: Rounding Adjustment (iBox total = ERPNext total) ──
        if flt(ibox_total) > 0:
            erp_grand = flt(getattr(si, "grand_total", 0))
            diff = flt(ibox_total) - erp_grand
            tolerance = 5.0 if currency == "UZS" else 0.001
            if abs(diff) > tolerance:
                si.rounding_adjustment = diff
                si.rounded_total = flt(ibox_total)
                si.base_rounding_adjustment = flt(diff * effective_conversion_rate)
                si.base_rounded_total = flt(ibox_total * effective_conversion_rate)

        # ── STEP 6: Insert as DRAFT + Deadlock Retry ─────────────────
        import time

        for attempt in range(2):  # Max 2 urinish (original + 1 retry)
            try:
                with patch(
                        "erpnext.controllers.accounts_controller.get_exchange_rate",
                    return_value=effective_conversion_rate,
                ), patch(
                    "erpnext.stock.get_item_details.insert_item_price",
                    return_value=None,
                ):
                    si.insert(ignore_permissions=True)
                return True  # Muvaffaqiyatli
            except frappe.QueryDeadlockError:
                frappe.db.rollback()
                if attempt == 0:
                    time.sleep(2)  # 2 sek kutib qayta urinish
                    continue
                frappe.log_error(
                    title=f"Sotuv Sync - Deadlock - {self.client_name}",
                    message=f"ibox_id={ibox_id}: 2 urinishdan keyin ham Deadlock.",
                )
                return False
            except Exception as e:
                frappe.log_error(
                    title=f"Sotuv Sync - Insert Failed - {self.client_name}",
                    message=(
                        f"ibox_sales_id: {ibox_id}\n"
                        f"Customer: {customer_name}\n"
                        f"Currency: {currency}\n"
                        f"Xato: {str(e)[:500]}\n\n"
                        f"{frappe.get_traceback()[-500:]}"
                    ),
                )
                frappe.db.rollback()
                return False

        return False

    # ══════════════════════════════════════════════════════════════════
    # Resolver Methods
    # ══════════════════════════════════════════════════════════════════

    def _resolve_customer(self, outlet_id, outlet_name: str = "") -> str | None:
        """
        iBox outlet_id → ERPNext Customer.name  (field: custom_ibox_id)

        Topilmasa → placeholder Customer avtomatik yaratiladi.
        """
        if not outlet_id:
            return None
        name = frappe.db.get_value(
            "Customer",
            {"custom_ibox_id": outlet_id, "custom_ibox_client": self.client_name},
            "name",
        )
        if name:
            return name

        # Auto-create: placeholder customer
        try:
            customer_name = self._clean(outlet_name)
            if not customer_name:
                customer_name = f"iBox-Customer-{outlet_id}"
            doc = frappe.new_doc("Customer")
            doc.customer_name = customer_name
            doc.customer_group = "All Customer Groups"
            doc.territory = "All Territories"
            doc.custom_ibox_id = str(outlet_id)
            doc.custom_ibox_client = self.client_name
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            frappe.log_error(
                title=f"Auto-created Customer - {self.client_name}",
                message=(
                    f"Customer '{customer_name}' (ibox_id={outlet_id}) avtomatik yaratildi. "
                    f"source_outlet_name='{outlet_name or ''}'"
                ),
            )
            return doc.name
        except Exception:
            frappe.log_error(
                title=f"Customer Auto-Create Error - {self.client_name}",
                message=f"outlet_id={outlet_id}\n{frappe.get_traceback()}",
            )
            return None

    @staticmethod
    def _extract_outlet_name(record: dict) -> str:
        """Shipment recorddan outlet nomini olishga urinish."""
        outlet = record.get("outlet") or {}
        return (
            str(record.get("outlet_name") or "").strip()
            or str(record.get("customer_name") or "").strip()
            or str(outlet.get("name") or "").strip()
            or ""
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

    def _resolve_item(self, product_id, product_name: str = "") -> str | None:
        """
        iBox product_id → ERPNext Item.name  (field: custom_ibox_id)

        Topilmasa → haqiqiy nomi bilan Item avtomatik yaratiladi.
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

        # Auto-create: haqiqiy nomi bilan
        try:
            item_name = (product_name or f"iBox-Product-{product_id}")[:140]
            item_code = (f"{item_name} - iBox-{product_id}")[:140]
            doc = frappe.new_doc("Item")
            doc.item_code = item_code
            doc.item_name = item_name
            doc.item_group = "All Item Groups"
            doc.stock_uom = "Nos"
            doc.is_stock_item = 1
            doc.custom_ibox_id = str(product_id)
            doc.custom_ibox_client = self.client_name
            doc.append("uoms", {"uom": "Nos", "conversion_factor": 1.0})
            doc.insert(ignore_permissions=True)
            frappe.db.commit()
            return doc.name
        except Exception:
            self._skip_log["missing_items"].append(product_id)
            return None

    # _get_party_currency — O'CHIRILDI
    # Sabab: iBox currency_code DOIM ustunlik qiladi.
    # party_currency UZS narxni USD ga inflate qilar edi (42-milliard xato).

    def _resolve_uom(self, item_code: str) -> str:
        """Item.stock_uom ni olish. Topilmasa 'Nos' (ERPNext default)."""
        if not item_code:
            return "Nos"
        uom = frappe.db.get_value("Item", item_code, "stock_uom")
        return uom or "Nos"

    def _ensure_uom_in_item(self, item_code: str, uom: str):
        """
        Item ning 'uoms' child jadvalida ushbu UOM mavjudligini tekshirish.
        Agar yo'q bo'lsa — conversion_factor=1.0 bilan avtomatik qo'shish.

        Bu ERPNext ning UOM ValidationError xatosining oldini oladi:
          'Row #1: Please set the UOM conversion factor for UOM - Nos'
        """
        if not item_code or not uom:
            return

        # Allaqachon borligini tekshirish (DB query — har safar Item yuklashdan tezroq)
        exists = frappe.db.exists(
            "UOM Conversion Detail",
            {"parent": item_code, "parenttype": "Item", "uom": uom},
        )
        if exists:
            return

        # UOM ning o'zi tizimda borligini tekshirish
        if not frappe.db.exists("UOM", uom):
            return

        # Item ga UOM qo'shish
        try:
            item_doc = frappe.get_doc("Item", item_code)
            item_doc.append("uoms", {
                "uom": uom,
                "conversion_factor": 1.0,
            })
            item_doc.flags.ignore_validate = True
            item_doc.save(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            # Xato bo'lsa ham sync to'xtamasligi kerak
            frappe.db.rollback()
            pass

    def _resolve_item_name(self, item_code: str) -> str:
        """Item.item_name ni olish. Topilmasa item_code qaytariladi."""
        if not item_code:
            return item_code or "Unknown"
        name = frappe.db.get_value("Item", item_code, "item_name")
        return name or item_code

    def _resolve_currency_account(self, currency_code: str) -> tuple:
        """
        currency_code → (ERPNext currency str, debit_to account str | None)

        Mapping:
          USD → usd_receivable_account  (Debitors-USD hisobi)
          UZS → uzs_receivable_account  (Debitors-UZS hisobi)
        """
        if currency_code == "USD":
            return "USD", getattr(self.client_doc, "usd_receivable_account", None)
        return "UZS", getattr(self.client_doc, "uzs_receivable_account", None)

    def _resolve_income_account(self, currency_code: str) -> str | None:
        """
        currency_code → income_account str | None

        Har bir Sales Invoice Item qatoriga qo'yiladigan daromad hisobi.

        Fallback zanjiri:
          UZS → uzs_sales_income → Company default_income_account
          USD → usd_sales_income → Company default_income_account
        """
        # 1) iBox Client field — valyutaga mos
        if currency_code == "USD":
            income = getattr(self.client_doc, "usd_sales_income", None)
        else:
            income = getattr(self.client_doc, "uzs_sales_income", None)

        if income:
            return income

        # 2) Company default income account (fallback)
        company = self.client_doc.company
        if company:
            default = frappe.db.get_value("Company", company, "default_income_account")
            if default:
                return default

        return None

    def _get_conversion_rate(self, date_str: str, currency: str) -> float:
        """
        Berilgan sana va valyuta uchun conversion rate topish.

        HISTORICAL RATE — ALWAYS date <= posting_date:
          - UZS → har doim 1.0
          - USD → Currency Exchange jadvalidan date <= transaction_date
            bo'lgan eng so'nggi kursni olish.
          - Topilmasa → tizimdagi eng oxirgi kurs (fallback).

        Hech qachon joriy sanani ishlatmaydi — faqat
        tranzaksiya sanasi yoki undan oldingi kurs.

        Performance: per-sync-run cache — har bir unique date uchun
        DB faqat 1 marta so'raladi.
        """
        if currency == "UZS":
            return 1.0

        cache_key = f"{date_str}_{currency}"
        if cache_key in self._rate_cache:
            return self._rate_cache[cache_key]

        rate = 0.0

        try:
            transaction_date = getdate(date_str) if date_str else None
        except Exception:
            transaction_date = None

        if transaction_date:
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
    # Date/Time Parsing Helpers
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _parse_date(raw: str) -> str:
        """
        ISO 8601 string dan faqat sanani ajratish.

        Misollar:
          "2025-12-31T11:47:34.000000Z" → "2025-12-31"
          "2025-12-31T11:47:34+05:00"   → "2025-12-31"
          "2025-12-31"                  → "2025-12-31"
          ""                            → ""
        """
        if not raw:
            return ""
        return raw[:10]

    @staticmethod
    def _parse_time(raw: str) -> str:
        """
        ISO 8601 string dan faqat vaqtni ajratish.

        Misollar:
          "2025-12-31T11:47:34.000000Z" → "11:47:34"
          "2025-12-31T11:47:34+05:00"   → "11:47:34"
          "2025-12-31"                  → "00:00:00"
          ""                            → "00:00:00"
        """
        if not raw or "T" not in raw:
            return "00:00:00"
        time_part = raw[11:]
        time_part = time_part[:8]
        if len(time_part) < 8 or time_part.count(":") < 2:
            return "00:00:00"
        return time_part

    # ══════════════════════════════════════════════════════════════════
    # General Utility
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
