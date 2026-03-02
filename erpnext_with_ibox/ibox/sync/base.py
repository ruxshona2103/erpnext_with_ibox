# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Base Sync Handler — barcha sync handlerlar uchun abstract base class.
Batch commit, progress tracking, error isolation — hammasi shu yerda.
"""

from abc import ABC, abstractmethod
from typing import Generator

import frappe

from erpnext_with_ibox.ibox.config import BATCH_COMMIT_SIZE, PROGRESS_LOG_SIZE


class BaseSyncHandler(ABC):
    """
    Barcha sync handlerlar uchun abstract base class.

    Yangi doctype sync qo'shish uchun:
    1. BaseSyncHandler dan meros olgan class yarating
    2. fetch_data() va upsert() ni implement qiling
    3. SYNC_HANDLERS dict ga registratsiya qiling (sync/__init__.py)
    """

    DOCTYPE: str = None   # Masalan: "Item", "Customer"
    NAME: str = None      # Masalan: "Items", "Customers"

    def __init__(self, api_client, client_doc):
        self.api = api_client
        self.client_doc = client_doc
        self.client_name = client_doc.name

    @abstractmethod
    def fetch_data(self) -> Generator[dict, None, None]:
        """iBox API dan datalarni yield qilish."""
        ...

    @abstractmethod
    def upsert(self, record: dict) -> bool:
        """
        Bitta recordni ERPNext ga insert yoki update qilish.

        Returns:
            True agar o'zgarish bo'lgan bo'lsa, False agar skip qilingan bo'lsa.
        """
        ...

    def run(self) -> dict:
        """
        To'liq sync jarayonini ishga tushirish.

        Returns:
            dict: {processed, synced, errors}
        """
        processed = 0
        synced = 0
        errors = 0
        batch_count = 0

        self._set_status(f"{self.NAME} sync boshlandi...")

        for record in self.fetch_data():
            # Stop flag tekshirish
            if self._is_stopped():
                self._set_status(
                    f"{self.NAME}: TO'XTATILDI ⛔ "
                    f"({processed} ta qayta ishlandi, {synced} ta sinxronlandi)"
                )
                frappe.db.commit()
                return {"processed": processed, "synced": synced, "errors": errors, "stopped": True}

            try:
                if self.upsert(record):
                    synced += 1
                processed += 1
                batch_count += 1

                if batch_count >= BATCH_COMMIT_SIZE:
                    frappe.db.commit()
                    batch_count = 0

                if processed % PROGRESS_LOG_SIZE == 0:
                    self._set_status(
                        f"{self.NAME}: {processed} ta qayta ishlandi, "
                        f"{synced} ta sinxronlandi"
                    )
                    frappe.db.commit()

            except Exception:
                errors += 1
                frappe.log_error(
                    title=f"{self.NAME} Upsert Error - {self.client_name}",
                    message=f"record_id={record.get('id')}\n{frappe.get_traceback()}",
                )

        frappe.db.commit()

        return {"processed": processed, "synced": synced, "errors": errors}

    def _is_stopped(self) -> bool:
        """Cache'dagi stop flagni tekshirish."""
        return bool(frappe.cache().get_value(f"ibox_sync_stop_{self.client_name}"))

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
