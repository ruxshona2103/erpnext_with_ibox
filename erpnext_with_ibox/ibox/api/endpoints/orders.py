# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Orders API Endpoint - handles all order-related API calls
"""


class OrdersEndpoint:
    """Orders API endpoint handler"""
    
    ENDPOINT = "/api/integration/document/order/list"
    
    def __init__(self, client):
        self.client = client
    
    def get_list(self, page: int = 1, per_page: int = 100) -> dict:
        """
        Get paginated list of orders
        
        Args:
            page: Page number (1-indexed)
            per_page: Number of orders per page
            
        Returns:
            dict with keys: data, current_page, last_page, total, etc.
        """
        return self.client.request(
            method="GET",
            endpoint=self.ENDPOINT,
            params={"page": page, "per_page": per_page}
        )
    
    def get_all(self, per_page: int = 100):
        """
        Generator to fetch all orders across all pages
        
        Yields:
            dict: Individual order data
        """
        page = 1
        while True:
            response = self.get_list(page=page, per_page=per_page)
            orders = response.get("data", [])
            
            if not orders:
                break
            
            yield from orders
            
            if len(orders) < per_page:
                break
            
            page += 1
