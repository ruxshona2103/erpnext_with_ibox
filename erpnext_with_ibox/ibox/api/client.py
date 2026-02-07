# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
iBox API Client - Base client for making HTTP requests to iBox API
"""

import requests
import frappe
from frappe import _


class IBoxAPIClient:
    """Base iBox API client for making HTTP requests"""
    
    def __init__(self, ibox_client_name: str):
        self.client_doc = frappe.get_doc("iBox Client", ibox_client_name)
        self.base_url = self.client_doc.api_base_url.rstrip("/")
        self.token = self.client_doc.get_password("bearer_token")
        self.filial_id = self.client_doc.filial_id or 1
        
        # Lazy-loaded endpoint handlers
        self._orders = None
    
    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Filial-Id": str(self.filial_id)
        }
    
    def request(self, method: str, endpoint: str, params: dict = None, data: dict = None) -> dict:
        """Make HTTP request to iBox API"""
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data,
                timeout=60,
                verify=False  # Skip SSL verification for iBox
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            frappe.log_error(
                title=f"iBox API Error - {self.client_doc.client_name}",
                message=f"URL: {url}\nError: {str(e)}"
            )
            raise
    
    @property
    def orders(self):
        """Lazy-load orders endpoint handler"""
        if self._orders is None:
            from erpnext_with_ibox.ibox.api.endpoints.orders import OrdersEndpoint
            self._orders = OrdersEndpoint(self)
        return self._orders
