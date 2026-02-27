# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Supplier Sync Handler — iBox /api/outlet/supplier -> ERPNext Supplier.
Internal API (login/password token) orqali ishlaydi.
"""

import re
from typing import Generator

import frappe

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class SupplierSyncHandler(BaseSyncHandler):
    DOCTYPE = "Supplier"
    NAME = "Suppliers"
    NEEDS_INTERNAL_API = True

    def __init__(self, api_client, client_doc, internal_api=None):
        super().__init__(api_client, client_doc)
        self.internal_api = internal_api

    def fetch_data(self) -> Generator[dict, None, None]:
        yield from self.internal_api.supplier.get_all()

    def upsert(self, record: dict) -> bool:
        ibox_id = record.get("id")
        name = self._clean(record.get("name"), "Noma'lum yetkazuvchi")
        balances_str = self._clean(record.get("balances"))

        balance_uzs = self._parse_balance(balances_str, "UZS")
        balance_usd = self._parse_balance(balances_str, "USD")

        # 1) iBox ID bo'yicha qidirish
        existing = frappe.db.get_value(
            "Supplier",
            {"custom_ibox_id": ibox_id, "custom_ibox_client": self.client_name},
            "name",
        )

        # 2) Agar iBox ID bilan topilmasa, nom bo'yicha qidirish (qo'lda yaratilgan bo'lishi mumkin)
        if not existing:
            existing_by_name = frappe.db.get_value(
                "Supplier", {"supplier_name": name}, "name"
            )
            if existing_by_name:
                # Mavjud supplier'ga iBox ma'lumotlarini bog'lash
                frappe.db.set_value("Supplier", existing_by_name, {
                    "custom_ibox_id": ibox_id,
                    "custom_ibox_client": self.client_name,
                    "custom_ibox_balances": balances_str,
                    "custom_balance_uzs": balance_uzs,
                    "custom_balance_usd": balance_usd,
                })
                return True

        if existing:
            current = frappe.db.get_value(
                "Supplier",
                existing,
                ["supplier_name", "custom_ibox_balances", "custom_balance_uzs", "custom_balance_usd"],
                as_dict=True,
            )
            updates = {}
            if current.supplier_name != name:
                updates["supplier_name"] = name
            if current.custom_ibox_balances != balances_str:
                updates["custom_ibox_balances"] = balances_str
            if current.custom_balance_uzs != balance_uzs:
                updates["custom_balance_uzs"] = balance_uzs
            if current.custom_balance_usd != balance_usd:
                updates["custom_balance_usd"] = balance_usd

            if updates:
                frappe.db.set_value("Supplier", existing, updates)
                return True
            return False

        frappe.get_doc({
            "doctype": "Supplier",
            "supplier_name": name,
            "supplier_group": "All Supplier Groups",
            "supplier_type": "Company",
            "custom_ibox_id": ibox_id,
            "custom_ibox_client": self.client_name,
            "custom_ibox_balances": balances_str,
            "custom_balance_uzs": balance_uzs,
            "custom_balance_usd": balance_usd,
        }).insert(ignore_permissions=True)
        return True

    @staticmethod
    def _clean(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value).strip() or default

    @staticmethod
    def _parse_balance(balances_str: str, currency: str) -> float:
        """
        Balances stringdan ma'lum valyutani ajratib olish.

        Misollar:
            "43150.11 USD, -2174814185.6 UZS" → UZS: -2174814185.6, USD: 43150.11
            "0 UZS" → UZS: 0.0, USD: 0.0
        """
        if not balances_str:
            return 0.0
        match = re.search(rf"(-?[\d.,]+)\s*{currency}", balances_str)
        if match:
            # Vergulni olib tashlash (1,000.50 → 1000.50)
            return float(match.group(1).replace(",", ""))
        return 0.0
