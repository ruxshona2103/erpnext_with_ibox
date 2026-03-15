"""Har bir cashbox uchun 2ta Mode of Payment (UZS + USD) yaratish va eski 1ta MoP o'chirish."""
import frappe


def run():
    company = "Ibox"
    client_name = "Mycosmetic"

    cashboxes = frappe.get_all(
        "iBox Cashbox Mapping",
        filters={"parent": client_name},
        fields=["name", "cashbox_id", "cashbox_name", "uzs_account", "usd_account"],
    )

    print(f"Jami {len(cashboxes)} ta cashbox topildi\n")

    for cb in cashboxes:
        cb_name = cb.cashbox_name or f"Cashbox-{cb.cashbox_id}"
        safe_name = cb_name.replace("'", "").replace('"', '').strip()
        print(f"--- {safe_name} (ID: {cb.cashbox_id}) ---")

        uzs_acc = cb.uzs_account
        usd_acc = cb.usd_account

        # 1) UZS Mode of Payment
        uzs_mop_name = f"iBox Kassa - {safe_name} (UZS)"
        if not frappe.db.exists("Mode of Payment", uzs_mop_name):
            try:
                mop = frappe.get_doc({
                    "doctype": "Mode of Payment",
                    "mode_of_payment": uzs_mop_name,
                    "type": "Cash",
                    "accounts": [],
                })
                if uzs_acc:
                    mop.append("accounts", {
                        "company": company,
                        "default_account": uzs_acc,
                    })
                mop.insert(ignore_permissions=True)
                print(f"  UZS MoP yaratildi: {uzs_mop_name} -> {uzs_acc}")
            except Exception as e:
                print(f"  UZS MoP xato: {e}")
                uzs_mop_name = None
        else:
            print(f"  UZS MoP mavjud: {uzs_mop_name}")

        # 2) USD Mode of Payment
        usd_mop_name = f"iBox Kassa - {safe_name} (USD)"
        if not frappe.db.exists("Mode of Payment", usd_mop_name):
            try:
                mop = frappe.get_doc({
                    "doctype": "Mode of Payment",
                    "mode_of_payment": usd_mop_name,
                    "type": "Cash",
                    "accounts": [],
                })
                if usd_acc:
                    mop.append("accounts", {
                        "company": company,
                        "default_account": usd_acc,
                    })
                mop.insert(ignore_permissions=True)
                print(f"  USD MoP yaratildi: {usd_mop_name} -> {usd_acc}")
            except Exception as e:
                print(f"  USD MoP xato: {e}")
                usd_mop_name = None
        else:
            print(f"  USD MoP mavjud: {usd_mop_name}")

        # 3) Eski bitta MoP o'chirish (agar mavjud bo'lsa)
        old_mop_name = f"iBox Kassa - {safe_name}"
        if frappe.db.exists("Mode of Payment", old_mop_name):
            try:
                frappe.delete_doc("Mode of Payment", old_mop_name, ignore_permissions=True)
                print(f"  Eski MoP o'chirildi: {old_mop_name}")
            except Exception as e:
                print(f"  Eski MoP o'chirish xato: {e}")

        # 4) Cashbox mapping — mode_of_payment ga UZS variant (default)
        frappe.db.set_value("iBox Cashbox Mapping", cb.name, {
            "mode_of_payment": uzs_mop_name,
        })

    frappe.db.commit()
    print(f"\n=== Tayyor! {len(cashboxes)} ta cashbox x 2 MoP = {len(cashboxes) * 2} ta MoP yaratildi ===")


run()
