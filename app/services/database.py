"""
Database connection and utilities
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import Iterator, Dict, Any, List

from app.config import settings


class Database:
    """Database connection manager"""
    
    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or settings.DATABASE_URL
    
    @contextmanager
    def get_connection(self) -> Iterator[psycopg2.extensions.connection]:
        """Get database connection with context manager"""
        conn = psycopg2.connect(self.connection_string)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    @contextmanager
    def get_cursor(self) -> Iterator[RealDictCursor]:
        """Get database cursor with context manager"""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                yield cursor
            finally:
                cursor.close()


# Global database instance
db = Database()

