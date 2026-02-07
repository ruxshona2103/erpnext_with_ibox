# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Warehouse Service - handles warehouse lookup and creation
"""

import frappe


class WarehouseService:
    """Service for managing warehouses from iBox data"""
    
    @staticmethod
    def get_or_create(warehouse_data: dict, company: str) -> str:
        """
        Find existing warehouse or create new one
        
        Args:
            warehouse_data: Warehouse dict from iBox with key: name
            company: Company name for the warehouse
            
        Returns:
            Warehouse document name
        """
        warehouse_name = warehouse_data.get("name", "Main Warehouse")
        company_abbr = frappe.db.get_value("Company", company, "abbr")
        full_name = f"{warehouse_name} - {company_abbr}"
        
        # Check by full name
        if frappe.db.exists("Warehouse", full_name):
            return full_name
        
        # Try without company abbr
        existing = frappe.db.get_value(
            "Warehouse", 
            {"warehouse_name": warehouse_name, "company": company}, 
            "name"
        )
        if existing:
            return existing
        
        # Get parent warehouse
        parent = frappe.db.get_value(
            "Warehouse", 
            {"is_group": 1, "company": company}, 
            "name"
        )
        
        # Create new warehouse
        warehouse = frappe.new_doc("Warehouse")
        warehouse.warehouse_name = warehouse_name
        warehouse.company = company
        warehouse.parent_warehouse = parent
        warehouse.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return warehouse.name
