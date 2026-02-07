# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Sync Runner - orchestrates sync operations for iBox clients
"""

import frappe
from frappe.utils import now

from erpnext_with_ibox.ibox.api import IBoxAPIClient


def sync_all_clients():
    """
    Sync all enabled iBox clients.
    Called by scheduled job (daily at 23:00).
    """
    clients = frappe.get_all(
        "iBox Client",
        filters={"enabled": 1},
        pluck="name"
    )
    
    for client_name in clients:
        try:
            sync_client(client_name)
        except Exception as e:
            frappe.log_error(
                title=f"iBox Sync Error - {client_name}",
                message=str(e)
            )


def sync_client(client_name: str, handlers: list = None):
    """
    Sync a single iBox client.
    
    Args:
        client_name: Name of iBox Client document
        handlers: List of handler names to run (default: all)
    """
    from erpnext_with_ibox.ibox.sync import SYNC_HANDLERS
    
    client_doc = frappe.get_doc("iBox Client", client_name)
    api = IBoxAPIClient(client_name)
    
    # Update status
    client_doc.sync_status = "Syncing..."
    client_doc.save(ignore_permissions=True)
    frappe.db.commit()
    
    try:
        # Determine which handlers to run
        if handlers is None:
            handlers = list(SYNC_HANDLERS.keys())
        
        results = {}
        
        for handler_name in handlers:
            handler_class = SYNC_HANDLERS.get(handler_name)
            if handler_class:
                handler = handler_class(api, client_doc)
                count = handler.run()
                results[handler_name] = count
        
        # Update success status
        client_doc.reload()
        client_doc.last_sync_datetime = now()
        
        # Format results
        result_str = ", ".join(f"{k}: {v}" for k, v in results.items())
        client_doc.sync_status = f"Success: {result_str}"
        client_doc.save(ignore_permissions=True)
        frappe.db.commit()
        
        return results
        
    except Exception as e:
        client_doc.reload()
        client_doc.sync_status = f"Error: {str(e)[:100]}"
        client_doc.save(ignore_permissions=True)
        frappe.db.commit()
        raise
