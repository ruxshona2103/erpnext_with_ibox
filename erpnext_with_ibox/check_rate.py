import frappe

def execute():
    comp = frappe.get_doc("Company", "Mycosmetic")
    print("Company Currency:", comp.default_currency)
    print("Accounts:")
    for acc in ["Oylik maosh - M", "USD Kassada Nakd Pllar - M"]:
        try:
            doc = frappe.get_doc("Account", acc)
            print("Account:", acc, "Currency:", doc.account_currency)
        except Exception:
            pass
