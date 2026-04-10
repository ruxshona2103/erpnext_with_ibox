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
        frappe.cache().delete_value(f"ibox_sync_lock_{self.name}_time")

    # ── Lock Management ──────────────────────────────────────────────

    @frappe.whitelist()
    def force_clear_locks(self):
        """
        Redis lock va stop flaglarni majburan tozalash.
        Agar sync to'xtab qolgan bo'lsa (crashed job) — bu method uning qulflini ocharadi.
        CFO Stan: Lock 2+ soat qo'lda turgan bo'lsa, avtomatik bekor qilish qabul qilishni talab qiladi.
        """
        try:
            lock_key = f"ibox_sync_lock_{self.name}"
            stop_key = f"ibox_sync_stop_{self.name}"
            lock_time_key = f"{lock_key}_time"
            
            # Lock yoshi tekshirish (log uchun)
            import time as time_module
            lock_set_time = frappe.cache().get_value(lock_time_key)
            lock_age = "Noma'lum"
            if lock_set_time:
                try:
                    lock_age_sec = time_module.time() - float(lock_set_time)
                    lock_age = f"{lock_age_sec/3600:.1f} soat" if lock_age_sec >= 3600 else f"{int(lock_age_sec/60)} min"
                except Exception:
                    pass
            
            # Lockni tozalash
            frappe.cache().delete_value(lock_key)
            frappe.cache().delete_value(lock_time_key)
            frappe.cache().delete_value(stop_key)
            
            # Status ni reset qilish
            frappe.db.set_value(
                "iBox Client",
                self.name,
                "sync_status",
                "Lock to'xtatildi ✓ Yangi sync boshlashga tayyor.",
                update_modified=False,
            )
            frappe.db.commit()
            
            frappe.log_error(
                title=f"Force Clear Locks - {self.name}",
                message=f"Lock age: {lock_age}. User triggered manual unlock."
            )
            
            return {
                "success": True,
                "message": f"Qulflar muvaffaqiyatli to'xtatildi (lock yoshi: {lock_age}). Yangi sync boshlashga tayyor."
            }
        except Exception as e:
            frappe.log_error(
                title=f"Force Clear Locks Error - {self.name}",
                message=str(e)
            )
            return {
                "success": False,
                "message": f"Qulflarni tozalashda xatolik: {str(e)[:100]}"
            }

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
    def sync_sales_returns(self):
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["sales_returns"],
        )
        return {"message": "Sotuv vozvratlari sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

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
    def sync_stock_adjustments(self):
        """Inventarizatsiya hujjatlarini sync qilish (maks. 200ta, background job)."""
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["stock_adjustments"],
        )
        return {"message": "Inventarizatsiya sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_transfers(self):
        """Omborlar arasi ko'chirishlarni sync qilish (maks. 200ta, background job)."""
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["transfers"],
        )
        return {"message": "Omborlar arasi ko'chirish sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_salaries(self):
        """Oylik maoshlarni sync qilish (maks. 200ta, background job)."""
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["salaries"],
        )
        return {"message": "Oylik maoshlar sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

    @frappe.whitelist()
    def sync_currency_exchanges(self):
        """Valyuta ayirboshlash hujjatlarini sync qilish (maks. 200ta, background job)."""
        self._prepare_for_sync()
        frappe.enqueue(
            "erpnext_with_ibox.ibox.sync.runner.sync_client",
            queue=SYNC_QUEUE, timeout=SYNC_TIMEOUT,
            client_name=self.name, handler_names=["currency_exchanges"],
        )
        return {"message": "Valyuta ayirboshlash sinxronizatsiyasi boshlandi. Sync Status ni kuzating."}

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

    # ── Setup Accounts ───────────────────────────────────────────────

    @frappe.whitelist()
    def setup_accounts(self):
        """
        iBox Client uchun barcha kerakli accountlar va Mode of Payment larni
        avtomatik yaratish va iBox Client fieldlariga to'ldirish.

        Yaratiladi:
          1. Purchase: Payable (UZS/USD)
          2. Sales: Receivable (UZS/USD), Sales Income (UZS/USD)
          3. Salary: Expense (UZS/USD), Cash (UZS/USD)
          4. Cashbox: har bir cashbox uchun Cash Account (UZS/USD) + Mode of Payment (UZS/USD)
        """
        if not self.company:
            frappe.throw("Company tanlanmagan. Avval Company ni belgilang.")

        company = self.company
        abbr = frappe.db.get_value("Company", company, "abbr")
        if not abbr:
            frappe.throw(f"Company '{company}' da abbreviation topilmadi.")

        client = self.name
        created = []
        skipped = []

        # ── Helper: Account yaratish yoki mavjudini topish ───────────
        def get_or_create_account(account_name, parent_account, account_type, currency):
            full_name = f"{account_name} - {abbr}"
            if frappe.db.exists("Account", full_name):
                skipped.append(full_name)
                return full_name

            doc = frappe.get_doc({
                "doctype": "Account",
                "account_name": account_name,
                "parent_account": parent_account,
                "company": company,
                "account_type": account_type,
                "account_currency": currency,
                "is_group": 0,
            })
            doc.insert(ignore_permissions=True)
            created.append(full_name)
            return full_name

        # ── Helper: Mode of Payment yaratish ─────────────────────────
        def get_or_create_mode_of_payment(mop_name, account_full_name):
            if frappe.db.exists("Mode of Payment", mop_name):
                # Account mapping mavjudligini tekshirish
                existing = frappe.db.get_value(
                    "Mode of Payment Account",
                    {"parent": mop_name, "company": company},
                    "default_account",
                )
                if not existing:
                    mop_doc = frappe.get_doc("Mode of Payment", mop_name)
                    mop_doc.append("accounts", {
                        "company": company,
                        "default_account": account_full_name,
                    })
                    mop_doc.save(ignore_permissions=True)
                skipped.append(f"MoP: {mop_name}")
                return mop_name

            doc = frappe.get_doc({
                "doctype": "Mode of Payment",
                "mode_of_payment": mop_name,
                "type": "Cash",
                "accounts": [{
                    "company": company,
                    "default_account": account_full_name,
                }],
            })
            doc.insert(ignore_permissions=True)
            created.append(f"MoP: {mop_name}")
            return mop_name

        # ── Helper: Parent account topish ────────────────────────────
        def find_parent(account_type_or_name, root_type=None):
            """is_group=1 bo'lgan parent accountni topish."""
            filters = {"company": company, "is_group": 1}
            if root_type:
                filters["root_type"] = root_type
            if account_type_or_name:
                filters["account_type"] = account_type_or_name
            result = frappe.db.get_value("Account", filters, "name")
            if result:
                return result
            # account_type bilan topilmasa, nom bo'yicha qidirish
            return frappe.db.get_value(
                "Account",
                {"company": company, "is_group": 1, "name": ["like", f"%{account_type_or_name}%"]},
                "name",
            )

        # ── Parent accountlarni aniqlash ─────────────────────────────
        cash_parent = find_parent("Cash", "Asset")
        if not cash_parent:
            frappe.throw("'Cash In Hand' parent account topilmadi. Chart of Accounts ni tekshiring.")

        receivable_parent = find_parent("", "Asset") or ""
        # Receivable uchun maxsus: "Accounts Receivable" yoki "Debtors" group
        receivable_parent = frappe.db.get_value(
            "Account",
            {"company": company, "is_group": 1, "name": ["like", "%Accounts Receivable%"]},
            "name",
        ) or frappe.db.get_value(
            "Account",
            {"company": company, "is_group": 1, "name": ["like", "%Debtors%"]},
            "name",
        )
        if not receivable_parent:
            frappe.throw("'Accounts Receivable' parent account topilmadi.")

        payable_parent = frappe.db.get_value(
            "Account",
            {"company": company, "is_group": 1, "name": ["like", "%Accounts Payable%"]},
            "name",
        )
        if not payable_parent:
            frappe.throw("'Accounts Payable' parent account topilmadi.")

        income_parent = frappe.db.get_value(
            "Account",
            {"company": company, "is_group": 1, "name": ["like", "%Direct Income%"]},
            "name",
        )
        if not income_parent:
            frappe.throw("'Direct Income' parent account topilmadi.")

        expense_parent = frappe.db.get_value(
            "Account",
            {"company": company, "is_group": 1, "name": ["like", "%Indirect Expenses%"]},
            "name",
        )
        if not expense_parent:
            frappe.throw("'Indirect Expenses' parent account topilmadi.")

        # ══════════════════════════════════════════════════════════════
        # 1. PURCHASE ACCOUNTS (Payable)
        # ══════════════════════════════════════════════════════════════
        uzs_payable = get_or_create_account(
            f"{client} - Payable (UZS)", payable_parent, "Payable", "UZS"
        )
        usd_payable = get_or_create_account(
            f"{client} - Payable (USD)", payable_parent, "Payable", "USD"
        )

        # ══════════════════════════════════════════════════════════════
        # 2. SALES ACCOUNTS (Receivable + Income)
        # ══════════════════════════════════════════════════════════════
        uzs_receivable = get_or_create_account(
            f"{client} - Receivable (UZS)", receivable_parent, "Receivable", "UZS"
        )
        usd_receivable = get_or_create_account(
            f"{client} - Receivable (USD)", receivable_parent, "Receivable", "USD"
        )
        uzs_sales_income = get_or_create_account(
            f"{client} - Sales Income (UZS)", income_parent, "Income Account", "UZS"
        )
        usd_sales_income = get_or_create_account(
            f"{client} - Sales Income (USD)", income_parent, "Income Account", "USD"
        )

        # ══════════════════════════════════════════════════════════════
        # 3. SALARY ACCOUNTS (Expense + Cash)
        # ══════════════════════════════════════════════════════════════
        uzs_salary_expense = get_or_create_account(
            f"{client} - Salary Expense (UZS)", expense_parent, "Expense Account", "UZS"
        )
        usd_salary_expense = get_or_create_account(
            f"{client} - Salary Expense (USD)", expense_parent, "Expense Account", "USD"
        )
        uzs_salary_cash = get_or_create_account(
            f"{client} - Salary Cash (UZS)", cash_parent, "Cash", "UZS"
        )
        usd_salary_cash = get_or_create_account(
            f"{client} - Salary Cash (USD)", cash_parent, "Cash", "USD"
        )

        # ══════════════════════════════════════════════════════════════
        # 4. CASHBOX ACCOUNTS + MODE OF PAYMENT
        # ══════════════════════════════════════════════════════════════
        for row in self.get("cashboxes", []):
            cb_name = row.cashbox_name
            if not cb_name:
                continue

            # Cash Accounts
            uzs_cash_acc = get_or_create_account(
                f"{client} - {cb_name} (UZS)", cash_parent, "Cash", "UZS"
            )
            usd_cash_acc = get_or_create_account(
                f"{client} - {cb_name} (USD)", cash_parent, "Cash", "USD"
            )

            # Mode of Payment
            uzs_mop = get_or_create_mode_of_payment(
                f"{client} - {cb_name} (UZS)", uzs_cash_acc
            )
            usd_mop = get_or_create_mode_of_payment(
                f"{client} - {cb_name} (USD)", usd_cash_acc
            )

            # Cashbox child table ni to'ldirish
            row.mode_of_payment = uzs_mop
            row.uzs_account = uzs_cash_acc
            row.usd_account = usd_cash_acc

        # ══════════════════════════════════════════════════════════════
        # 5. iBox Client FIELDLARNI TO'LDIRISH
        # ══════════════════════════════════════════════════════════════
        self.uzs_payable_account = uzs_payable
        self.usd_payable_account = usd_payable
        self.uzs_receivable_account = uzs_receivable
        self.usd_receivable_account = usd_receivable
        self.uzs_sales_income = uzs_sales_income
        self.usd_sales_income = usd_sales_income
        self.uzs_salary_expense_account = uzs_salary_expense
        self.usd_salary_expense_account = usd_salary_expense
        self.uzs_salary_cash_account = uzs_salary_cash
        self.usd_salary_cash_account = usd_salary_cash

        self.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success": True,
            "message": (
                f"Setup yakunlandi!\n\n"
                f"Yaratildi: {len(created)} ta\n"
                f"Mavjud (o'tkazib yuborildi): {len(skipped)} ta\n\n"
                f"Yaratilganlar:\n" + "\n".join(f"  • {c}" for c in created) if created
                else f"Setup yakunlandi!\n\nBarcha accountlar allaqachon mavjud ({len(skipped)} ta)."
            ),
        }
