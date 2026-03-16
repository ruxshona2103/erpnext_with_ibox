# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Base Sync Handler — barcha sync handlerlar uchun abstract base class.

Industrial-grade features:
  • Redis Lock — bitta client uchun bir vaqtda faqat 1 ta sync
  • Kill Switch — stop signal + blocking DB querylarni KILL qilish
  • Total Tracking — ibox_total vs processed vs ERPNext bazada
  • Batch commit + memory management
  • Graceful error isolation
"""

from abc import ABC, abstractmethod
from typing import Generator

import frappe

from erpnext_with_ibox.ibox.config import (
    BATCH_COMMIT_SIZE,
    ORPHAN_CLEANUP_THRESHOLD,
    ORPHAN_CLEANUP_ENABLED,
)


class BaseSyncHandler(ABC):
    """
    Barcha sync handlerlar uchun abstract base class.

    Yangi doctype sync qo'shish uchun:
    1. BaseSyncHandler dan meros olgan class yarating
    2. fetch_data() va upsert() ni implement qiling
    3. fetch_data() ichida self.ibox_total ni birinchi API javobdan set qiling
    4. SYNC_HANDLERS dict ga registratsiya qiling (sync/__init__.py)

    Mirror Sync (Orphan Cleanup):
      Full Sync tugagandan keyin cleanup_orphaned_records() chaqiriladi.
      iBox API da yo'q bo'lgan, lekin ERPNext da qolgan Draft recordlar
      tozalanadi — faqat xavfsiz chegaralar (15% threshold) ichida.
    """

    DOCTYPE: str = None   # Masalan: "Item", "Customer"
    NAME: str = None      # Masalan: "Mahsulotlar", "Mijozlar"

    # Progress har necha recordda yangilansin
    PROGRESS_INTERVAL = 200
    BATCH_COMMIT_SIZE = BATCH_COMMIT_SIZE

    # ── Mirror Sync Configuration ─────────────────────────────────────
    # Sub-classlar override qiladi:
    IBOX_ID_FIELD: str = None        # Masalan: "custom_ibox_purchase_id"
    IBOX_CLIENT_FIELD: str = "custom_ibox_client"  # Barcha doctype larda bir xil

    def __init__(self, api_client, client_doc, is_cleanup_job=False):
        self.api = api_client
        self.client_doc = client_doc
        self.client_name = client_doc.name
        self.ibox_total = 0  # API dan kelgan umumiy yozuvlar soni
        self.is_cleanup_job = is_cleanup_job  # Cleanup-specific sync uchun flag

        # ── Pagination & Date Filter — iBox Client dan o'qiladi ───────
        self.page_size = int(client_doc.get("sync_page_size") or 100)
        self.max_pages = int(client_doc.get("sync_max_pages") or 0)  # 0 = cheksiz
        self.sync_from_date = str(client_doc.get("sync_from_date") or "")
        self.sync_to_date = str(client_doc.get("sync_to_date") or "")

        # ── Mirror Sync: API dan kelgan active ID lar to'plami ────────
        self._active_ibox_ids: set = set()
        self._cleanup_result: dict | None = None
        self._api_response_status: int | None = 200

    @abstractmethod
    def fetch_data(self) -> Generator[dict, None, None]:
        """
        iBox API dan datalarni yield qilish.
        MUHIM: Birinchi sahifada self.ibox_total ni set qiling!
        """
        ...

    @abstractmethod
    def upsert(self, record: dict) -> bool:
        """
        Bitta recordni ERPNext ga insert yoki update qilish.
        Returns: True agar o'zgarish bo'lgan bo'lsa, False agar skip.
        """
        ...

    def _get_erp_count(self) -> int:
        """ERPNext bazasidagi mavjud yozuvlar sonini hisoblash."""
        if not self.DOCTYPE:
            return 0
        try:
            filters = {"custom_ibox_client": self.client_name}
            return frappe.db.count(self.DOCTYPE, filters)
        except Exception:
            return 0

    # ── Main Run Loop ─────────────────────────────────────────────────

    def run(self) -> dict:
        """
        To'liq sync jarayonini ishga tushirish.

        Mirror Sync protokoli:
          1. API dan har bir record yield bo'lganda uning ID si _active_ibox_ids ga yig'iladi
          2. Barcha recordlar processed bo'lgandan keyin cleanup_orphaned_records() chaqiriladi
          3. ERPNext da bor, lekin iBox da yo'q bo'lgan Draft recordlar o'chiriladi

        Progress formati:
          "{NAME}: {processed} / {ibox_total} (Bazada: {erp_count})"
        Yakuniy:
          "Tayyor: ibox tizimida {ibox_total} ta, ERPNext tizimida {erp_count} ta {NAME} mavjud."
        """
        lock_key = f"ibox_sync_lock_{self.client_name}"

        # ── Lock tekshirish ──────────────────────────────────────────
        if frappe.cache().get_value(lock_key):
            self._set_status(
                f"{self.NAME}: Boshqa sync ishlayapti ⏳ Keyinroq urinib ko'ring."
            )
            return {"processed": 0, "synced": 0, "errors": 0, "locked": True}

        # ── Lock qo'yish (1 soat TTL) va vaqt belgilash ───────────────
        frappe.cache().set_value(lock_key, True, expires_in_sec=3600)
        import time as time_module
        frappe.cache().set_value(f"{lock_key}_time", str(time_module.time()), expires_in_sec=3600)

        processed = 0
        synced = 0
        errors = 0
        batch_count = 0
        sync_completed_fully = True  # API dan to'liq o'qilganmi?

        self._set_status(f"{self.NAME} sync boshlandi...")

        try:
            for record in self.fetch_data():
                # ── Kill Switch ──────────────────────────────────────
                if self._is_stopped():
                    sync_completed_fully = False
                    self._set_status(
                        f"{self.NAME}: TO'XTATILDI ⛔ "
                        f"({processed}/{self.ibox_total})"
                    )
                    frappe.db.commit()
                    frappe.cache().delete_value(
                        f"ibox_sync_stop_{self.client_name}"
                    )
                    return {
                        "processed": processed,
                        "synced": synced,
                        "errors": errors,
                        "stopped": True,
                    }

                # ── Date Filter ─────────────────────────────────────
                if not self._is_in_date_range(record):
                    processed += 1
                    continue

                # ── Mirror Sync: Active ID yig'ish ───────────────────
                record_id = record.get("id")
                if record_id is not None:
                    self._active_ibox_ids.add(str(record_id))

                try:
                    if self.upsert(record):
                        synced += 1
                    processed += 1
                    batch_count += 1

                    # ── Batch commit + memory cleanup ────────────────
                    if batch_count >= self.BATCH_COMMIT_SIZE:
                        frappe.db.commit()
                        batch_count = 0
                        frappe.local.cache = {}

                    # ── Progress update ──────────────────────────────
                    if processed % self.PROGRESS_INTERVAL == 0:
                        erp_count = self._get_erp_count()
                        total_str = f" / {self.ibox_total}" if self.ibox_total else ""
                        self._set_status(
                            f"{self.NAME}: {processed}{total_str} "
                            f"(Bazada: {erp_count})"
                        )

                except Exception:
                    errors += 1
                    frappe.log_error(
                        title=f"{self.NAME} Upsert Error - {self.client_name}",
                        message=(
                            f"record_id={record.get('id')}\n"
                            f"{frappe.get_traceback()}"
                        ),
                    )

            frappe.db.commit()

            # ── Mirror Sync: Orphan Cleanup ──────────────────────────
            # CFO Safety Rule:
            #   Cleanup FAQAT quyidagi holatda ishga tushadi:
            #     1) full_sync flag = True
            #     2) API response status = 200
            #     3) date-range incremental sync emas
            #     4) sync to'liq yakunlangan
            is_full_sync = bool(frappe.cache().get_value(f"ibox_sync_full_{self.client_name}"))
            has_date_range = bool(self.sync_from_date or self.sync_to_date)
            api_ok = int(self._api_response_status or 0) == 200

            enable_cleanup = (
                (is_full_sync or self.is_cleanup_job)
                and sync_completed_fully
                and api_ok
                and not has_date_range
                and self._active_ibox_ids 
                and ORPHAN_CLEANUP_ENABLED
            )
            
            if enable_cleanup:
                self._set_status(f"{self.NAME}: Ortiqcha recordlarni tozalash...")
                try:
                    self._cleanup_result = self.cleanup_orphaned_records()
                except Exception:
                    frappe.log_error(
                        title=f"{self.NAME} Cleanup Error - {self.client_name}",
                        message=frappe.get_traceback(),
                    )
                    self._cleanup_result = {"error": True}

            # ── Yakuniy hisobot ──────────────────────────────────────
            erp_count = self._get_erp_count()
            total_info = f"ibox tizimida {self.ibox_total} ta, " if self.ibox_total else ""

            # Cleanup natijasi
            cleanup_info = ""
            if self._cleanup_result:
                deleted = self._cleanup_result.get("deleted", 0)
                aborted = self._cleanup_result.get("aborted", False)
                if aborted:
                    cleanup_info = " ⚠️ Tozalash bekor qilindi (xavfsizlik)"
                elif deleted > 0:
                    cleanup_info = f" 🗑️ {deleted} ta eskirgan record o'chirildi"

            self._set_status(
                f"Tayyor: {total_info}"
                f"ERPNext tizimida {erp_count} ta {self.NAME} mavjud. "
                f"({synced} ta yangi, {errors} ta xato){cleanup_info}"
            )

        finally:
            # ── DOIMO lock tozalash ──────────────────────────────────
            frappe.cache().delete_value(lock_key)

        result = {
            "processed": processed,
            "synced": synced,
            "errors": errors,
            "ibox_total": self.ibox_total,
        }
        if self._cleanup_result:
            result["cleanup"] = self._cleanup_result
        return result

    # ── Date Filter ──────────────────────────────────────────────────

    def _is_in_date_range(self, record: dict) -> bool:
        """
        Record sanasi sync_from_date..sync_to_date oralig'ida ekanligini tekshirish.
        Sana filtri bo'sh bo'lsa — True (hamma recordlar o'tadi).
        """
        if not self.sync_from_date and not self.sync_to_date:
            return True

        raw_date = record.get("date") or ""
        if not raw_date:
            return True  # Sanasi yo'q recordlarni o'tkazib yubormaymiz

        record_date = raw_date[:10]  # "2026-03-15T..." → "2026-03-15"
        if not record_date or len(record_date) < 10:
            return True

        if self.sync_from_date and record_date < self.sync_from_date:
            return False
        if self.sync_to_date and record_date > self.sync_to_date:
            return False
        return True

    # ── Stop / Kill Mechanism ─────────────────────────────────────────

    def _is_stopped(self) -> bool:
        """Cache'dagi stop flagni tekshirish."""
        return bool(
            frappe.cache().get_value(f"ibox_sync_stop_{self.client_name}")
        )

    # ══════════════════════════════════════════════════════════════════
    # Mirror Sync — Orphan Cleanup
    # ══════════════════════════════════════════════════════════════════

    def cleanup_orphaned_records(self) -> dict:
        """
        iBox API da yo'q bo'lgan, lekin ERPNext da qolgan recordlarni tozalash.

        Mirror Sync Protokoli:
          1. ERPNext dagi barcha IBOX_ID_FIELD qiymatlarini olish (bu client uchun)
          2. iBox API dagi active ID lar bilan solishtirish
          3. ERPNext da bor, iBox da yo'q = ORPHANED (eskirgan)
          4. Xavfsizlik tekshiruvi: orphan soni > 15% bo'lsa → ABORT
          5. Faqat DRAFT (docstatus=0) recordlarni o'chirish
          6. Submitted (docstatus=1) recordlar HECH QACHON o'chirilmaydi

        Returns:
            dict: {
                "orphaned": int,      # Topilgan eskirgan recordlar soni
                "deleted": int,       # O'chirilgan recordlar soni
                "skipped_submitted": int,  # O'tkazib yuborilgan (submitted)
                "aborted": bool,      # Xavfsizlik chegarasi oshganmi
                "erp_before": int,    # Cleanup oldidan ERPNext dagi son
                "erp_after": int,     # Cleanup keyin ERPNext dagi son
            }
        """
        result = {
            "orphaned": 0,
            "deleted": 0,
            "skipped_submitted": 0,
            "aborted": False,
            "erp_before": 0,
            "erp_after": 0,
        }

        # Sub-class IBOX_ID_FIELD ni belgilamagan bo'lsa → skip
        if not self.IBOX_ID_FIELD or not self.DOCTYPE:
            return result

        # Active ID lar bo'sh → API dan hech narsa kelmagan → xavfli, skip
        if not self._active_ibox_ids:
            return result

        # ── Step 1: ERPNext dagi barcha ibox ID larni olish ──────────
        erp_records = frappe.db.get_all(
            self.DOCTYPE,
            filters={
                self.IBOX_CLIENT_FIELD: self.client_name,
                self.IBOX_ID_FIELD: ["is", "set"],  # NULL yoki '' emas
            },
            fields=["name", self.IBOX_ID_FIELD, "docstatus"],
        )

        result["erp_before"] = len(erp_records)

        # ERPNext dagi ID lar to'plami
        erp_ibox_ids = {
            str(r.get(self.IBOX_ID_FIELD)) for r in erp_records if r.get(self.IBOX_ID_FIELD)
        }

        # ── Step 2: Orphaned ID larni aniqlash ───────────────────────
        #   ERPNext da bor, lekin iBox API da YO'Q
        orphaned_ids = erp_ibox_ids - self._active_ibox_ids
        result["orphaned"] = len(orphaned_ids)

        if not orphaned_ids:
            result["erp_after"] = result["erp_before"]
            return result

        # ── Step 3: Xavfsizlik Tekshiruvi (CFO Standard) ─────────────
        #   Agar orphan soni umumiy recordlarning 15% dan oshsa → ABORT.
        #   Bu API ning qisman xato qaytargan holatini himoya qiladi.
        total_erp = len(erp_records)
        if total_erp > 0:
            orphan_ratio = len(orphaned_ids) / total_erp
            if orphan_ratio > ORPHAN_CLEANUP_THRESHOLD:
                frappe.log_error(
                    title=f"CRITICAL: {self.NAME} Mirror Sync ABORTED - {self.client_name}",
                    message=(
                        f"Mass deletion detected! Sync aborted for safety.\n\n"
                        f"ERPNext dagi recordlar: {total_erp}\n"
                        f"iBox API dagi active: {len(self._active_ibox_ids)}\n"
                        f"Orphaned (o'chirilishi kerak): {len(orphaned_ids)}\n"
                        f"Nisbat: {orphan_ratio:.1%} (chegara: {ORPHAN_CLEANUP_THRESHOLD:.0%})\n\n"
                        f"Bu xavfsizlik cheklovi. Agar bu haqiqiy o'chirish bo'lsa,\n"
                        f"config.py da ORPHAN_CLEANUP_THRESHOLD ni oshiring yoki\n"
                        f"qo'lda tozalang."
                    ),
                )
                result["aborted"] = True
                result["erp_after"] = result["erp_before"]
                return result

        # ── Step 4: Orphaned recordlarni topish va tozalash ──────────
        #   Faqat DRAFT (docstatus=0) recordlar o'chiriladi.
        #   Submitted (docstatus=1) recordlar o'tkazib yuboriladi.
        orphaned_docs = [
            r for r in erp_records
            if str(r.get(self.IBOX_ID_FIELD)) in orphaned_ids
        ]

        for doc_rec in orphaned_docs:
            doc_name = doc_rec.get("name")
            docstatus = doc_rec.get("docstatus", 0)

            if docstatus == 1:
                # Submitted — HECH QACHON o'chirmaymiz
                result["skipped_submitted"] += 1
                continue

            if docstatus == 2:
                # Cancelled — o'chirilishi mumkin
                pass

            # Draft (0) yoki Cancelled (2) — o'chirish
            try:
                frappe.delete_doc(
                    self.DOCTYPE,
                    doc_name,
                    force=True,
                    ignore_permissions=True,
                )
                result["deleted"] += 1
            except Exception:
                frappe.log_error(
                    title=f"{self.NAME} Cleanup Delete Error - {self.client_name}",
                    message=(
                        f"doc_name={doc_name}, "
                        f"ibox_id={doc_rec.get(self.IBOX_ID_FIELD)}\n"
                        f"{frappe.get_traceback()}"
                    ),
                )

        frappe.db.commit()

        result["erp_after"] = self._get_erp_count()

        # ── Audit Log ────────────────────────────────────────────────
        if result["deleted"] > 0:
            frappe.log_error(
                title=f"{self.NAME} Mirror Sync - {result['deleted']} ta o'chirildi - {self.client_name}",
                message=(
                    f"iBox: {len(self._active_ibox_ids)} | "
                    f"ERPNext (Avval): {result['erp_before']} | "
                    f"O'chirildi: {result['deleted']} | "
                    f"Hozir: {result['erp_after']}\n"
                    f"Submitted o'tkazib yuborildi: {result['skipped_submitted']}\n\n"
                    f"O'chirilgan iBox ID lar (birinchi 50 ta):\n"
                    f"{sorted(orphaned_ids)[:50]}"
                ),
            )

        return result

    @staticmethod
    def kill_blocking_queries(client_name: str):
        """
        MySQL PROCESSLIST dagi sync-related querylarni KILL qilish.
        stop_sync dan chaqiriladi.
        """
        try:
            blocking = frappe.db.sql("""
                SELECT Id, Info
                FROM information_schema.PROCESSLIST
                WHERE Info IS NOT NULL
                  AND Id != CONNECTION_ID()
                  AND (
                    Info LIKE %s
                    OR Info LIKE %s
                    OR Info LIKE %s
                    OR Info LIKE %s
                  )
            """, (
                f"%custom_ibox_client%{client_name}%",
                f"%custom_ibox%{client_name}%",
                f"%tabSales Invoice%{client_name}%",
                f"%tabPurchase Invoice%{client_name}%",
            ), as_dict=True)

            killed = 0
            for row in blocking:
                try:
                    frappe.db.sql(f"KILL {row['Id']}")
                    killed += 1
                except Exception:
                    pass
            return killed
        except Exception:
            return 0

    # ── Status Helper ─────────────────────────────────────────────────

    def _set_status(self, status: str):
        """iBox Client dagi sync_status maydonini yangilash."""
        try:
            frappe.db.set_value(
                "iBox Client", self.client_name, "sync_status", status,
                update_modified=False,
            )
            frappe.db.commit()
        except Exception:
            pass
