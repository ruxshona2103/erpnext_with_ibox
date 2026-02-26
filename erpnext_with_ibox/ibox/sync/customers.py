# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Customer Sync Handler — iBox outlet_client -> ERPNext Customer.
"""

from typing import Generator

import frappe

from erpnext_with_ibox.ibox.config import SLUG_CUSTOMERS
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class CustomerSyncHandler(BaseSyncHandler):
    DOCTYPE = "Customer"
    NAME = "Customers"

    def fetch_data(self) -> Generator[dict, None, None]:
        yield from self.api.directory.get_all(slug=SLUG_CUSTOMERS)

    def upsert(self, record: dict) -> bool:
        ibox_id = record.get("id")
        name = self._clean(record.get("name"), "Noma'lum mijoz")
        phone = self._clean(record.get("main_phone"))

        existing = frappe.db.get_value(
            "Customer",
            {"custom_ibox_id": ibox_id, "custom_ibox_client": self.client_name},
            "name",
        )

        if existing:
            changed = False
            if frappe.db.get_value("Customer", existing, "customer_name") != name:
                frappe.db.set_value("Customer", existing, "customer_name", name)
                changed = True
            if phone and frappe.db.get_value("Customer", existing, "custom_main_phone") != phone:
                frappe.db.set_value("Customer", existing, "custom_main_phone", phone)
                changed = True
            return changed

        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": name,
            "customer_type": "Individual",
            "customer_group": "All Customer Groups",
            "territory": "All Territories",
            "custom_ibox_id": ibox_id,
            "custom_ibox_client": self.client_name,
            "custom_main_phone": phone,
        }).insert(ignore_permissions=True)
        return True

    @staticmethod
    def _clean(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default
