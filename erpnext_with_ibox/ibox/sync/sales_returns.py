# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sales Return Sync Handler — iBox return/list -> ERPNext Sales Invoice (Credit Note).

Sotuv vozvrati (return) → Sales Invoice / Credit Note (is_return=1, docstatus=0)

Audit qilingan farqlar:
  - Shipment endpoint detail key: shipment_details
  - Return endpoint detail key:   purchase_details

Qoidalar:
  - is_return = 1
  - update_stock = 1
  - qty har doim manfiy
  - custom_ibox_sales_id = ibox root id
  - debit_to va income_account iBox currency_code asosida overwrite qilinadi
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.config import SALES_RETURN_PAGE_SIZE
from erpnext_with_ibox.ibox.sync.sales import SalesSyncHandler


class SalesReturnSyncHandler(SalesSyncHandler):
    DOCTYPE = "Sales Invoice"
    NAME = "Sotuv Vozvratlari"
    ERP_FILTERS = {"is_return": 1}
    RETURN_LIMIT = SALES_RETURN_PAGE_SIZE

    def fetch_data(self):
        """iBox API dan sales return recordlarni page-by-page + period filter bilan olish."""
        per_page = min(int(self.page_size or self.RETURN_LIMIT or 100), 100)
        max_pages = int(self.max_pages or 0)
        period_from = f"{self.sync_from_date} 00:00:00" if self.sync_from_date else None
        period_to = f"{self.sync_to_date} 00:00:00" if self.sync_to_date else None

        page = 1
        pulled_pages = 0
        total_pages = None

        while True:
            response = self.api.sales_returns.get_page(
                page=page,
                per_page=per_page,
                period_from=period_from,
                period_to=period_to,
            )
            self._api_response_status = 200

            records = response.get("data", []) or []

            if page == 1:
                total = int(response.get("total") or 0)
                self.ibox_total = total

                last_page = response.get("last_page")
                if last_page:
                    total_pages = int(last_page)
                elif total > 0:
                    total_pages = max(1, -(-total // per_page))

            if not records:
                break

            for record in records:
                yield record

            pulled_pages += 1

            if max_pages and pulled_pages >= max_pages:
                break
            if total_pages and page >= total_pages:
                break
            if len(records) < per_page:
                break

            page += 1

    def upsert(self, record: dict) -> bool:
        """Bitta sales return recordni Credit Note sifatida yaratish."""
        ibox_id = record.get("id")

        existing = frappe.db.get_value(
            "Sales Invoice",
            {
                "custom_ibox_sales_id": ibox_id,
                "custom_ibox_client": self.client_name,
            },
            ["name", "docstatus"],
            as_dict=True,
        )
        if existing:
            return False

        company = self.client_doc.company
        if not company:
            self._skip_log["missing_accounts"].append("company_missing")
            return False

        outlet_id = record.get("outlet_id")
        customer_name = self._resolve_customer(outlet_id)
        if not customer_name:
            if not record.get("_is_retry"):
                record["_is_retry"] = True
                self._retry_queue.append(record)
            else:
                self._skip_log["missing_customers"].append(outlet_id)
            return False

        header_warehouse_id = record.get("warehouse_id")
        details = record.get("purchase_details") or record.get("details") or []

        if not header_warehouse_id and details:
            for detail in details:
                warehouse_id = detail.get("warehouse_id")
                if warehouse_id:
                    header_warehouse_id = warehouse_id
                    break

        header_warehouse_name = self._resolve_warehouse(header_warehouse_id)
        if not header_warehouse_name:
            fallback = getattr(self.client_doc, "default_warehouse", None)
            if fallback:
                header_warehouse_name = fallback

        currency = "UZS"
        effective_conversion_rate = 1.0

        debit_to = getattr(self.client_doc, "uzs_receivable_account", None)
        if not debit_to:
            self._skip_log["missing_accounts"].append(f"uzs_receivable_account:{ibox_id}")
            return False

        acct_currency = frappe.db.get_value("Account", debit_to, "account_currency")
        if acct_currency and acct_currency != "UZS":
            self._skip_log["missing_accounts"].append(
                f"currency_mismatch:{ibox_id}:debit_to={debit_to}:{acct_currency}!=UZS"
            )
            return False

        income_account = getattr(self.client_doc, "uzs_sales_income", None)
        if not income_account:
            self._skip_log["missing_accounts"].append(f"uzs_sales_income:{ibox_id}")
            return False

        raw_date = record.get("date", "")
        posting_date = self._parse_date(raw_date)
        posting_time = self._parse_time(raw_date)
        effective_conversion_rate = 1.0

        ibox_total = self._parse_float(
            record.get("total") or record.get("amount") or record.get("sum")
        )

        items = []
        for detail in details:
            product_id = detail.get("product_id")
            item_code = self._resolve_item(product_id)
            if not item_code:
                self._skip_log["missing_items"].append(product_id)
                continue

            row_wh_id = detail.get("warehouse_id") or header_warehouse_id
            row_wh_name = self._resolve_warehouse(row_wh_id) or header_warehouse_name
            if not row_wh_name:
                self._skip_log["missing_warehouses"].append(row_wh_id)
                continue

            ibox_qty = self._parse_float(detail.get("quantity") or detail.get("qty"))
            final_qty = flt(ibox_qty) * -1
            rate = abs(self._parse_float(detail.get("price") or detail.get("rate")))

            uom = self._resolve_uom(item_code)
            self._ensure_uom_in_item(item_code, uom)
            item_name = self._resolve_item_name(item_code)

            items.append({
                "item_code": item_code,
                "item_name": item_name[:140],
                "warehouse": row_wh_name,
                "qty": final_qty,
                "rate": rate,
                "uom": uom,
                "stock_uom": uom,
                "stock_qty": final_qty,
                "conversion_factor": 1,
                "income_account": income_account,
                "allow_zero_valuation_rate": 1,
                "custom_ibox_detail_id": detail.get("id"),
                "custom_ibox_warehouse_id": row_wh_id,
            })

        if not items:
            if not record.get("_is_retry"):
                record["_is_retry"] = True
                self._retry_queue.append(record)
            return False

        si = frappe.new_doc("Sales Invoice")
        si.customer = customer_name
        si.company = company
        si.posting_date = posting_date
        si.posting_time = posting_time
        si.set_posting_time = 1
        si.is_return = 1
        si.update_stock = 1
        si.docstatus = 0
        si.custom_ibox_sales_id = ibox_id
        si.custom_ibox_client = self.client_name
        si.custom_ibox_total = ibox_total

        for item_row in items:
            si.append("items", item_row)

        with patch(
            "erpnext.controllers.accounts_controller.get_exchange_rate",
            return_value=effective_conversion_rate,
        ):
            si.set_missing_values()

        si.currency = "UZS"
        si.price_list_currency = currency
        si.selling_price_list = "Standard Selling"
        si.debit_to = debit_to
        si.conversion_rate = 1.0
        si.plc_conversion_rate = 1.0
        si.set_warehouse = header_warehouse_name
        si.taxes_and_charges = ""
        si.is_return = 1
        si.update_stock = 1

        for item in si.items:
            item.income_account = income_account

        si.calculate_taxes_and_totals()

        erp_grand = flt(getattr(si, "grand_total", 0))
        diff = flt(ibox_total) - erp_grand
        if diff:
            si.rounding_adjustment = diff
            si.rounded_total = flt(ibox_total)
            si.base_rounding_adjustment = diff
            si.base_rounded_total = flt(ibox_total)

        import time

        for attempt in range(2):
            try:
                with patch(
                    "erpnext.controllers.accounts_controller.get_exchange_rate",
                    return_value=effective_conversion_rate,
                ):
                    si.insert(ignore_permissions=True)
                return True
            except frappe.QueryDeadlockError:
                frappe.db.rollback()
                if attempt == 0:
                    time.sleep(2)
                    continue
                frappe.log_error(
                    title=f"Sales Return Sync - Deadlock - {self.client_name}",
                    message=f"ibox_sales_return_id={ibox_id}: 2 urinishdan keyin ham Deadlock.",
                )
                return False
            except Exception as e:
                frappe.log_error(
                    title=f"Sales Return Sync - Insert Failed - {self.client_name}",
                    message=(
                        f"ibox_sales_return_id: {ibox_id}\n"
                        f"Customer: {customer_name}\n"
                        f"Currency: {currency}\n"
                        f"is_return: 1\n"
                        f"Xato: {str(e)[:500]}\n\n"
                        f"{frappe.get_traceback()[-1000:]}"
                    ),
                )
                frappe.db.rollback()
                return False

        return False