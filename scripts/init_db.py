#!/usr/bin/env python3
"""
Initialize database with schema and sample data (optional)
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from app.config import settings


def init_database():
    """Run database migrations"""
    print(f"Connecting to database: {settings.DATABASE_URL.split('@')[-1]}")
    
    # Read migration file
    migration_file = Path(__file__).parent.parent / "migrations" / "001_initial_schema.sql"
    
    if not migration_file.exists():
        print(f"Error: Migration file not found: {migration_file}")
        return False
    
    with open(migration_file, "r", encoding="utf-8") as f:
        migration_sql = f.read()
    
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                # Execute migration
                cursor.execute(migration_sql)
                print("✓ Database schema created successfully")
                
                # Insert tag schema version
                tag_schema_file = Path(__file__).parent.parent / "config" / "tags" / f"tag_schema_{settings.TAG_SCHEMA_VERSION}.json"
                if tag_schema_file.exists():
                    import json
                    with open(tag_schema_file, "r", encoding="utf-8") as f:
                        schema_def = json.load(f)
                    
                    cursor.execute("""
                        INSERT INTO tag_schema_version (version, schema_definition)
                        VALUES (%s, %s)
                        ON CONFLICT (version) DO UPDATE
                        SET schema_definition = EXCLUDED.schema_definition
                    """, (settings.TAG_SCHEMA_VERSION, json.dumps(schema_def)))
                    print(f"✓ Tag schema version {settings.TAG_SCHEMA_VERSION} registered")
        
        return True
    except Exception as e:
        print(f"Error initializing database: {e}")
        return False


if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)

