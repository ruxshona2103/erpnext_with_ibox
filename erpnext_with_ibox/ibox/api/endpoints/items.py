from erpnext_with_ibox.ibox.config import IBOX_ENDPOINTS, DIRECTORY_TYPES


class ItemsEndpoint:
    """Items API endpoint handler for product_selection directory"""

    ENDPOINT = IBOX_ENDPOINTS["items"]
    DIRECTORY_TYPE = DIRECTORY_TYPES["items"]

    def __init__(self, client):
        self.client = client

    def get_list(self, page: int = 1, per_page: int = 100, updated_at_min: str = None) -> dict:
        """
        Get paginated list of items from directory API

        Args:
            page: Page number (1-indexed)
            per_page: Number of items per page
            updated_at_min: ISO datetime string — fetch only records updated after this time

        Returns:
            dict with keys: data, current_page, last_page, total, etc.
        """
        params = {
            "type": self.DIRECTORY_TYPE,
            "page": page,
            "per_page": per_page,
        }

        if updated_at_min:
            params["updated_at_min"] = updated_at_min

        return self.client.request(
            method="GET",
            endpoint=self.ENDPOINT,
            params=params,
        )

    def get_all(self, per_page: int = 100, updated_at_min: str = None):
        """
        Generator to fetch all items across all pages.

        Yields:
            tuple: (item_dict, page_number, total_from_api)
        """
        page = 1
        while True:
            response = self.get_list(
                page=page, per_page=per_page, updated_at_min=updated_at_min
            )
            items = response.get("data", [])
            total = response.get("total", 0)

            if not items:
                break

            for item in items:
                yield item, page, total

            if len(items) < per_page:
                break

            page += 1
