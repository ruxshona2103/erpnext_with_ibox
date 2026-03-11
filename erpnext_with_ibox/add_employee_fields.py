import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
    custom_fields = {
        "Employee": [
            {
                "fieldname": "custom_ibox_client",
                "label": "iBox Client",
                "fieldtype": "Link",
                "options": "iBox Client",
                "insert_after": "employee_name"
            },
            {
                "fieldname": "custom_ibox_id",
                "label": "iBox ID",
                "fieldtype": "Data",
                "insert_after": "custom_ibox_client"
            }
        ]
    }
    create_custom_fields(custom_fields)
    frappe.db.commit()
    print("Employee custom fields created successfully.")

