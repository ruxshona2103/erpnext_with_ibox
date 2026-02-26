"""
iBox Integration Configuration — barcha constantlar uchun yagona manba.
"""

# -- API Endpoints --
DIRECTORY_ENDPOINT = "/api/integration/core/directory"

# -- Directory Slugs (DIRECTORY_ENDPOINT bilan ?data=<slug> sifatida ishlatiladi) --
SLUG_ITEMS = "product_product"
SLUG_CUSTOMERS = "outlet_client"

# -- Sync Tuning --
PAGE_SIZE = 1000           # Har bir API sahifadagi yozuvlar soni
BATCH_COMMIT_SIZE = 500    # frappe.db.commit() har N ta upsertdan keyin
PROGRESS_LOG_SIZE = 1000   # sync_status yangilash oralig'i

# -- Background Job Defaults --
SYNC_QUEUE = "long"
SYNC_TIMEOUT = 7200        # 2 soat har bir job uchun
