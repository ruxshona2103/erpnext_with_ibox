# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
iBox API Client — Base client for making HTTP requests to iBox API.

429 (Too Many Requests) xatosi uchun avtomatik retry + exponential backoff.
Barcha endpoint handlerlar (shipments, purchases, directory, warehouses)
ushbu client.request() orqali ishlaydi, shuning uchun retry
logikasi barcha joyga avtomatik ta'sir qiladi.
"""

import time

import requests
import frappe

from erpnext_with_ibox.ibox.config import (
    API_RETRY_COUNT,
    API_RETRY_BASE_DELAY,
    API_RETRY_MAX_DELAY,
)


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
        self._shipments = None
        self._salaries = None
        self._currency_exchanges = None

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Filial-Id": str(self.filial_id),
        }

    def request(self, method: str, endpoint: str, params: dict = None, data: dict = None) -> dict:
        """
        Make HTTP request to iBox API with automatic retry on 429.

        429 (Too Many Requests) xatosida:
          - 1-urinish: 10s kutish
          - 2-urinish: 20s kutish
          - 3-urinish: 40s kutish
          - 4-urinish: 80s kutish
          - 5-urinish: 120s kutish (max)
          - Keyin raise qilinadi.

        Boshqa HTTP xatolar darhol raise qilinadi.
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()
        last_exception = None

        for attempt in range(1, API_RETRY_COUNT + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=data,
                    timeout=60,
                    verify=False,
                )
                response.raise_for_status()
                return response.json()

            except requests.exceptions.HTTPError as e:
                last_exception = e
                status_code = e.response.status_code if e.response is not None else 0

                if status_code == 429:
                    # Exponential backoff: base * 2^(attempt-1), max ga cheklangan
                    delay = min(API_RETRY_BASE_DELAY * (2 ** (attempt - 1)), API_RETRY_MAX_DELAY)
                    frappe.log_error(
                        title=f"iBox API 429 - {self.client_doc.client_name}",
                        message=(
                            f"URL: {url}\n"
                            f"429 Too Many Requests — {attempt}/{API_RETRY_COUNT} urinish.\n"
                            f"{delay} soniya kutilmoqda..."
                        ),
                    )
                    time.sleep(delay)
                    continue  # qayta urinish

                # Boshqa HTTP xatolar — darhol raise
                frappe.log_error(
                    title=f"iBox API Error - {self.client_doc.client_name}",
                    message=f"URL: {url}\nHTTP {status_code}: {str(e)}",
                )
                raise

            except requests.exceptions.RequestException as e:
                # Tarmoq xatosi (timeout, connection error)
                last_exception = e
                frappe.log_error(
                    title=f"iBox API Error - {self.client_doc.client_name}",
                    message=f"URL: {url}\nError: {str(e)}",
                )
                raise

        # Barcha retrylar tugadi, hali ham 429
        frappe.log_error(
            title=f"iBox API 429 FINAL - {self.client_doc.client_name}",
            message=(
                f"URL: {url}\n"
                f"{API_RETRY_COUNT} marta qayta urinildi, lekin hali ham 429.\n"
                f"iBox API rate limitiga tushib qoldi. Keyinroq urinib ko'ring."
            ),
        )
        raise last_exception
    
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

    @property
    def shipments(self):
        """Shipment endpoint handler (lazy-load)."""
        if self._shipments is None:
            from erpnext_with_ibox.ibox.api.endpoints.shipments import ShipmentEndpoint
            self._shipments = ShipmentEndpoint(self)
        return self._shipments

    @property
    def salaries(self):
        """Salary endpoint handler (lazy-load)."""
        if self._salaries is None:
            from erpnext_with_ibox.ibox.api.endpoints.salary import SalaryEndpoint
            self._salaries = SalaryEndpoint(self)
        return self._salaries

    @property
    def currency_exchanges(self):
        """Currency Exchange endpoint handler (lazy-load)."""
        if self._currency_exchanges is None:
            from erpnext_with_ibox.ibox.api.endpoints.currency_exchange import CurrencyExchangeEndpoint
            self._currency_exchanges = CurrencyExchangeEndpoint(self)
        return self._currency_exchanges

