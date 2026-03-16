# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sync Runner — iBox clientlar uchun sync jarayonini boshqarish.

sync_client():
    - handler_names ko'rsatilmasa, MASTER_SYNC_ORDER tartibida barcha master
      handlerlarni ishga tushiradi (warehouses → suppliers → customers → items).
    - Har bir modul tugagandan keyin sync_status yangilanadi (real-time feedback).
    - Bitta handler xato qilsa, xatolik loglanib, qolganlar davom etadi.

sync_all_clients():
    - 700+ client uchun staggered scheduling (30s oraliq).
"""

import time

import frappe
from frappe.utils import now

from erpnext_with_ibox.ibox.config import SYNC_QUEUE, SYNC_TIMEOUT

# Odam-o'qiydigan modul nomlari (status xabarlari uchun)
_MODULE_LABELS = {
    "warehouses":      "Omborlar",
    "suppliers":       "Taminotchilar",
    "customers":       "Mijozlar",
    "items":           "Mahsulotlar",
    "purchases":       "Xaridlar/Vozvratlar",
    "purchases_only":  "Xaridlar",
    "returns_only":    "Vozvratlar",
    "exchange_rates":  "Valyuta kurslari",
    "sales":              "Sotuvlar (Otgruzki)",
    "sales_returns":      "Sotuv vozvratlari",
    "payment_transfers":  "Pul ko'chirishlar",
    "stock_adjustments":  "Inventarizatsiya",
    "transfers":          "Omborlar arasi ko'chirish",
    "salaries":           "Oylik maoshlar",
    "currency_exchanges": "Valyuta ayirboshlash",
}

# Stagger delay — har bir client orasidagi kutish (sekundlarda)
CLIENT_STAGGER_DELAY = 30


def sync_all_clients():
    """
    Barcha faol iBox Client lar uchun sync joblarni navbatga qo'yish.
    hooks.py dagi scheduled job orqali chaqiriladi.

    700+ client uchun staggered scheduling:
    - Har bir client mustaqil background job sifatida ishlaydi
    - Clientlar orasida 30s kutish — DB va Redis yukini kamaytiradi
    """
    clients = frappe.get_all("iBox Client", filters={"enabled": 1}, pluck="name")

    for i, client_name in enumerate(clients):
        try:
            frappe.enqueue(
                "erpnext_with_ibox.ibox.sync.runner.sync_client",
                queue=SYNC_QUEUE,
                timeout=SYNC_TIMEOUT,
                job_id=f"ibox_sync_{client_name}",
                client_name=client_name,
            )
        except Exception:
            frappe.log_error(
                title=f"Sync Enqueue Error - {client_name}",
                message=frappe.get_traceback(),
            )

        # Stagger — oxirgi clientdan keyin kutish shart emas
        if i < len(clients) - 1:
            time.sleep(CLIENT_STAGGER_DELAY)


def sync_client(client_name: str, handler_names: list = None, is_cleanup_job: bool = False):
    """
    Bitta iBox Client uchun sync handlerlarni to'g'ri ketma-ketlikda ishga tushirish.

    Args:
        client_name:   iBox Client document nomi
        handler_names: Ishga tushiriladigan handler kalitlari ro'yxati.
                       None bo'lsa — MASTER_SYNC_ORDER ishlatiladi.
        is_cleanup_job: True bo'lsa — cleanup logic barcha handlerlar uchun ishlatiladi.
                       False (default) bo'lsa — cleanup faqat Full Sync (handler_names=None) 
                       uchun ishga tushadi. Bu PARTIAL SYNCS (sync_customers, sync_items) 
                       uchun cleanup-ni disabled qiladi (xavfsizlik uchun).
    """
    from erpnext_with_ibox.ibox.sync import SYNC_HANDLERS, MASTER_SYNC_ORDER
    from erpnext_with_ibox.ibox.api import IBoxAPIClient

    client_doc = frappe.get_doc("iBox Client", client_name)
    api = IBoxAPIClient(client_name)

    is_full_sync = handler_names is None

    if handler_names is None:
        handler_names = MASTER_SYNC_ORDER

    internal_api = None
    all_results = {}

    # Stop flag va lock tozalash — yangi sync boshlanayotganda eski sarqitlar to'sqinlik qilmasligi uchun
    # CRITICAL: Agar lock 2+ soat qo'lda qolgan bo'lsa (crashed job) — uni avtomatik tozalash
    lock_key = f"ibox_sync_lock_{client_name}"
    lock_age_key = f"ibox_sync_lock_time_{client_name}"
    
    current_lock = frappe.cache().get_value(lock_key)
    if current_lock:
        # Lock borligini tekshirish va yoshi
        import time as time_module
        lock_set_time = frappe.cache().get_value(lock_age_key)
        if lock_set_time:
            try:
                lock_age_seconds = time_module.time() - float(lock_set_time)
                if lock_age_seconds > 7200:  # 2+ soat
                    frappe.log_error(
                        title=f"Auto-cleared aged lock - {client_name}",
                        message=f"Lock age: {lock_age_seconds/3600:.1f} hours. Automatic cleanup triggered."
                    )
                    frappe.cache().delete_value(lock_key)
                    frappe.cache().delete_value(lock_age_key)
            except Exception:
                pass
    
    frappe.cache().delete_value(f"ibox_sync_stop_{client_name}")
    
    frappe.cache().set_value(
        f"ibox_sync_full_{client_name}",
        1 if is_full_sync else 0,
        expires_in_sec=SYNC_TIMEOUT,
    )

    # Partial synclarda to'xtab qolmasligi uchun (agar kimdir partial bosgan bo'lsa),
    # ba'zi joylarda faqat To'liq syncdagina tozalang deb berilgan edi. Biz ikkalasining yaxshi xususiyatini olamiz:
    if is_full_sync:
        frappe.cache().delete_value(f"ibox_sync_stop_{client_name}")
        _set_status(client_name, "To'liq sinxronizatsiya boshlandi...")
    else:
        _set_status(client_name, f"Qisman sinxronizatsiya boshlandi: {', '.join(handler_names)}...")

    for handler_name in handler_names:
        # Har bir handler oldidan stop tekshirish
        if frappe.cache().get_value(f"ibox_sync_stop_{client_name}"):
            _set_status(client_name, "TO'XTATILDI ⛔")
            frappe.cache().delete_value(f"ibox_sync_stop_{client_name}")
            frappe.cache().delete_value(f"ibox_sync_lock_{client_name}")
            frappe.cache().delete_value(f"ibox_sync_full_{client_name}")
            break

        handler_class = SYNC_HANDLERS.get(handler_name)
        if not handler_class:
            frappe.log_error(
                title=f"Sync - Noto'g'ri handler - {client_name}",
                message=f"'{handler_name}' handler SYNC_HANDLERS da topilmadi.",
            )
            continue

        label = _MODULE_LABELS.get(handler_name, handler_name)

        _set_status(client_name, f"Sinxronizatsiya: {label} yuklanmoqda...")

        try:
            # Internal API kerak bo'lsa (Suppliers) — lazy init
            if getattr(handler_class, "NEEDS_INTERNAL_API", False):
                if internal_api is None:
                    from erpnext_with_ibox.ibox.api.internal_client import IBoxInternalClient
                    internal_api = IBoxInternalClient(client_name)
                handler = handler_class(api, client_doc, is_cleanup_job=is_cleanup_job, internal_api=internal_api)
            else:
                handler = handler_class(api, client_doc, is_cleanup_job=is_cleanup_job)

            result = handler.run()
            all_results[handler_name] = result

            # Locked yoki stopped — keyingi handlerlarga o'tmaslik
            if result.get("locked") or result.get("stopped"):
                break

            synced = result.get("synced", 0)
            processed = result.get("processed", 0)
            errors = result.get("errors", 0)
            err_info = f", {errors} ta xato" if errors else ""
            _set_status(
                client_name,
                f"Sinxronizatsiya: {label} tugatildi "
                f"({synced} ta yangi, {processed} ta qayta ishlandi{err_info})..."
            )

        except Exception:
            frappe.log_error(
                title=f"Sync Handler Error - {client_name}/{handler_name}",
                message=frappe.get_traceback(),
            )
            all_results[handler_name] = {"error": True, "synced": 0, "processed": 0, "errors": 1}
            _set_status(
                client_name,
                f"Sinxronizatsiya: {label} da xatolik yuz berdi, keyingisiga o'tilmoqda..."
            )

    # ── Yakuniy status ────────────────────────────────────────────────
    summary_parts = []
    for name, res in all_results.items():
        lbl = _MODULE_LABELS.get(name, name)
        if isinstance(res, dict) and "synced" in res:
            cleanup = res.get("cleanup")
            cleanup_str = ""
            if cleanup:
                deleted = cleanup.get("deleted", 0)
                aborted = cleanup.get("aborted", False)
                if aborted:
                    cleanup_str = " ⚠️"
                elif deleted > 0:
                    cleanup_str = f" 🗑️{deleted}"
            summary_parts.append(f"{lbl}: {res['synced']}/{res['processed']}{cleanup_str}")
        else:
            summary_parts.append(f"{lbl}: xatolik")

    # Lock tozalash — DOIMO
    frappe.cache().delete_value(f"ibox_sync_lock_{client_name}")
    frappe.cache().delete_value(f"ibox_sync_stop_{client_name}")
    frappe.cache().delete_value(f"ibox_sync_full_{client_name}")

    frappe.db.set_value(
        "iBox Client",
        client_name,
        {
            "sync_status": f"Tayyor ✓ | {', '.join(summary_parts)}" if summary_parts else "Tayyor ✓",
            "last_sync_datetime": now(),
        },
        update_modified=False,
    )
    frappe.db.commit()

    return all_results


# ── Internal helper ───────────────────────────────────────────────────────────

def _set_status(client_name: str, status: str):
    """sync_status maydonini real-time yangilash."""
    try:
        frappe.db.set_value(
            "iBox Client", client_name, "sync_status", status,
            update_modified=False,
        )
        frappe.db.commit()
    except Exception:
        pass
