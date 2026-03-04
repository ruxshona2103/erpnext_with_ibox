# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Payment Received Sync Handler — iBox payment-received/list -> ERPNext Payment Entry.
"""

from typing import Generator
import frappe
from frappe.utils import getdate

from erpnext_with_ibox.ibox.config import SLUG_PAYMENTS
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler

class PaymentSyncHandler(BaseSyncHandler):
    DOCTYPE = "Payment Entry"
    NAME = "Payments"

    def fetch_data(self) -> Generator[dict, None, None]:
        # To'lovlar API si pagination bilan ishlaydi
        page = 1
        per_page = 100
        total_pages = None

        while True:
            response = self.api.request(
                method="GET",
                endpoint=SLUG_PAYMENTS,
                params={"page": page, "per_page": per_page}
            )
            records = response.get("data", [])
            
            if total_pages is None:
                total_pages = response.get("last_page", 1)

            if not records:
                break

            for record in records:
                yield record

            if page >= total_pages or len(records) < per_page:
                break

            page += 1

    def upsert(self, record: dict) -> bool:
        # Faqat "Оплата от клиента" (payment_type == 1) bo'lganlarni kiritamiz
        payment_type = record.get("payment_type")
        if payment_type != 1:
            return False  # Ignore qolganlarini

        ibox_payment_id = str(record.get("id"))
        outlet_id = record.get("outlet_id")
        posting_date = (record.get("date") or "").split("T")[0]

        # Customer topamiz
        customer = frappe.db.get_value(
            "Customer",
            {
                "custom_ibox_id": outlet_id,
                "custom_ibox_client": self.client_name
            },
            "name"
        )
        if not customer:
            frappe.logger().warning(f"Customer topilmadi: outlet_id={outlet_id} payment={ibox_payment_id}. O'tkazib yuborildi.")
            return False

        changed = False
        payment_details = record.get("payment_details", [])

        for detail in payment_details:
            detail_id = str(detail.get("id"))
            amount = detail.get("amount", 0)
            cashbox_info = detail.get("cashbox", {})
            currency_info = detail.get("currency", {})
            
            cashbox_id = str(detail.get("cashbox_id"))
            
            # Mapping orqali ERPNext Mode of Payment ni topamiz
            mode_of_payment = self._get_mode_of_payment(cashbox_id)
            if not mode_of_payment:
                frappe.logger().warning(f"Cashbox mapping topilmadi: cashbox_id={cashbox_id} ibox_client={self.client_name}. To'lov ID={ibox_payment_id}. O'tkazib yuborildi.")
                continue

            # Deduplication
            existing = frappe.db.get_value(
                "Payment Entry",
                {"custom_ibox_payment_detail_id": detail_id},
                "name"
            )

            if existing:
                # Odatda to'lovlar o'zgarmaydi. Lekin xohlasak bu yerda update yozish mumkin.
                continue

            # Target currency (USD/UZS) dan qat'iy nazar ERPNext o'zi hal qilishi uchun 
            # asosan Amount va Customer beriladi.
            # Target currency (USD/UZS) dan qat'iy nazar ERPNext o'zi hal qilishi uchun 
            # asosan Amount va Customer beriladi.
            doc = frappe.get_doc({
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": customer,
                "paid_amount": amount,
                "received_amount": amount,
                "mode_of_payment": mode_of_payment,
                "company": self.client_doc.company,
                "posting_date": posting_date or frappe.utils.today(),
                "custom_ibox_client": self.client_name,
                "custom_ibox_payment_id": ibox_payment_id,
                "custom_ibox_payment_detail_id": detail_id,
            })
            
            # Accountlarni Mode of Payment dan oladi, Default setup bo'lmasa xato beradi
            try:
                doc.setup_party_account_field()
                doc.set_missing_values()
                doc.insert(ignore_permissions=True)
                # doc.submit() # Avtomatik submit qilish kerak bo'lsa yoqamiz.
                changed = True
            except frappe.exceptions.ValidationError as e:
                frappe.log_error(
                    title=f"Payments Upsert Error - {self.client_name}",
                    message=f"Validation: {ibox_payment_id} detail={detail_id}\n{frappe.get_traceback()}"
                )
            except Exception as e:
                frappe.log_error(
                    title=f"Payments Upsert Error - {self.client_name}",
                    message=f"System: {ibox_payment_id} detail={detail_id}\n{frappe.get_traceback()}"
                )

        return changed

    def _get_mode_of_payment(self, cashbox_id: str) -> str:
        # iBox Client dagi iBox Cashbox Mapping jadvalidan qidirish
        # iBox Cashbox Mapping nomi bilan Child Table `cashboxes` qilib ulangan.
        client_doc = frappe.get_doc("iBox Client", self.client_name)
        for row in client_doc.get("cashboxes", []):
            if str(row.cashbox_id) == str(cashbox_id):
                return row.mode_of_payment
        return None
