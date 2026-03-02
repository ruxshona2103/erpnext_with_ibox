# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
iBox API Client - Base client for making HTTP requests to iBox API
"""

import requests
import frappe


class IBoxAPIClient:
    """Base iBox API client for making HTTP requests"""
    
    def __init__(self, ibox_client_name: str):
        self.client_doc = frappe.get_doc("iBox Client", ibox_client_name)
        self.base_url = self.client_doc.api_base_url.rstrip("/")
        self.token = self.client_doc.get_password("bearer_token")
        self.filial_id = self.client_doc.filial_id or 1
        
        self._directory = None
        self._warehouses = None
        self._purchases = None
    
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
    def directory(self):
        """Directory endpoint handler (lazy-load)."""
        if self._directory is None:
            from erpnext_with_ibox.ibox.api.endpoints.directory import DirectoryEndpoint
            self._directory = DirectoryEndpoint(self)
        return self._directory

    @property
    def warehouses(self):
        """Warehouse endpoint handler (lazy-load)."""
        if self._warehouses is None:
            from erpnext_with_ibox.ibox.api.endpoints.warehouses import WarehouseEndpoint
            self._warehouses = WarehouseEndpoint(self)
        return self._warehouses

    @property
    def purchases(self):
        """Purchase endpoint handler (lazy-load)."""
        if self._purchases is None:
            from erpnext_with_ibox.ibox.api.endpoints.purchases import PurchaseEndpoint
            self._purchases = PurchaseEndpoint(self)
        return self._purchases
