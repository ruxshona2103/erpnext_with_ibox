# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Customer Service - handles customer lookup and creation
"""

import frappe


class CustomerService:
    """Service for managing customers from iBox data"""
    
    @staticmethod
    def get_or_create(customer_name: str) -> str:
        """
        Find existing customer or create new one
        
        Args:
            customer_name: Name of the customer (outlet_name from iBox)
            
        Returns:
            Customer document name
        """
        if not customer_name:
            customer_name = "Unknown Customer"
        
        # Check if exists
        if frappe.db.exists("Customer", customer_name):
            return customer_name
        
        # Create new customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Company"
        customer.customer_group = (
            frappe.db.get_single_value("Selling Settings", "customer_group") 
            or "All Customer Groups"
        )
        customer.territory = (
            frappe.db.get_single_value("Selling Settings", "territory") 
            or "All Territories"
        )
        customer.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return customer.name
