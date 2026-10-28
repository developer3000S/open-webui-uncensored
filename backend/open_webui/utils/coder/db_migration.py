# -*- coding: utf-8 -*-
"""
Database migration utilities for Coder section.

This module provides functions to ensure database schema is correct
when the database is reinstalled or reset.
"""

import logging
import sqlite3
from typing import Optional

from open_webui.config import DATABASE_URL

log = logging.getLogger(__name__)


def get_db_path() -> Optional[str]:
    """Get the SQLite database file path from DATABASE_URL."""
    if DATABASE_URL.startswith('sqlite:///'):
        return DATABASE_URL[10:]  # Remove 'sqlite:///' prefix
    return None


def ensure_coder_schema() -> bool:
    """
    Ensure the coder_github_connection table has all required columns.
    
    Returns:
        bool: True if schema is correct or fixed, False if error occurred.
    """
    db_path = get_db_path()
    if not db_path:
        log.error("Cannot determine SQLite database path from DATABASE_URL")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='coder_github_connection'
        """)
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            log.warning("Table coder_github_connection does not exist")
            conn.close()
            return False
        
        # Check for missing columns
        cursor.execute("PRAGMA table_info(coder_github_connection)")
        columns = [col[1] for col in cursor.fetchall()]
        
        missing_columns = []
        required_columns = ['installation_id']  # Add more if needed
        
        for col in required_columns:
            if col not in columns:
                missing_columns.append(col)
        
        if missing_columns:
            log.info(f"Adding missing columns to coder_github_connection: {', '.join(missing_columns)}")
            for col in missing_columns:
                cursor.execute(f"ALTER TABLE coder_github_connection ADD COLUMN {col} TEXT")
            conn.commit()
            log.info("Database schema updated successfully")
        else:
            log.info("Database schema is already correct")
            
        conn.close()
        return True
        
    except Exception as e:
        log.error(f"Error during database schema validation: {e}", exc_info=True)
        return False