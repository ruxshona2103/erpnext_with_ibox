# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sync Runner — iBox clientlar uchun sync jarayonini boshqarish.
Har bir client alohida background job sifatida ishga tushiriladi.
"""

import frappe
from frappe.utils import now

from erpnext_with_ibox.ibox.config import SYNC_QUEUE, SYNC_TIMEOUT


def sync_all_clients():
    """
    Barcha faol iBox Client lar uchun sync joblarni navbatga qo'yish.
    hooks.py dagi scheduled job (har kuni Toshkent 23:50) orqali chaqiriladi.
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
    Bitta iBox Client uchun sync handlerlarni ishga tushirish.

    Args:
        client_name: iBox Client document nomi
        handler_names: Ishga tushiriladigan handler kalitlari ro'yxati (default: hammasi)
    """
    from erpnext_with_ibox.ibox.sync import SYNC_HANDLERS
    from erpnext_with_ibox.ibox.api import IBoxAPIClient

    client_doc = frappe.get_doc("iBox Client", client_name)
    api = IBoxAPIClient(client_name)

    if handler_names is None:
        handler_names = list(SYNC_HANDLERS.keys())

    internal_api = None
    all_results = {}

    for handler_name in handler_names:
        handler_class = SYNC_HANDLERS.get(handler_name)
        if not handler_class:
            continue

        try:
            if getattr(handler_class, "NEEDS_INTERNAL_API", False):
                if internal_api is None:
                    from erpnext_with_ibox.ibox.api.internal_client import IBoxInternalClient
                    internal_api = IBoxInternalClient(client_name)
                handler = handler_class(api, client_doc, internal_api=internal_api)
            else:
                handler = handler_class(api, client_doc)
            result = handler.run()
            all_results[handler_name] = result
        except Exception:
            frappe.log_error(
                title=f"Sync Handler Error - {client_name}/{handler_name}",
                message=frappe.get_traceback(),
            )
            all_results[handler_name] = {"error": True}

    # Yakuniy natija
    summary_parts = []
    for name, res in all_results.items():
        if isinstance(res, dict) and "synced" in res:
            summary_parts.append(f"{name}: {res['synced']}/{res['processed']}")
        else:
            summary_parts.append(f"{name}: xatolik")

    frappe.db.set_value("iBox Client", client_name, {
        "sync_status": f"Tayyor: {', '.join(summary_parts)}",
        "last_sync_datetime": now(),
    }, update_modified=False)
    frappe.db.commit()

    return all_results
