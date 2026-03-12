# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from erpnext_with_ibox.ibox.config import SLUG_CUSTOMERS, SYNC_QUEUE, SYNC_TIMEOUT


class iBoxClient(Document):
    def validate(self):
        if self.api_base_url and self.api_base_url.endswith("/"):
            self.api_base_url = self.api_base_url.rstrip("/")

        if not self.internal_api_login or not self.internal_api_password:
            frappe.msgprint(
                "Internal API Login yoki Password bo'sh. "
                "Taminotchilar sinxronizatsiyasi ishlamaydi.",
                title="Internal API Credentials",
                indicator="orange",
            )

    # ── Test ──────────────────────────────────────────────────────────

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

    # ── Internal: yangi sync oldidan tozalash ────────────────────────

    def _prepare_for_sync(self):
        """Har qanday yangi sync boshlashdan oldin — eski stop flag va lock tozalash."""
        frappe.cache().delete_value(f"ibox_sync_stop_{self.name}")
        frappe.cache().delete_value(f"ibox_sync_lock_{self.name}")

    # ── Master Sync ──────────────────────────────────────────────────

    @frappe.whitelist()
    def sync_now(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,
            client_name=self.name,
        )
        return {
            "message": (
                "To'liq sinxronizatsiya boshlandi!\n\n"
                "Tartib: Omborlar → Taminotchilar → Mijozlar → Mahsulotlar\n\n"
                "Sync Status maydonini kuzating."
            )
        }

    # ── Partial Syncs ─────────────────────────────────────────────────

    @frappe.whitelist()
    def sync_warehouses(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["warehouses"],
        )
        return {"message": "Omborxonalar sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_suppliers(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["suppliers"],
        )
        return {"message": "Taminotchilar sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_customers(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["customers"],
        )
        return {"message": "Mijozlar sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_purchases(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["purchases_only"],
        )
        return {"message": "Xaridlar sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_payments(self):
        """Faqat TO'LOVLARNI sync qilish (background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["payments"],
        )
        return {"message": "To'lovlar sinxronizatsiyasi orqa fonda boshlandi. Sync Status maydonini kuzating."}

    @frappe.whitelist()
    def sync_payments_made(self):
        """Faqat CHIQUVCHI TO'LOVLARNI (Payment Made) sync qilish (maks. 200ta, background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["payments_made"],
        )
        return {"message": "Chiquvchi to'lovlar (maks 200 ta) sinxronizatsiyasi orqa fonda boshlandi."}

    @frappe.whitelist()
    def sync_payment_transfers(self):
        """Faqat ICHKI PUL KO'CHIRISHLARNI (Payment Transfer) sync qilish (maks. 200ta, background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["payment_transfers"],
        )
        return {"message": "Ichki pul ko'chirishlar (maks 200 ta) sinxronizatsiyasi orqa fonda boshlandi."}

    @frappe.whitelist()
    def sync_returns(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["returns_only"],
        )
        return {"message": "Vozvratlar sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_exchange_rates(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["exchange_rates"],
        )
        return {"message": "Valyuta kurslari sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_cashboxes(self):
        """Kassalarni iBox API dan tortib, child table ga yozish."""
        from erpnext_with_ibox.ibox.api.internal_client import IBoxInternalClient
        
        try:
            client = IBoxInternalClient(self.name)
            cashboxes_data = client.cashbox.get_all(active=True)
            
            # Mavjud cashbox_id larni topish (mapping doc orqali row ni izlash)
            existing_cashboxes = {row.cashbox_id: row for row in self.get("cashboxes")}
            
            added = 0
            updated = 0
            
            for cb in cashboxes_data:
                cb_id = str(cb.get("id"))
                cb_name = cb.get("name")
                
                if cb_id in existing_cashboxes:
                    row = existing_cashboxes[cb_id]
                    if row.cashbox_name != cb_name:
                        row.cashbox_name = cb_name
                        updated += 1
                else:
                    self.append("cashboxes", {
                        "cashbox_id": cb_id,
                        "cashbox_name": cb_name
                    })
                    added += 1
            
            if added > 0 or updated > 0:
                self.save(ignore_permissions=True)
                frappe.db.commit()
                
            return {
                "message": f"Kassalar muvaffaqiyatli yuklandi!\\nYangi: {added} ta\\nYangilandi: {updated} ta\\nJami: {len(cashboxes_data)} ta"
            }
            
        except Exception as e:
            frappe.log_error(title=f"Cashbox Sync Error - {self.name}", message=str(e))
            frappe.throw(f"Kassalarni tortishda xatolik yuz berdi: {str(e)[:200]}")

    @frappe.whitelist()
    def sync_sales(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["sales"],
        )
        return {"message": "Sotuvlar sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_items(self):
        """Faqat MAHSULOTLARNI sync qilish — real-time total tracking bilan."""
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["items"],
        )
        return {"message": "Mahsulotlar sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    # ── Stop Sync (Industrial-Grade) ──────────────────────────────────

    @frappe.whitelist()
    def stop_sync(self):
        """
        Barcha ishlab turgan sync joblarni TO'LIQ to'xtatish.

        1. Cache flag → base.py har recordda tekshiradi va to'xtaydi
        2. DB dagi bloklayotgan querylarni KILL → migrate bloklanmaydi
        3. RQ queue dagi kutayotgan joblarni cancel
        4. Lock + flag tozalash → qayta sync darhol mumkin
        """
        # 1) Stop signal
        frappe.cache().set_value(
            f"ibox_sync_stop_{self.name}", True, expires_in_sec=30
        )

        # 2) Bloklayotgan DB querylarni KILL qilish
        killed = 0
        try:
            from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler
            killed = BaseSyncHandler.kill_blocking_queries(self.name)
        except Exception:
            pass

        # 3) RQ queue dagi kutayotgan joblarni cancel
        jobs_cancelled = 0
        try:
            from frappe.utils.background_jobs import get_redis_conn
            from rq import Queue

            conn = get_redis_conn()
            for queue_name in ["long", "default", "short"]:
                try:
                    q = Queue(queue_name, connection=conn)
                    for job in q.jobs:
                        if (
                            hasattr(job, "kwargs")
                            and job.kwargs
                            and job.kwargs.get("client_name") == self.name
                        ):
                            job.cancel()
                            jobs_cancelled += 1
                except Exception:
                    pass
        except Exception:
            pass

        # 4) Barcha flaglarni tozalash — qayta sync bloklanamasligi uchun
        frappe.cache().delete_value(f"ibox_sync_stop_{self.name}")
        frappe.cache().delete_value(f"ibox_sync_lock_{self.name}")

        # 5) Status yangilash
        frappe.db.set_value(
            "iBox Client", self.name, "sync_status",
            f"TO'XTATILDI ⛔ ({killed} query kill, {jobs_cancelled} job cancel). "
            f"Qayta sync qilish mumkin.",
            update_modified=False,
        )
        frappe.db.commit()

        return {
            "message": (
                f"Sinxronizatsiya to'xtatildi!\n"
                f"{killed} ta DB query kill qilindi.\n"
                f"{jobs_cancelled} ta kutayotgan job bekor qilindi.\n"
                f"Qayta sync qilish mumkin."
            )
        }

    @frappe.whitelist()
    def clear_stop_flag(self):
        """Stop flag va lock tozalash (backup)."""
        frappe.cache().delete_value(f"ibox_sync_stop_{self.name}")
        frappe.cache().delete_value(f"ibox_sync_lock_{self.name}")
