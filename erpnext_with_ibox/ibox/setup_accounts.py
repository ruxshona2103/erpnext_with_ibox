"""UZS Receivable va UZS Income accountlar yaratish va iBox Client ga set qilish."""
import frappe


def run():
    company = "Ibox"
    client_name = "Mycosmetic"

    # 1) UZS Debtors (Receivable)
    uzs_debtors_name = "Debtors - UZS"
    uzs_debtors = frappe.db.get_value("Account", {"account_name": uzs_debtors_name, "company": company}, "name")
    if not uzs_debtors:
        acc = frappe.get_doc({
            "doctype": "Account",
            "account_name": uzs_debtors_name,
            "parent_account": "1300 - Accounts Receivable - I",
            "company": company,
            "account_type": "Receivable",
            "account_currency": "UZS",
            "is_group": 0,
        })
        acc.insert(ignore_permissions=True)
        uzs_debtors = acc.name
        print(f"Yaratildi: {uzs_debtors}")
    else:
        print(f"Mavjud: {uzs_debtors}")

    # 2) UZS Sales Income
    uzs_sales_name = "Sales - UZS"
    uzs_sales = frappe.db.get_value("Account", {"account_name": uzs_sales_name, "company": company}, "name")
    if not uzs_sales:
        acc = frappe.get_doc({
            "doctype": "Account",
            "account_name": uzs_sales_name,
            "parent_account": "4100 - Direct Income - I",
            "company": company,
            "account_type": "",
            "account_currency": "UZS",
            "is_group": 0,
        })
        acc.insert(ignore_permissions=True)
        uzs_sales = acc.name
        print(f"Yaratildi: {uzs_sales}")
    else:
        print(f"Mavjud: {uzs_sales}")

    # 3) iBox Client ga set qilish
    frappe.db.set_value("iBox Client", client_name, {
        "uzs_payable_account": "2111 - Creditors - UZS - I - I",
        "usd_payable_account": "2110 - Creditors - USD - I",
        "uzs_receivable_account": uzs_debtors,
        "usd_receivable_account": "1310 - Debtors - I",
        "uzs_sales_income": uzs_sales,
        "usd_sales_income": "4110 - Sales - I",
    })
    frappe.db.commit()

    print(f"\niBox Client '{client_name}' accountlar sozlandi:")
    print(f"  UZS Payable:    2111 - Creditors - UZS - I - I")
    print(f"  USD Payable:    2110 - Creditors - USD - I")
    print(f"  UZS Receivable: {uzs_debtors}")
    print(f"  USD Receivable: 1310 - Debtors - I")
    print(f"  UZS Income:     {uzs_sales}")
    print(f"  USD Income:     4110 - Sales - I")


run()
