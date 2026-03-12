import frappe


DEFAULT_PARENT_ACCOUNT = "1100 - Cash In Hand - I"
SUPPORTED_CURRENCIES = ("UZS", "USD")


def setup_cashbox_mode_of_payments(client_name: str = "Mycosmetic", company: str | None = None) -> dict:
    client_doc = frappe.get_doc("iBox Client", client_name)
    company = company or client_doc.company

    unique_cashboxes = {}
    for row in client_doc.get("cashboxes", []):
        cashbox_id = str(row.cashbox_id or "").strip()
        cashbox_name = (row.cashbox_name or "").strip()
        if not cashbox_id or not cashbox_name:
            continue
        unique_cashboxes.setdefault(cashbox_id, cashbox_name)

    created_modes = []
    created_accounts = []
    linked_accounts = []

    for cashbox_id, cashbox_name in unique_cashboxes.items():
        for currency in SUPPORTED_CURRENCIES:
            account_name = _ensure_account(company, cashbox_name, currency)
            mode_of_payment = _ensure_mode_of_payment(cashbox_name, currency)
            if _ensure_mode_of_payment_account(mode_of_payment, company, account_name):
                linked_accounts.append({
                    "mode_of_payment": mode_of_payment,
                    "account": account_name,
                })

            if frappe.flags.get("ibox_cashbox_account_created"):
                created_accounts.append(account_name)
                frappe.flags.ibox_cashbox_account_created = False

            if frappe.flags.get("ibox_cashbox_mop_created"):
                created_modes.append(mode_of_payment)
                frappe.flags.ibox_cashbox_mop_created = False

    frappe.db.commit()
    return {
        "client": client_name,
        "company": company,
        "cashboxes": len(unique_cashboxes),
        "created_modes": created_modes,
        "created_accounts": created_accounts,
        "linked_accounts": linked_accounts,
    }


def _ensure_account(company: str, cashbox_name: str, currency: str) -> str:
    account_name = _build_cashbox_account_name(cashbox_name, currency)
    existing_account = frappe.db.get_value(
        "Account",
        {"company": company, "account_name": account_name},
        "name"
    )
    if existing_account:
        return existing_account

    account = frappe.get_doc({
        "doctype": "Account",
        "account_name": account_name,
        "company": company,
        "parent_account": DEFAULT_PARENT_ACCOUNT,
        "root_type": "Asset",
        "report_type": "Balance Sheet",
        "account_type": "Cash",
        "account_currency": currency,
    })
    account.insert(ignore_permissions=True)
    frappe.flags.ibox_cashbox_account_created = True
    return account.name


def _ensure_mode_of_payment(cashbox_name: str, currency: str) -> str:
    mode_of_payment_name = _build_mode_of_payment_name(cashbox_name, currency)
    if frappe.db.exists("Mode of Payment", mode_of_payment_name):
        return mode_of_payment_name

    mode_of_payment = frappe.get_doc({
        "doctype": "Mode of Payment",
        "mode_of_payment": mode_of_payment_name,
        "type": "Cash",
        "enabled": 1,
    })
    mode_of_payment.insert(ignore_permissions=True)
    frappe.flags.ibox_cashbox_mop_created = True
    return mode_of_payment.name


def _ensure_mode_of_payment_account(mode_of_payment: str, company: str, account_name: str) -> bool:
    if frappe.db.exists(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company, "default_account": account_name}
    ):
        return False

    mode_of_payment_doc = frappe.get_doc("Mode of Payment", mode_of_payment)
    for row in mode_of_payment_doc.get("accounts", []):
        if row.company == company:
            row.default_account = account_name
            mode_of_payment_doc.save(ignore_permissions=True)
            return True

    mode_of_payment_doc.append("accounts", {
        "company": company,
        "default_account": account_name,
    })
    mode_of_payment_doc.save(ignore_permissions=True)
    return True


def _build_mode_of_payment_name(cashbox_name: str, currency: str) -> str:
    return f"iBox - {cashbox_name} ({currency})"


def _build_cashbox_account_name(cashbox_name: str, currency: str) -> str:
    return f"iBox - {cashbox_name} ({currency})"