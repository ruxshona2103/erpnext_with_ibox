# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from erpnext_with_ibox.ibox.config import SLUG_CUSTOMERS, SYNC_QUEUE, SYNC_TIMEOUT


class iBoxClient(Document):
    def validate(self):
        if self.api_base_url and self.api_base_url.endswith("/"):
            self.api_base_url = self.api_base_url.rstrip("/")

        # Internal API credentiallarni tekshirish (ogohlantirish)
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

    # ── Master Sync (to'liq sinxronizatsiya) ─────────────────────────

    @frappe.whitelist()
    def sync_now(self):
        """
        To'liq master sinxronizatsiya — Omborlar → Taminotchilar → Mijozlar → Mahsulotlar.

        Xaridlar alohida trigger qilinadi (asosiy ma'lumotlar tayyor bo'lgandan keyin).
        Background job sifatida ishga tushiriladi.
        """
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,
            client_name=self.name,
            # handler_names=None => runner MASTER_SYNC_ORDER ni ishlatadi
        )
        return {
            "message": (
                "To'liq sinxronizatsiya boshlandi!\n\n"
                "Tartib: Omborlar → Taminotchilar → Mijozlar → Mahsulotlar\n\n"
                "Sync Status maydonini kuzating — har bir modul tugaganda "
                "yangilanib boradi."
            )
        }

    # ── Partial Syncs ─────────────────────────────────────────────────

    @frappe.whitelist()
    def sync_warehouses(self):
        """Faqat omborxonalarni sync qilish (background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["warehouses"],
        )
        return {"message": "Omborxonalar sinxronizatsiyasi orqa fonda boshlandi. Sync Status maydonini kuzating."}

    @frappe.whitelist()
    def sync_suppliers(self):
        """Faqat taminotchilarni sync qilish (background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["suppliers"],
        )
        return {"message": "Taminotchilar sinxronizatsiyasi orqa fonda boshlandi. Sync Status maydonini kuzating."}

    @frappe.whitelist()
    def sync_customers(self):
        """Faqat mijozlarni sync qilish (background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["customers"],
        )
        return {"message": "Mijozlar sinxronizatsiyasi orqa fonda boshlandi. Sync Status maydonini kuzating."}

    @frappe.whitelist()
    def sync_purchases(self):
        """Faqat XARIDLARNI sync qilish — vozvratlar yuklanmaydi (background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["purchases_only"],
        )
        return {"message": "Xaridlar sinxronizatsiyasi orqa fonda boshlandi. Sync Status maydonini kuzating."}

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
    def sync_returns(self):
        """Faqat VOZVRATLARNI sync qilish — xaridlar yuklanmaydi (background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["returns_only"],
        )
        return {"message": "Vozvratlar sinxronizatsiyasi orqa fonda boshlandi. Sync Status maydonini kuzating."}

    @frappe.whitelist()
    def sync_exchange_rates(self):
        """Valyuta kurslarini sync qilish (background job)."""
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE,
            timeout=SYNC_TIMEOUT,

            client_name=self.name,
            handler_names=["exchange_rates"],
        )
        return {"message": "Valyuta kurslari sinxronizatsiyasi orqa fonda boshlandi. Sync Status maydonini kuzating."}

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

    # ── Stop Sync ─────────────────────────────────────────────────

    @frappe.whitelist()
    def stop_sync(self):
        """Barcha ishlab turgan sync joblarni to'xtatish (cache flag orqali)."""
        cache_key = f"ibox_sync_stop_{self.name}"
        frappe.cache().set_value(cache_key, True, expires_in_sec=300)  # 5 daqiqa

        frappe.db.set_value(
            "iBox Client", self.name, "sync_status",
            "TO'XTATISH buyrug'i berildi... ⏳",
            update_modified=False,
        )
        frappe.db.commit()

        return {"message": "Sinxronizatsiya to'xtatish buyrug'i yuborildi. Joriy modul tugagach to'xtaydi."}

    @frappe.whitelist()
    def clear_stop_flag(self):
        """Stop flagni tozalash (yangi sync boshlashdan oldin)."""
        frappe.cache().delete_value(f"ibox_sync_stop_{self.name}")

