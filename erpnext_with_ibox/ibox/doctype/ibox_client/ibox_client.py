# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from erpnext_with_ibox.ibox.config import SLUG_CUSTOMERS, SYNC_QUEUE, SYNC_TIMEOUT


class iBoxClient(Document):
    def validate(self):
        if self.api_base_url and self.api_base_url.endswith("/"):
            self.api_base_url = self.api_base_url.rstrip("/")

    @frappe.whitelist()
    def test_connection(self):
        """iBox API ulanishni tekshirish (1 ta mijoz so'rov yuborib)."""
        from erpnext_with_ibox.ibox.api import IBoxAPIClient

        try:
            client = IBoxAPIClient(self.name)
            response = client.directory.get_page(slug=SLUG_CUSTOMERS, page=1, per_page=1)

            if "data" in response:
                total = response.get("total", len(response.get("data", [])))
                return {
                    "success": True,
                    "message": f"Ulanish muvaffaqiyatli! Bazada {total} ta mijoz topildi.",
                }
            return {"success": False, "message": f"Kutilmagan API javob: {response}"}
        except Exception as e:
            return {"success": False, "message": str(e)[:200]}

    @frappe.whitelist()
    def sync_now(self):
        """Qo'lda sync ishga tushirish (background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,
            job_id=f"ibox_sync_{self.name}",
            client_name=self.name,
        )
        return {"message": "Sinxronizatsiya orqa fonda boshlandi. Sync Status maydonini kuzating."}

