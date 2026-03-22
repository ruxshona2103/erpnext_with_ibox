import time
from typing import Generator

import frappe
from frappe.utils import flt

from erpnext_with_ibox.ibox.config import SLUG_PAYMENT_TRANSFERS
from erpnext_with_ibox.ibox.sync.base import BaseSyncHandler


class PaymentTransferSyncHandler(BaseSyncHandler):
    DOCTYPE = "Payment Entry"
    NAME = "Payment Transfers (Ichki Pul Ko'chirishlar)"
    IBOX_ID_FIELD = "custom_ibox_payment_id"

    def fetch_data(self) -> Generator[dict, None, None]:
        """
        iBox API dan pul ko'chirishlarni yield qilish.
        page_size va max_pages iBox Client sozlamalaridan olinadi.
        """
        per_page = self.page_size or 100
        max_pages = self.max_pages or 0  # 0 = cheksiz

        page = 1
        while True:
            if max_pages and page > max_pages:
                break

            response = self.api.request(
                method="GET",
                endpoint=SLUG_PAYMENT_TRANSFERS,
                params={"page": page, "per_page": per_page}
            )
            records = response.get("data", [])

            if page == 1:
                total = int(flt(response.get("total", 0)))
                self.ibox_total = min(total, max_pages * per_page) if max_pages else total

            if not records:
                break

            for record in records:
                yield record

            if len(records) < per_page:
                break

            time.sleep(1)
            page += 1

    def upsert(self, record: dict) -> bool:
        transfer_id = str(record.get("id"))
        posting_date = (record.get("date") or "").split("T")[0] or frappe.utils.today()
        company = self.client_doc.company
        company_currency = frappe.db.get_value("Company", company, "default_currency") or "USD"
        transfer_currency = record.get("currency_code") or company_currency
        paid_amount = flt(record.get("total", 0), 2)

        if not transfer_id or not paid_amount:
            return False

        if frappe.db.get_value("Payment Entry", {"custom_ibox_payment_detail_id": transfer_id}, "name"):
            return False

        from_cashbox_id = str(record.get("from_cashbox_id") or "")
        to_cashbox_id = str(record.get("to_cashbox_id") or "")

        from_mode_of_payment = self._get_mode_of_payment(
            from_cashbox_id,
            transfer_currency,
            record.get("from_cashbox_name")
        )
        to_mode_of_payment = self._get_mode_of_payment(
            to_cashbox_id,
            transfer_currency,
            record.get("to_cashbox_name")
        )

        if not from_mode_of_payment or not to_mode_of_payment:
            self._log_config_error(
                transfer_id,
                f"Cashbox mapping topilmadi. from_cashbox_id={from_cashbox_id}, to_cashbox_id={to_cashbox_id}"
            )
            return False

        paid_from = self._get_cashbox_account(from_mode_of_payment, transfer_currency)
        paid_to = self._get_cashbox_account(to_mode_of_payment, transfer_currency)

        if not paid_from or not paid_to:
            self._log_config_error(
                transfer_id,
                (
                    f"Mode of Payment account topilmadi. "
                    f"from_mode_of_payment={from_mode_of_payment}, to_mode_of_payment={to_mode_of_payment}"
                )
            )
            return False

        if paid_from == paid_to:
            self._log_config_error(
                transfer_id,
                f"paid_from va paid_to bir xil accountga tushib qoldi: {paid_from}."
            )
            return False

        paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency") or company_currency
        paid_to_currency = frappe.db.get_value("Account", paid_to, "account_currency") or company_currency

        if transfer_currency and transfer_currency != paid_from_currency:
            self._log_config_error(
                transfer_id,
                (
                    f"Transfer currency ({transfer_currency}) source account currency bilan mos emas: "
                    f"{paid_from_currency}. from_cashbox_id={from_cashbox_id}, account={paid_from}"
                )
            )
            return False

        if transfer_currency and transfer_currency != paid_to_currency:
            self._log_config_error(
                transfer_id,
                (
                    f"Transfer currency ({transfer_currency}) target account currency bilan mos emas: "
                    f"{paid_to_currency}. to_cashbox_id={to_cashbox_id}, account={paid_to}"
                )
            )
            return False

        source_exchange_rate = self._get_exchange_rate(paid_from_currency, company_currency, posting_date)
        target_exchange_rate = self._get_exchange_rate(paid_to_currency, company_currency, posting_date)
        received_amount = flt(
            paid_amount if source_exchange_rate == target_exchange_rate else paid_amount * source_exchange_rate / target_exchange_rate,
            2,
        )

        try:
            doc = frappe.get_doc({
                "doctype": "Payment Entry",
                "payment_type": "Internal Transfer",
                "company": company,
                "posting_date": posting_date,
                "mode_of_payment": from_mode_of_payment,
                "paid_from": paid_from,
                "paid_to": paid_to,
                "paid_from_account_currency": paid_from_currency,
                "paid_to_account_currency": paid_to_currency,
                "paid_amount": paid_amount,
                "received_amount": received_amount,
                "source_exchange_rate": source_exchange_rate,
                "target_exchange_rate": target_exchange_rate,
                "reference_no": record.get("number") or transfer_id,
                "reference_date": posting_date,
                "remarks": (
                    f"iBox transfer #{record.get('number') or transfer_id}: "
                    f"{record.get('from_cashbox_name') or from_cashbox_id} -> "
                    f"{record.get('to_cashbox_name') or to_cashbox_id}"
                ),
                "custom_ibox_client": self.client_name,
                "custom_ibox_payment_id": transfer_id,
                "custom_ibox_payment_detail_id": transfer_id,
            })
            doc.set_missing_values()
            doc.insert(ignore_permissions=True)
            return True
        except Exception:
            frappe.log_error(
                title=f"Payment Transfer Upsert Error - {self.client_name}",
                message=f"transfer_id={transfer_id}\n{frappe.get_traceback()}"
            )
            return False

    def _get_mode_of_payment(
        self,
        cashbox_id: str,
        currency: str | None = None,
        fallback_cashbox_name: str | None = None,
    ) -> str:
        fallback_mode_of_payment = None
        cashbox_name = fallback_cashbox_name

        for row in self.client_doc.get("cashboxes", []):
            if str(row.cashbox_id) == str(cashbox_id):
                fallback_mode_of_payment = row.mode_of_payment
                cashbox_name = row.cashbox_name or fallback_cashbox_name
                break

        if not fallback_mode_of_payment:
            return ""

        if not currency:
            return fallback_mode_of_payment

        candidates = [self._replace_currency_suffix(fallback_mode_of_payment, currency)]

        if cashbox_name:
            candidates.append(f"iBox Kassa - {cashbox_name} ({currency})")
            candidates.append(self._build_currency_mode_of_payment(cashbox_name, currency))

        candidates.append(fallback_mode_of_payment)

        for mop in candidates:
            if mop and frappe.db.exists("Mode of Payment", mop):
                return mop

        return fallback_mode_of_payment

    def _build_currency_mode_of_payment(self, cashbox_name: str, currency: str) -> str:
        return f"iBox - {cashbox_name} ({currency})"

    @staticmethod
    def _replace_currency_suffix(mode_of_payment: str, currency: str) -> str:
        if not mode_of_payment:
            return mode_of_payment

        if " (" in mode_of_payment and mode_of_payment.endswith(")"):
            base = mode_of_payment.rsplit(" (", 1)[0]
            return f"{base} ({currency})"

        return mode_of_payment

    def _get_cashbox_account(self, mode_of_payment: str, currency: str | None = None) -> str:
        company = self.client_doc.company

        mop_account = frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": mode_of_payment, "company": company},
            "default_account"
        )
        if mop_account:
            if not currency:
                return mop_account

            acc_currency = frappe.db.get_value("Account", mop_account, "account_currency")
            if not acc_currency or acc_currency == currency:
                return mop_account

            currency_cash = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_type": "Cash",
                    "is_group": 0,
                    "account_currency": currency,
                },
                "name",
            )
            if currency_cash:
                return currency_cash
            return mop_account

        if currency:
            currency_cash = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_type": "Cash",
                    "is_group": 0,
                    "account_currency": currency,
                },
                "name",
            )
            if currency_cash:
                return currency_cash

        return ""

    def _get_exchange_rate(self, from_currency: str, company_currency: str, posting_date: str) -> float:
        if from_currency == company_currency:
            return 1.0

        exchange_rate = flt(
            frappe.db.get_value(
                "Currency Exchange",
                {
                    "from_currency": from_currency,
                    "to_currency": company_currency,
                },
                "exchange_rate"
            )
        )

        if exchange_rate > 1 and from_currency == "UZS" and company_currency in ["USD", "EUR", "RUB"]:
            exchange_rate = 1.0 / exchange_rate

        if exchange_rate:
            return exchange_rate

        reverse_rate = flt(
            frappe.db.get_value(
                "Currency Exchange",
                {
                    "from_currency": company_currency,
                    "to_currency": from_currency,
                },
                "exchange_rate"
            )
        )
        if reverse_rate:
            return 1.0 / reverse_rate

        return 1.0

    def _log_config_error(self, transfer_id: str, message: str) -> None:
        frappe.log_error(
            title=f"Payment Transfer Config Error - {self.client_name}",
            message=f"transfer_id={transfer_id}: {message}"
        )