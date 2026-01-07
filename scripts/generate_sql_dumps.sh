#!/bin/bash

# Script to generate SQL dumps for TourRAG database
# Usage: ./scripts/generate_sql_dumps.sh

DB_NAME="tourrag_db"
SCHEMA_FILE="tourrag_db_schema.sql"
FULL_FILE="tourrag_db_full.sql"

# Find pg_dump (try PostgreSQL 17 first, then common locations)
PG_DUMP=""
if [ -f "/opt/homebrew/Cellar/postgresql@17/17.5/bin/pg_dump" ]; then
    PG_DUMP="/opt/homebrew/Cellar/postgresql@17/17.5/bin/pg_dump"
elif command -v pg_dump &> /dev/null; then
    PG_DUMP="pg_dump"
elif [ -f "/usr/local/bin/pg_dump" ]; then
    PG_DUMP="/usr/local/bin/pg_dump"
else
    echo "Error: pg_dump not found. Please install PostgreSQL or specify pg_dump path."
    exit 1
fi

echo "Using pg_dump: $PG_DUMP"
echo "Database: $DB_NAME"
echo ""

# Generate schema-only dump
echo "Generating schema-only dump: $SCHEMA_FILE"
$PG_DUMP -s "$DB_NAME" > "$SCHEMA_FILE"
if [ $? -eq 0 ]; then
    echo "✓ Schema dump created: $SCHEMA_FILE"
    echo "  Size: $(du -h "$SCHEMA_FILE" | cut -f1)"
else
    echo "✗ Failed to create schema dump"
    exit 1
fi

echo ""

# Generate full dump (schema + data)
echo "Generating full dump (schema + data): $FULL_FILE"
$PG_DUMP "$DB_NAME" > "$FULL_FILE"
if [ $? -eq 0 ]; then
    echo "✓ Full dump created: $FULL_FILE"
    echo "  Size: $(du -h "$FULL_FILE" | cut -f1)"
else
    echo "✗ Failed to create full dump"
    exit 1
fi

echo ""
echo "Done! SQL dumps generated:"
echo "  - Schema only: $SCHEMA_FILE"
echo "  - Full dump:   $FULL_FILE"

