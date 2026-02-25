# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
iBox Integration API — Yagona Manba (Single Source of Truth).
Industrial-grade background sync: frappe.enqueue, pagination (per_page=1000),
batch commits every 500 records, real-time progress tracking.

Verified API slugs:
  - Mahsulotlar: "product_product"
  - Mijozlar:    "outlet_client"
"""

import re
import traceback

import frappe
import requests
from frappe.utils import now


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

DIRECTORY_ENDPOINT = "/api/integration/core/directory"

SLUG_ITEMS     = "product_product"   # Verified
SLUG_CUSTOMERS = "outlet_client"     # Verified

BATCH_COMMIT_SIZE    = 500    # commit() har N ta recorddan keyin
PROGRESS_LOG_SIZE    = 1000   # sync_status yangilash oralig'i
PAGE_SIZE            = 1000   # har bir sahifadagi yozuvlar soni


# ─────────────────────────────────────────────
# INTERNAL: HTTP Helper
# ─────────────────────────────────────────────

def _make_request(client_doc, data_slug: str, page: int = 1, per_page: int = PAGE_SIZE) -> dict:
    """
    iBox API ga HTTP GET so'rov yuborish.

    Args:
        client_doc: iBox Client frappe document
        data_slug:  API directory turi ("product_product", "outlet_client")
        page:       Sahifa raqami (1-indexed)
        per_page:   Sahifadagi yozuvlar soni

    Returns:
        API javobini dict shaklida qaytaradi
    """
    base_url  = client_doc.api_base_url.rstrip("/")
    token     = client_doc.get_password("bearer_token")
    filial_id = client_doc.filial_id or 1

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
        "Filial-Id":     str(filial_id),
    }

    params = {
        "data":     data_slug,
        "page":     page,
        "per_page": per_page,
    }

    try:
        response = requests.get(
            f"{base_url}{DIRECTORY_ENDPOINT}",
            headers=headers,
            params=params,
            timeout=60,
            verify=False,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        frappe.log_error(
            title=f"iBox API Error — {client_doc.name}",
            message=f"slug={data_slug}, page={page}\n\n{traceback.format_exc()}",
        )
        raise


# ─────────────────────────────────────────────
# INTERNAL: String Helpers
# ─────────────────────────────────────────────

def _clean(value, default: str = "") -> str:
    """None va boshqa turlarni xavfsiz stringga aylantirish."""
    if value is None:
        return default
    return str(value).strip() or default


def _sanitize(text: str) -> str:
    """Frappe item_code uchun noqonuniy belgilarni olib tashlash."""
    return re.sub(r"[^A-Za-z0-9\u0400-\u04FF\s.\-]", "", text).strip()


# ─────────────────────────────────────────────
# WHITELISTED: Test Connection
# ─────────────────────────────────────────────

@frappe.whitelist()
def test_connection(client_name: str) -> dict:
    """iBox API ulanishni tekshirish."""
    try:
        client_doc = frappe.get_doc("iBox Client", client_name)
        result = _make_request(client_doc, SLUG_CUSTOMERS, page=1, per_page=1)
        total = result.get("total", len(result.get("data", [])))
        return {
            "success": True,
            "message": f"Ulanish muvaffaqiyatli! Bazada {total} ta mijoz topildi.",
        }
    except Exception as e:
        frappe.log_error(title=f"iBox Test Connection — {client_name}", message=traceback.format_exc())
        return {"success": False, "message": f"Xatolik: {str(e)[:200]}"}


# ─────────────────────────────────────────────
# WHITELISTED: Sync Triggers (non-blocking)
# ─────────────────────────────────────────────

@frappe.whitelist()
def sync_customers(client_name: str) -> dict:
    """
    Mijozlarni sinxronlashtirish — background job sifatida ishga tushirish.
    UI bloklanmaydi. Jarayon 'Sync Status' maydonida ko'rinadi.
    """
    _set_status(client_name, "Mijozlar sinxronizatsiyasi navbatga qo'yildi...")

    frappe.enqueue(
        "erpnext_with_ibox.ibox.api.run_sync_job",
        queue="long",
        timeout=7200,
        job_id=f"ibox_sync_customers_{client_name}",
        client_name=client_name,
        data_slug=SLUG_CUSTOMERS,
        doctype="Customer",
    )

    return {
        "success": True,
        "message": "Sinxronizatsiya orqa fonda boshlandi. Holatni 'Sync Status' maydonida kuzatishingiz mumkin.",
    }


@frappe.whitelist()
def sync_items(client_name: str) -> dict:
    """
    Mahsulotlarni sinxronlashtirish — background job sifatida ishga tushirish.
    UI bloklanmaydi. Jarayon 'Sync Status' maydonida ko'rinadi.
    """
    _set_status(client_name, "Mahsulotlar sinxronizatsiyasi navbatga qo'yildi...")

    frappe.enqueue(
        "erpnext_with_ibox.ibox.api.run_sync_job",
        queue="long",
        timeout=7200,
        job_id=f"ibox_sync_items_{client_name}",
        client_name=client_name,
        data_slug=SLUG_ITEMS,
        doctype="Item",
    )

    return {
        "success": True,
        "message": "Sinxronizatsiya orqa fonda boshlandi. Holatni 'Sync Status' maydonida kuzatishingiz mumkin.",
    }


# ─────────────────────────────────────────────
# BACKGROUND: Core Sync Job
# ─────────────────────────────────────────────

def run_sync_job(client_name: str, data_slug: str, doctype: str):
    """
    Barcha sahifalarni ketma-ket o'qib upsert qilish.
    frappe.enqueue orqali background da ishga tushiriladi.

    Pagination: per_page=1000
    Batch commit: har 500 ta recorddan keyin
    Progress: har 1000 ta recorddan keyin sync_status yangilanadi
    """
    upsert_fn = _upsert_item if doctype == "Item" else _upsert_customer
    client_doc = frappe.get_doc("iBox Client", client_name)

    page        = 1
    total_pages = None   # Birinchi javobdan aniqlanadi
    processed   = 0
    synced      = 0
    batch_count = 0      # Har 500 ta yozuvdan keyin commit

    _set_status(client_name, f"{doctype} sinxronlash boshlandi...")

    while True:
        try:
            result = _make_request(client_doc, data_slug, page=page, per_page=PAGE_SIZE)
        except Exception:
            frappe.log_error(
                title=f"run_sync_job API Error — {client_name}",
                message=f"slug={data_slug}, page={page}\n{traceback.format_exc()}",
            )
            page += 1
            if page > (total_pages or 500):
                break
            continue

        records = result.get("data", [])

        # Total sahifalar soni birinchi javobda aniqlanadi
        if total_pages is None:
            total     = result.get("total", 0)
            last_page = result.get("last_page")
            total_pages = last_page or (max(1, -(-total // PAGE_SIZE)))  # Ceiling division

        if not records:
            break

        # ── Har bir recordni upsert qilish ──
        for record in records:
            try:
                if upsert_fn(record, client_name):
                    synced += 1
                processed += 1
                batch_count += 1

                # Batch commit — har 500 ta yozuvdan keyin
                if batch_count >= BATCH_COMMIT_SIZE:
                    frappe.db.commit()
                    batch_count = 0

                # Progress yangilash — har 1000 ta yozuvdan keyin
                if processed % PROGRESS_LOG_SIZE == 0:
                    _set_status(
                        client_name,
                        f"Syncing {doctype}: {processed} ta qayta ishlandi, "
                        f"{synced} ta yangilandi (sahifa {page}/{total_pages})",
                    )
                    frappe.db.commit()

            except Exception:
                frappe.log_error(
                    title=f"{doctype} Upsert Error — {client_name}",
                    message=f"id={record.get('id')}\n{traceback.format_exc()}",
                )

        # Sahifa oxirida commit
        frappe.db.commit()
        batch_count = 0

        # Oxirgi sahifaga yetdikmi?
        if page >= total_pages or len(records) < PAGE_SIZE:
            break

        page += 1

    # ── Yakuniy holat ──
    frappe.db.set_value("iBox Client", client_name, {
        "sync_status":        f"Tayyor ({doctype}): {synced} ta yangilandi, jami {processed} ta",
        "last_sync_datetime": now(),
    }, update_modified=False)
    frappe.db.commit()

    frappe.logger().info(
        f"iBox Sync Complete [{client_name}] {doctype}: "
        f"{synced} synced / {processed} processed"
    )


# ─────────────────────────────────────────────
# SCHEDULED: Nightly Full Sync (hooks.py → 03:00)
# ─────────────────────────────────────────────

def scheduled_sync_all_clients():
    """
    Barcha faol iBox Client lar uchun to'liq sinxronlashtirish.
    hooks.py → scheduler_events → cron "0 3 * * *"
    """
    clients = frappe.get_all("iBox Client", filters={"enabled": 1}, pluck="name")
    for client_name in clients:
        try:
            frappe.enqueue(
                "erpnext_with_ibox.ibox.api.run_sync_job",
                queue="long",
                timeout=7200,
                job_id=f"ibox_nightly_customers_{client_name}",
                client_name=client_name,
                data_slug=SLUG_CUSTOMERS,
                doctype="Customer",
            )
            frappe.enqueue(
                "erpnext_with_ibox.ibox.api.run_sync_job",
                queue="long",
                timeout=7200,
                job_id=f"ibox_nightly_items_{client_name}",
                client_name=client_name,
                data_slug=SLUG_ITEMS,
                doctype="Item",
            )
        except Exception:
            frappe.log_error(
                title=f"Scheduled Sync Enqueue Error — {client_name}",
                message=traceback.format_exc(),
            )


# ─────────────────────────────────────────────
# INTERNAL: Status Helper
# ─────────────────────────────────────────────

def _set_status(client_name: str, status: str):
    """iBox Client hujjatidagi sync_status maydonini yangilash."""
    try:
        frappe.db.set_value(
            "iBox Client", client_name, "sync_status", status,
            update_modified=False,
        )
        frappe.db.commit()
    except Exception:
        pass  # Status yangilash muvaffaqiyatsiz bo'lsa, asosiy jarayon to'xtamasin


# ─────────────────────────────────────────────
# UPSERT: Item
# ─────────────────────────────────────────────

def _upsert_item(record: dict, client_name: str) -> bool:
    """Bitta mahsulotni upsert qilish. True = o'zgarish bo'lgan."""
    ibox_id   = record.get("id")
    item_name = _clean(record.get("name"), "Noma'lum mahsulot")
    item_code = _sanitize(item_name)[:140] or f"IBOX-{ibox_id}"

    item_group = (
        "Products"
        if frappe.db.exists("Item Group", "Products")
        else "All Item Groups"
    )

    existing = frappe.db.get_value(
        "Item",
        {"custom_ibox_id": ibox_id, "custom_ibox_client": client_name},
        "name",
    )

    if existing:
        changed = False
        if frappe.db.get_value("Item", existing, "item_name") != item_name:
            frappe.db.set_value("Item", existing, {
                "item_name": item_name,
                "item_code": item_code,
            })
            changed = True
        return changed

    frappe.get_doc({
        "doctype":            "Item",
        "item_code":          item_code,
        "item_name":          item_name,
        "item_group":         item_group,
        "stock_uom":          "Nos",
        "is_stock_item":      1,
        "is_sales_item":      1,
        "is_purchase_item":   1,
        "custom_ibox_id":     ibox_id,
        "custom_ibox_client": client_name,
    }).insert(ignore_permissions=True)
    return True


# ─────────────────────────────────────────────
# UPSERT: Customer
# ─────────────────────────────────────────────

def _upsert_customer(record: dict, client_name: str) -> bool:
    """Bitta mijozni upsert qilish. True = o'zgarish bo'lgan."""
    ibox_id = record.get("id")
    name    = _clean(record.get("name"), "Noma'lum mijoz")
    phone   = _clean(record.get("main_phone"))

    existing = frappe.db.get_value(
        "Customer",
        {"custom_ibox_id": ibox_id, "custom_ibox_client": client_name},
        "name",
    )

    if existing:
        changed = False
        if frappe.db.get_value("Customer", existing, "customer_name") != name:
            frappe.db.set_value("Customer", existing, "customer_name", name)
            changed = True
        if phone and frappe.db.get_value("Customer", existing, "custom_main_phone") != phone:
            frappe.db.set_value("Customer", existing, "custom_main_phone", phone)
            changed = True
        return changed

    frappe.get_doc({
        "doctype":            "Customer",
        "customer_name":      name,
        "customer_type":      "Individual",
        "customer_group":     "All Customer Groups",
        "territory":          "All Territories",
        "custom_ibox_id":     ibox_id,
        "custom_ibox_client": client_name,
        "custom_main_phone":  phone,
    }).insert(ignore_permissions=True)
    return True
