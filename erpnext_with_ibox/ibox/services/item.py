# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Item Service - handles item lookup and creation
"""

import frappe


class ItemService:
    """Service for managing items from iBox data"""
    
    # UOM mapping from iBox to ERPNext
    UOM_MAP = {
        "шт": "Nos",
        "шт.": "Nos", 
        "кг": "Kg",
        "л": "Ltr"
    }
    
    @staticmethod
    def get_or_create(product: dict, company: str) -> str:
        """
        Find existing item or create new one
        
        Args:
            product: Product dict from iBox with keys: id, name, storage_unit
            company: Company name for the item
            
        Returns:
            Item code (document name)
        """
        product_name = product.get("name", "Unknown Item")
        product_id = product.get("id")
        
        # First try to find by ibox_product_id
        existing = frappe.db.get_value(
            "Item", 
            {"custom_ibox_product_id": product_id}, 
            "name"
        )
        if existing:
            return existing
        
        # Try by item_code (product name)
        if frappe.db.exists("Item", product_name):
            return product_name
        
        # Create new item
        uom = product.get("storage_unit", {}).get("short_name", "шт")
        erp_uom = ItemService.UOM_MAP.get(uom, "Nos")
        
        item = frappe.new_doc("Item")
        item.item_code = product_name
        item.item_name = product_name
        item.item_group = "Products"
        item.stock_uom = erp_uom
        item.is_stock_item = 1
        item.custom_ibox_product_id = product_id
        item.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return item.name
