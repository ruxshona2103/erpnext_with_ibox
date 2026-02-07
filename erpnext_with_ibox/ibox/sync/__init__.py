# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sync module - handles synchronization between iBox and ERPNext
"""

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler
from erpnext_with_ibox.ibox.sync.orders import OrderSyncHandler
from erpnext_with_ibox.ibox.sync.runner import sync_all_clients, sync_client

# Registry of all sync handlers
SYNC_HANDLERS = {
    "orders": OrderSyncHandler,
    # Future handlers:
    # "payments": PaymentSyncHandler,
    # "purchases": PurchaseSyncHandler,
}

__all__ = [
    "BaseSyncHandler",
    "OrderSyncHandler", 
    "SYNC_HANDLERS",
    "sync_all_clients",
    "sync_client",
]
