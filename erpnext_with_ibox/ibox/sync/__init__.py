# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sync module — iBox va ERPNext o'rtasidagi sinxronizatsiya.
"""

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler
from erpnext_with_ibox.ibox.sync.customers import CustomerSyncHandler
from erpnext_with_ibox.ibox.sync.items import ItemSyncHandler
from erpnext_with_ibox.ibox.sync.suppliers import SupplierSyncHandler
from erpnext_with_ibox.ibox.sync.runner import sync_all_clients, sync_client

SYNC_HANDLERS = {
    "customers": CustomerSyncHandler,
    "items": ItemSyncHandler,
    "suppliers": SupplierSyncHandler,
}

__all__ = [
    "BaseSyncHandler",
    "CustomerSyncHandler",
    "ItemSyncHandler",
    "SupplierSyncHandler",
    "SYNC_HANDLERS",
    "sync_all_clients",
    "sync_client",
]
