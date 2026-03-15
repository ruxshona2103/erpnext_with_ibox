# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
iBox Internal API Client — login/password orqali token olib ishlaydigan client.
Directory API dan farqli ravishda, bu client /api/user/login orqali autentifikatsiya qiladi
va tokenni cache'da saqlaydi.
"""

import re
import time

import requests
import frappe

from erpnext_with_ibox.ibox.config import LOGIN_ENDPOINT, INTERNAL_TOKEN_TTL


class IBoxInternalClient:
    """Login/password orqali token olib ishlaydigan iBox API client"""

    def __init__(self, ibox_client_name: str):
        self.client_doc = frappe.get_doc("iBox Client", ibox_client_name)
        self.base_url = self.client_doc.api_base_url.rstrip("/")
        self.filial_id = self.client_doc.filial_id or 1
        self.client_name = ibox_client_name

        self._login = self.client_doc.internal_api_login
        self._password = self.client_doc.get_password("internal_api_password")

        # ── Credential Validation ─────────────────────────────────────
        if not self._login or not self._password:
            frappe.log_error(
                title=f"iBox Internal Login Failed for Client {self.client_name}",
                message=(
                    "Internal API login yoki password bo'sh.\n"
                    f"Client: {self.client_name}\n"
                    "iBox Client sozlamalarida 'Internal API Login' va "
                    "'Internal API Password' maydonlarini to'ldiring."
                ),
            )
            frappe.throw(
                f"iBox Internal API uchun login/password bo'sh — "
                f"Client: {self.client_name}. "
                f"Iltimos, iBox Client sozlamalarini tekshiring.",
                title="Internal API Credentials Missing",
            )

        self._supplier = None
        self._exchange_rate = None

    @property
    def _cache_key(self) -> str:
        return f"ibox_internal_token_{self.client_name}"

    def _get_token(self) -> str:
        """
        Cache'dan token olish. Yo'q yoki muddati o'tgan bo'lsa, login qilib yangi token olish.
        """
        cache = frappe.cache()
        cached = cache.get_value(self._cache_key)

        if cached:
            token, expires_at = cached
            if time.time() < expires_at:
                return token

        # Yangi token olish
        token = self._login_and_get_token()

        # Cache'ga saqlash (TTL bilan)
        cache.set_value(self._cache_key, (token, time.time() + INTERNAL_TOKEN_TTL))
        return token

    def _login_and_get_token(self) -> str:
        """iBox /api/user/login endpointiga POST qilib token olish."""
        url = f"{self.base_url}{LOGIN_ENDPOINT}"

        try:
            response = requests.post(
                url,
                json={"login": self._login, "password": self._password},
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=30,
                verify=False,
            )
            response.raise_for_status()
            data = response.json()
            token = data.get("token")

            if not token:
                raise ValueError("Login javobida token yo'q")

            return token

        except requests.exceptions.RequestException as e:
            frappe.log_error(
                title=f"iBox Internal Login Failed for Client {self.client_name}",
                message=f"URL: {url}\nLogin: {self._login}\nError: {str(e)}",
            )
            raise

    def _invalidate_token(self):
        """Cache'dagi tokenni o'chirish."""
        frappe.cache().delete_value(self._cache_key)

    def _get_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Filial-Id": str(self.filial_id),
        }

    def request(self, method: str, endpoint: str, params: dict = None, data: dict = None) -> dict:
        """
        HTTP request yuborish. Token 401 qaytarsa, cache'ni tozalab qayta urinish.
        """
        url = f"{self.base_url}{endpoint}"
        token = self._get_token()

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._get_headers(token),
                params=params,
                json=data,
                timeout=60,
                verify=False,
            )

            # 401 bo'lsa — token eskirgan, qayta login
            if response.status_code == 401:
                self._invalidate_token()
                token = self._get_token()
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self._get_headers(token),
                    params=params,
                    json=data,
                    timeout=60,
                    verify=False,
                )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            frappe.log_error(
                title=f"iBox Internal API Error - {self.client_name}",
                message=f"URL: {url}\nError: {str(e)}",
            )
            raise

    @property
    def supplier(self):
        """Supplier endpoint handler (lazy-load)."""
        if self._supplier is None:
            from erpnext_with_ibox.ibox.api.endpoints.supplier import SupplierEndpoint
            self._supplier = SupplierEndpoint(self)
        return self._supplier

    @property
    def exchange_rate(self):
        """Exchange Rate endpoint handler (lazy-load)."""
        if self._exchange_rate is None:
            from erpnext_with_ibox.ibox.api.endpoints.exchange_rate import ExchangeRateEndpoint
            self._exchange_rate = ExchangeRateEndpoint(self)
        return self._exchange_rate

    @property
    def cashbox(self):
        """Cashbox endpoint handler (lazy-load)."""
        if not hasattr(self, '_cashbox') or self._cashbox is None:
            from erpnext_with_ibox.ibox.api.endpoints.cashbox import CashboxEndpoint
            self._cashbox = CashboxEndpoint(self)
        return self._cashbox

    @property
    def stock_adjustments(self):
        """Stock Adjustment endpoint handler (lazy-load). /api/document/ — Internal API."""
        if not hasattr(self, '_stock_adjustments') or self._stock_adjustments is None:
            from erpnext_with_ibox.ibox.api.endpoints.stock_adjustment import StockAdjustmentEndpoint
            self._stock_adjustments = StockAdjustmentEndpoint(self)
        return self._stock_adjustments

    @property
    def transfers(self):
        """Transfer endpoint handler (lazy-load). /api/document/ — Internal API."""
        if not hasattr(self, '_transfers') or self._transfers is None:
            from erpnext_with_ibox.ibox.api.endpoints.transfer import TransferEndpoint
            self._transfers = TransferEndpoint(self)
        return self._transfers
# ── Convenience Function ──────────────────────────────────────────────────────

def get_internal_session_token(client_doc) -> str:
    """
    Tashqi modullar uchun qulay funksiya — iBox Internal API token olish.

    Args:
        client_doc: iBox Client document (yoki document nomi - str)

    Returns:
        str: Bearer token

    Usage:
        from erpnext_with_ibox.ibox.api.internal_client import get_internal_session_token
        token = get_internal_session_token("My iBox Client")
    """
    if isinstance(client_doc, str):
        client_name = client_doc
    else:
        client_name = client_doc.name

    internal_client = IBoxInternalClient(client_name)
    return internal_client._get_token()
