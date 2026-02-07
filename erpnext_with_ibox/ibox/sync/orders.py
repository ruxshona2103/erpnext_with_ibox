# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Order Sync Handler - syncs iBox orders to ERPNext Sales Orders
"""

from typing import Generator
import frappe
from frappe.utils import now

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler
from erpnext_with_ibox.ibox.services import CustomerService, ItemService, WarehouseService


class OrderSyncHandler(BaseSyncHandler):
    """Handles syncing iBox orders to Sales Orders"""
    
    DOCTYPE = "Sales Order"
    NAME = "Order"
    
    def fetch_data(self) -> Generator[dict, None, None]:
        """Fetch orders from iBox API"""
        yield from self.api.orders.get_all()
    
    def get_existing_filter(self, data: dict) -> dict:
        """Check by iBox order ID"""
        return {"custom_ibox_order_id": data.get("id")}
    
    def sync_single(self, data: dict) -> bool:
        """
        Sync single order to Sales Order
        
        Returns:
            True if created, False if skipped
        """
        # Skip if already exists
        if self.exists(data):
            return False
        
        # Get or create related records
        customer = CustomerService.get_or_create(
            data.get("outlet_name", "Unknown")
        )
        
        # Create Sales Order
        so = frappe.new_doc("Sales Order")
        so.customer = customer
        so.company = self.client_doc.company
        so.transaction_date = data.get("date", now())[:10]
        so.delivery_date = data.get("date", now())[:10]
        so.currency = data.get("currency_code", "UZS")
        so.conversion_rate = 1
        
        # Custom fields
        so.custom_ibox_order_id = data.get("id")
        so.custom_ibox_number = data.get("number")
        so.custom_ibox_status = data.get("status")
        so.custom_ibox_client = self.client_doc.name
        
        # Add items
        for detail in data.get("order_details", []):
            product = detail.get("product", {})
            warehouse_data = detail.get("warehouse", {})
            
            item_code = ItemService.get_or_create(product, self.client_doc.company)
            warehouse = WarehouseService.get_or_create(warehouse_data, self.client_doc.company)
            
            so.append("items", {
                "item_code": item_code,
                "qty": detail.get("quantity", 1),
                "rate": detail.get("price", 0),
                "warehouse": warehouse,
                "delivery_date": data.get("date", now())[:10]
            })
        
        so.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return True
