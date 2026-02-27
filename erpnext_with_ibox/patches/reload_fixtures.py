import frappe


def execute():
    frappe.reload_doc("ibox", "doctype", "ibox_client")
    frappe.reload_doctype("Custom Field")

    from frappe.utils.fixtures import sync_fixtures
    sync_fixtures(app="erpnext_with_ibox")
