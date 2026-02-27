"""
iBox Integration Configuration — barcha constantlar uchun yagona manba.
"""

# -- API Endpoints --
DIRECTORY_ENDPOINT = "/api/integration/core/directory"

# -- Directory Slugs (DIRECTORY_ENDPOINT bilan ?data=<slug> sifatida ishlatiladi) --
SLUG_ITEMS = "product_product"
SLUG_CUSTOMERS = "outlet_client"

# -- Internal API Endpoints --
SUPPLIER_ENDPOINT = "/api/outlet/supplier"
LOGIN_ENDPOINT = "/api/user/login"

# -- Internal API Token --
INTERNAL_TOKEN_TTL = 18000  # 5 soat (sekundlarda)

# -- Sync Tuning --
PAGE_SIZE = 1000           # Har bir Directory API sahifadagi yozuvlar soni
INTERNAL_PAGE_SIZE = 100   # Internal API uchun (iBox max 100 qabul qiladi)
BATCH_COMMIT_SIZE = 500    # frappe.db.commit() har N ta upsertdan keyin
PROGRESS_LOG_SIZE = 1000   # sync_status yangilash oralig'i

# -- Background Job Defaults --
SYNC_QUEUE = "long"
SYNC_TIMEOUT = 7200        # 2 soat har bir job uchun
