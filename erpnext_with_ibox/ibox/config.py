"""
iBox Integration Configuration — barcha constantlar uchun yagona manba.
"""

# -- API Endpoints --
DIRECTORY_ENDPOINT = "/api/integration/core/directory"

# -- Directory Slugs (DIRECTORY_ENDPOINT bilan ?data=<slug> sifatida ishlatiladi) --
SLUG_ITEMS = "product_product"
SLUG_CUSTOMERS = "outlet_client"
SLUG_WAREHOUSES = "core_warehouse"

# -- Document API Endpoints (Purchase / Return / Shipment) --
PURCHASE_ENDPOINT = "/api/integration/document/purchase/list"
PURCHASE_RETURN_ENDPOINT = "/api/integration/document/supplier-return/list"
PURCHASE_PAGE_SIZE = 100   # Xarid/vozvrat sahifada yozuvlar soni
SHIPMENT_ENDPOINT = "/api/integration/document/shipment/list"
SHIPMENT_PAGE_SIZE = 100   # Sotuv sahifada yozuvlar soni

# -- IBOX Endpoints (endpoint path dict) --
IBOX_ENDPOINTS = {
    "items": "/api/integration/core/directory",
}

# -- Directory Types (directory type slug dict) --
DIRECTORY_TYPES = {
    "items": "product_selection",
}

# -- Internal API Endpoints --
SUPPLIER_ENDPOINT = "/api/outlet/supplier"
LOGIN_ENDPOINT = "/api/user/login"
EXCHANGE_RATE_ENDPOINT = "/api/core/exchange-rate"
CASHBOX_ENDPOINT = "/api/finance/cashbox"

# -- Internal API Token --
INTERNAL_TOKEN_TTL = 18000  # 5 soat (sekundlarda)

# -- Sync Tuning --
PAGE_SIZE = 1000           # Har bir Directory API sahifadagi yozuvlar soni
INTERNAL_PAGE_SIZE = 100   # Internal API uchun (iBox max 100 qabul qiladi)
BATCH_COMMIT_SIZE = 50     # frappe.db.commit() har N ta upsertdan keyin
PROGRESS_LOG_SIZE = 1000   # sync_status yangilash oralig'i

# -- API Rate Limiting & Retry --
API_RETRY_COUNT = 5           # 429 xatoda necha marta qayta urinish
API_RETRY_BASE_DELAY = 30     # Birinchi retry oldidan kutish (sekundlarda)
API_RETRY_MAX_DELAY = 180     # Maksimal kutish vaqti (sekundlarda)
API_PAGE_DELAY = 2.0          # Har bir sahifa orasidagi pauza (sekundlarda)

# -- Orphan Cleanup (Mirror Sync) --
ORPHAN_CLEANUP_THRESHOLD = 0.15   # 15% — bu chegaradan oshsa cleanup ABORT (xavfsizlik)
ORPHAN_CLEANUP_ENABLED = True     # False qilsangiz cleanup ishlamaydi

# -- Background Job Defaults --
SYNC_QUEUE = "long"
SYNC_TIMEOUT = 10800       # 3 soat har bir job uchun

# -- Payment Sync --
SLUG_PAYMENTS = "/api/integration/document/payment-received/list"
SLUG_PAYMENTS_MADE = "/api/integration/document/payment-made/list"
SLUG_PAYMENT_TRANSFERS = "/api/integration/document/payment-transfer/list"

# -- New Document Endpoints --
STOCK_ADJUSTMENT_ENDPOINT = "/api/document/stock-adjustment"
TRANSFER_ENDPOINT = "/api/document/transfer"
SALARY_ENDPOINT = "/api/integration/document/salary/list"
CURRENCY_EXCHANGE_ENDPOINT = "/api/integration/document/currency-exchange/list"
