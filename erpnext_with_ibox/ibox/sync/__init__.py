# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sync module — iBox va ERPNext o'rtasidagi sinxronizatsiya.

MASTER_SYNC_ORDER — asosiy ma'lumotlar sinxronizatsiyasining to'g'ri ketma-ketligi:
  1. warehouses  — omborlar (stok uchun asos)
  2. suppliers   — taminotchilar (xarid uchun asos)
  3. customers   — mijozlar (sotuv uchun asos)
  4. items       — mahsulotlar (tranzaksiyalar uchun asos)
Purchases alohida (faqat master data to'liq bo'lgandan keyin ishga tushiriladi).
"""

from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler
from erpnext_with_ibox.ibox.sync.customers import CustomerSyncHandler
from erpnext_with_ibox.ibox.sync.exchange_rates import ExchangeRateSyncHandler
from erpnext_with_ibox.ibox.sync.items import ItemSyncHandler
from erpnext_with_ibox.ibox.sync.suppliers import SupplierSyncHandler
from erpnext_with_ibox.ibox.sync.warehouses import WarehouseSyncHandler
from erpnext_with_ibox.ibox.sync.purchases import PurchaseSyncHandler
from erpnext_with_ibox.ibox.sync.payments import PaymentSyncHandler
from erpnext_with_ibox.ibox.sync.payments_made import PaymentMadeSyncHandler
from erpnext_with_ibox.ibox.sync.payment_transfers import PaymentTransferSyncHandler
from erpnext_with_ibox.ibox.sync.sales import SalesSyncHandler
from erpnext_with_ibox.ibox.sync.stock_adjustments import StockAdjustmentSyncHandler
from erpnext_with_ibox.ibox.sync.transfers import TransferSyncHandler
from erpnext_with_ibox.ibox.sync.salaries import SalarySyncHandler
from erpnext_with_ibox.ibox.sync.currency_exchanges import CurrencyExchangeSyncHandler
from erpnext_with_ibox.ibox.sync.runner import sync_all_clients, sync_client


class PurchasesOnlyHandler(PurchaseSyncHandler):
    """Faqat xaridlarni yuklaydi (vozvratlar yuklanmaydi)."""
    NAME = "Purchases (Xaridlar)"
    def fetch_data(self):
        yield from self.api.purchases.get_all_purchases()


class ReturnsOnlyHandler(PurchaseSyncHandler):
    """Faqat vozvratlarni yuklaydi (xaridlar yuklanmaydi)."""
    NAME = "Returns (Vozvratlar)"
    def fetch_data(self):
        yield from self.api.purchases.get_all_returns()


# Handler registry — barcha mavjud handlerlar
SYNC_HANDLERS = {
    "warehouses":       WarehouseSyncHandler,
    "suppliers":        SupplierSyncHandler,
    "customers":        CustomerSyncHandler,
    "items":            ItemSyncHandler,
    "purchases":        PurchaseSyncHandler,        # xarid + vozvrat (ikkalasi)
    "purchases_only":   PurchasesOnlyHandler,       # faqat xarid
    "returns_only":     ReturnsOnlyHandler,          # faqat vozvrat
    "exchange_rates":   ExchangeRateSyncHandler,     # valyuta kurslari
    "payments":            PaymentSyncHandler,              # to'lovlar (kiruvchi)
    "sales":               SalesSyncHandler,                # sotuvlar (otgruzki)
    "payments_made":       PaymentMadeSyncHandler,          # chiquvchi to'lovlar
    "payment_transfers":   PaymentTransferSyncHandler,     # ichki pul ko'chirishlar
    "stock_adjustments":   StockAdjustmentSyncHandler,     # inventarizatsiya
    "transfers":           TransferSyncHandler,            # omborlar arasi ko'chirish
    "salaries":            SalarySyncHandler,              # oylik maoshlar
    "currency_exchanges":  CurrencyExchangeSyncHandler,    # valyuta ayirboshlash
}

# Master sync ketma-ketligi — "Sync Now" uchun majburiy tartib.
# Purchases FAQAT master data (warehouses, suppliers, customers, items)
# to'liq importdan keyin triggerlanadi.
MASTER_SYNC_ORDER = ["warehouses", "suppliers", "customers", "items"]

__all__ = [
    "BaseSyncHandler",
    "CustomerSyncHandler",
    "ExchangeRateSyncHandler",
    "ItemSyncHandler",
    "SupplierSyncHandler",
    "WarehouseSyncHandler",
    "PurchaseSyncHandler",
    "SalesSyncHandler",
    "PurchasesOnlyHandler",
    "ReturnsOnlyHandler",
    "PaymentSyncHandler",
    "PaymentMadeSyncHandler",
    "PaymentTransferSyncHandler",
    "StockAdjustmentSyncHandler",
    "TransferSyncHandler",
    "SalarySyncHandler",
    "CurrencyExchangeSyncHandler",
    "SYNC_HANDLERS",
    "MASTER_SYNC_ORDER",
    "sync_all_clients",
    "sync_client",
]
