# Copyright (c) 2026, asadbek.backend@gmail.com and contributors
# For license information, please see license.txt

"""
Base Sync Handler - Abstract base class for all sync handlers
"""

from abc import ABC, abstractmethod
from typing import Any, Generator
import frappe


class BaseSyncHandler(ABC):
    """
    Abstract base class for sync handlers.
    
    To add a new doctype sync:
    1. Create new handler class extending BaseSyncHandler
    2. Implement fetch_data(), sync_single(), get_existing_filter()
    3. Register in SYNC_HANDLERS dict in __init__.py
    """
    
    # Override in subclass
    DOCTYPE = None
    NAME = None
    
    def __init__(self, api_client, client_doc):
        """
        Initialize handler with API client and iBox Client doc
        
        Args:
            api_client: IBoxAPIClient instance
            client_doc: iBox Client document
        """
        self.api = api_client
        self.client_doc = client_doc
    
    @abstractmethod
    def fetch_data(self) -> Generator[dict, None, None]:
        """
        Fetch data from iBox API. Should yield individual records.
        
        Yields:
            dict: Single record data from iBox
        """
        pass
    
    @abstractmethod
    def sync_single(self, data: dict) -> bool:
        """
        Sync a single record to ERPNext.
        
        Args:
            data: Single record from iBox
            
        Returns:
            True if synced, False if skipped (already exists)
        """
        pass
    
    @abstractmethod
    def get_existing_filter(self, data: dict) -> dict:
        """
        Get filter to check if record already exists in ERPNext.
        
        Args:
            data: Single record from iBox
            
        Returns:
            dict filter for frappe.db.exists()
        """
        pass
    
    def exists(self, data: dict) -> bool:
        """Check if record already exists in ERPNext"""
        return bool(frappe.db.exists(self.DOCTYPE, self.get_existing_filter(data)))
    
    def run(self) -> int:
        """
        Run the sync process.
        
        Returns:
            Number of records synced
        """
        total_synced = 0
        
        for record in self.fetch_data():
            try:
                if self.sync_single(record):
                    total_synced += 1
            except Exception as e:
                frappe.log_error(
                    title=f"{self.NAME} Sync Error",
                    message=f"Record: {record.get('id')}\nError: {str(e)}"
                )
        
        return total_synced
