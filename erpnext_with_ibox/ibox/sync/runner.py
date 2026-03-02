# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sync Runner — iBox clientlar uchun sync jarayonini boshqarish.

sync_client():
    - handler_names ko'rsatilmasa, MASTER_SYNC_ORDER tartibida barcha master
      handlerlarni ishga tushiradi (warehouses → suppliers → customers → items).
    - Har bir modul tugagandan keyin sync_status yangilanadi (real-time feedback).
    - Bitta handler xato qilsa, xatolik loglanib, qolganlar davom etadi.
"""

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
}


def sync_all_clients():
    """
    Barcha faol iBox Client lar uchun sync joblarni navbatga qo'yish.
    hooks.py dagi scheduled job (har kuni 23:50) orqali chaqiriladi.
    Har bir client mustaqil background job sifatida ishlaydi.
    """
    clients = frappe.get_all("iBox Client", filters={"enabled": 1}, pluck="name")

    for client_name in clients:
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


def sync_client(client_name: str, handler_names: list = None):
    """
    Bitta iBox Client uchun sync handlerlarni to'g'ri ketma-ketlikda ishga tushirish.

    Args:
        client_name:   iBox Client document nomi
        handler_names: Ishga tushiriladigan handler kalitlari ro'yxati.
                       None bo'lsa — MASTER_SYNC_ORDER ishlatiladi
                       (warehouses → suppliers → customers → items).
    """
    from erpnext_with_ibox.ibox.sync import SYNC_HANDLERS, MASTER_SYNC_ORDER
    from erpnext_with_ibox.ibox.api import IBoxAPIClient

    client_doc = frappe.get_doc("iBox Client", client_name)
    api = IBoxAPIClient(client_name)

    # handler_names berilmagan bo'lsa — master tartibdan foydalanish
    if handler_names is None:
        handler_names = MASTER_SYNC_ORDER

    internal_api = None
    all_results = {}

    # Stop flagni tozalash — yangi sync boshlanayotganda eski stop flag to'sqinlik qilmasligi uchun
    frappe.cache().delete_value(f"ibox_sync_stop_{client_name}")

    _set_status(client_name, "To'liq sinxronizatsiya boshlandi...")

    for handler_name in handler_names:
        handler_class = SYNC_HANDLERS.get(handler_name)
        if not handler_class:
            frappe.log_error(
                title=f"Sync - Noto'g'ri handler - {client_name}",
                message=f"'{handler_name}' handler SYNC_HANDLERS da topilmadi.",
            )
            continue

        label = _MODULE_LABELS.get(handler_name, handler_name)

        # Boshlanishi haqida xabar
        _set_status(client_name, f"Sinxronizatsiya: {label} yuklanmoqda...")

        try:
            # Internal API kerak bo'lsa (Suppliers) — lazy init
            if getattr(handler_class, "NEEDS_INTERNAL_API", False):
                if internal_api is None:
                    from erpnext_with_ibox.ibox.api.internal_client import IBoxInternalClient
                    internal_api = IBoxInternalClient(client_name)
                handler = handler_class(api, client_doc, internal_api=internal_api)
            else:
                handler = handler_class(api, client_doc)

            result = handler.run()
            all_results[handler_name] = result

            # Modul tugadi — natija bilan status yangilash
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
            summary_parts.append(f"{lbl}: {res['synced']}/{res['processed']}")
        else:
            summary_parts.append(f"{lbl}: xatolik")

    frappe.db.set_value(
        "iBox Client",
        client_name,
        {
            "sync_status": f"Tayyor ✓ | {', '.join(summary_parts)}",
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
