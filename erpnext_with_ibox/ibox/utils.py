"""
iBox Utility functions — log tozalash, audit, va yordamchi funksiyalar.
"""

import frappe
from frappe.utils import add_days, now_datetime


def cleanup_old_logs():
    """
    7 kundan eski Error Log va iBox Sync loglarni o'chirish.
    Database bloating ni oldini oladi.

    hooks.py → scheduler_events → daily dan chaqiriladi.
    """
    cutoff = add_days(now_datetime(), -7)

    # Error Log tozalash
    try:
        old_logs = frappe.get_all(
            "Error Log",
            filters={"creation": ["<", cutoff]},
            pluck="name",
            limit=500,
        )
        for name in old_logs:
            frappe.delete_doc("Error Log", name, ignore_permissions=True)

        if old_logs:
            frappe.db.commit()
            frappe.logger().info(f"iBox: {len(old_logs)} ta eski Error Log o'chirildi")
    except Exception:
        frappe.log_error(
            title="Log Cleanup Error",
            message=frappe.get_traceback(),
        )
