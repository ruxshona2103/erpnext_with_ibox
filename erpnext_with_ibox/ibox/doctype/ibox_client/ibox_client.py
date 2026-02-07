# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class iBoxClient(Document):
    def validate(self):
        # Ensure URL doesn't have trailing slash
        if self.api_base_url and self.api_base_url.endswith("/"):
            self.api_base_url = self.api_base_url.rstrip("/")
    
    @frappe.whitelist()
    def test_connection(self):
        """Test API connection with stored credentials"""
        from erpnext_with_ibox.ibox.api import IBoxAPIClient
        
        try:
            client = IBoxAPIClient(self.name)
            response = client.orders.get_list(page=1, per_page=1)
            
            if "data" in response:
                total = response.get("total", len(response.get("data", [])))
                return {"success": True, "message": f"Connection successful! Found {total} orders."}
            else:
                return {"success": False, "message": f"API error: {response}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    @frappe.whitelist()
    def sync_now(self):
        """Manual sync trigger"""
        from erpnext_with_ibox.ibox.sync.runner import sync_client
        
        frappe.enqueue(
            sync_client,
            client_name=self.name,
            queue="long",
            timeout=3600
        )
        return {"message": "Sync started in background"}

