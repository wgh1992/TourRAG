#!/usr/bin/env python3
"""
Export database to SQL and CSV formats
Usage: python scripts/export_database.py [--output-dir OUTPUT_DIR]
"""
import os
import sys
import csv
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
import psycopg2


def export_table_to_csv(cursor, table_name: str, output_file: str):
    """Export a table to CSV file"""
    print(f"  Exporting {table_name} to CSV...")
    
    # Get column names
    cursor.execute(f"""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = %s 
        ORDER BY ordinal_position
    """, (table_name,))
    columns = [row['column_name'] for row in cursor.fetchall()]
    
    # Get all data
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    
    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            
            for row in rows:
                # Convert dict-like row to regular dict and handle special types
                row_dict = {}
                for col in columns:
                    value = row[col]
                    # Handle JSONB, arrays, and other complex types
                    if value is None:
                        row_dict[col] = None
                    elif isinstance(value, (dict, list)):
                        row_dict[col] = json.dumps(value, ensure_ascii=False)
                    elif isinstance(value, bytes):
                        # Skip binary data (like image_blob) in CSV
                        row_dict[col] = f"<BINARY_DATA_{len(value)}_BYTES>"
                    else:
                        row_dict[col] = value
                writer.writerow(row_dict)
    
    print(f"    ✓ Exported {len(rows)} rows to {output_file}")


def export_table_to_sql(cursor, table_name: str, output_file: str):
    """Export a table to SQL INSERT statements"""
    print(f"  Exporting {table_name} to SQL...")
    
    # Get column names and types
    cursor.execute(f"""
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns 
        WHERE table_name = %s 
        ORDER BY ordinal_position
    """, (table_name,))
    columns_info = cursor.fetchall()
    columns = [row['column_name'] for row in columns_info]
    column_types = {row['column_name']: row['data_type'] for row in columns_info}
    
    # Get all data
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    
    # Write to SQL file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"-- Export of table: {table_name}\n")
        f.write(f"-- Exported at: {datetime.now().isoformat()}\n")
        f.write(f"-- Total rows: {len(rows)}\n\n")
        
        if rows:
            # Generate INSERT statements
            for row in rows:
                values = []
                for col in columns:
                    value = row[col]
                    if value is None:
                        values.append('NULL')
                    elif isinstance(value, bool):
                        values.append('TRUE' if value else 'FALSE')
                    elif isinstance(value, (int, float)):
                        values.append(str(value))
                    elif isinstance(value, str):
                        # Escape single quotes
                        escaped = value.replace("'", "''")
                        values.append(f"'{escaped}'")
                    elif isinstance(value, (dict, list)):
                        # JSONB data
                        json_str = json.dumps(value, ensure_ascii=False).replace("'", "''")
                        values.append(f"'{json_str}'::jsonb")
                    elif isinstance(value, bytes):
                        # Binary data - use hex format
                        hex_data = value.hex()
                        values.append(f"'\\x{hex_data}'::bytea")
                    else:
                        # Fallback: convert to string
                        escaped = str(value).replace("'", "''")
                        values.append(f"'{escaped}'")
                
                columns_str = ', '.join(columns)
                values_str = ', '.join(values)
                f.write(f"INSERT INTO {table_name} ({columns_str}) VALUES ({values_str});\n")
    
    print(f"    ✓ Exported {len(rows)} rows to {output_file}")


def get_table_list(cursor) -> List[str]:
    """Get list of all tables in the database"""
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    return [row['table_name'] for row in cursor.fetchall()]


def export_schema(cursor, output_file: str):
    """Export database schema (CREATE TABLE statements)"""
    print(f"  Exporting database schema...")
    
    tables = get_table_list(cursor)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"-- Database Schema Export\n")
        f.write(f"-- Exported at: {datetime.now().isoformat()}\n\n")
        
        for table_name in tables:
            # Get CREATE TABLE statement using pg_dump approach
            cursor.execute(f"""
                SELECT 
                    'CREATE TABLE ' || quote_ident(table_name) || ' (' || 
                    string_agg(
                        quote_ident(column_name) || ' ' || 
                        CASE 
                            WHEN data_type = 'USER-DEFINED' THEN udt_name
                            WHEN data_type = 'ARRAY' THEN udt_name || '[]'
                            ELSE data_type
                        END ||
                        CASE 
                            WHEN is_nullable = 'NO' THEN ' NOT NULL'
                            ELSE ''
                        END,
                        ', '
                        ORDER BY ordinal_position
                    ) || ');' as create_statement
                FROM information_schema.columns
                WHERE table_name = %s
                GROUP BY table_name
            """, (table_name,))
            
            result = cursor.fetchone()
            if result and result['create_statement']:
                f.write(f"\n-- Table: {table_name}\n")
                f.write(result['create_statement'] + "\n\n")
    
    print(f"    ✓ Schema exported to {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Export database to SQL and CSV formats')
    parser.add_argument(
        '--output-dir',
        type=str,
        default='exports',
        help='Output directory for exported files (default: exports)'
    )
    parser.add_argument(
        '--tables',
        type=str,
        nargs='+',
        help='Specific tables to export (default: all tables)'
    )
    parser.add_argument(
        '--format',
        type=str,
        choices=['both', 'sql', 'csv'],
        default='both',
        help='Export format: both, sql, or csv (default: both)'
    )
    
    args = parser.parse_args()
    
    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create timestamped subdirectory
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_dir = output_dir / timestamp
    export_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("Database Export Tool")
    print("=" * 80)
    print(f"Output directory: {export_dir}")
    print(f"Format: {args.format}")
    print()
    
    try:
        with db.get_cursor() as cursor:
            # Get list of tables
            all_tables = get_table_list(cursor)
            
            if args.tables:
                # Filter to requested tables
                tables = [t for t in all_tables if t in args.tables]
                if not tables:
                    print(f"❌ Error: None of the specified tables found in database")
                    print(f"Available tables: {', '.join(all_tables)}")
                    return
            else:
                tables = all_tables
            
            print(f"Found {len(tables)} table(s) to export:")
            for table in tables:
                print(f"  - {table}")
            print()
            
            # Export schema if SQL format is requested
            if args.format in ['both', 'sql']:
                schema_file = export_dir / 'schema.sql'
                export_schema(cursor, str(schema_file))
                print()
            
            # Export each table
            for table_name in tables:
                print(f"Exporting table: {table_name}")
                
                if args.format in ['both', 'sql']:
                    sql_file = export_dir / f'{table_name}.sql'
                    export_table_to_sql(cursor, table_name, str(sql_file))
                
                if args.format in ['both', 'csv']:
                    csv_file = export_dir / f'{table_name}.csv'
                    export_table_to_csv(cursor, table_name, str(csv_file))
                
                print()
            
            # Create a combined SQL file with all INSERT statements
            if args.format in ['both', 'sql']:
                print("Creating combined SQL file...")
                combined_file = export_dir / 'all_data.sql'
                with open(combined_file, 'w', encoding='utf-8') as f:
                    f.write(f"-- Complete Database Export\n")
                    f.write(f"-- Exported at: {datetime.now().isoformat()}\n")
                    f.write(f"-- Tables: {', '.join(tables)}\n\n")
                    
                    # Read schema
                    schema_file = export_dir / 'schema.sql'
                    if schema_file.exists():
                        f.write("-- Schema\n")
                        f.write("-- " + "=" * 76 + "\n")
                        with open(schema_file, 'r', encoding='utf-8') as sf:
                            f.write(sf.read())
                        f.write("\n\n")
                    
                    # Read all table SQL files
                    for table_name in tables:
                        table_file = export_dir / f'{table_name}.sql'
                        if table_file.exists():
                            f.write(f"\n-- Data for table: {table_name}\n")
                            f.write("-- " + "=" * 76 + "\n")
                            with open(table_file, 'r', encoding='utf-8') as tf:
                                # Skip header comments
                                for line in tf:
                                    if not line.strip().startswith('--'):
                                        f.write(line)
                            f.write("\n")
                
                print(f"  ✓ Combined SQL file created: {combined_file}")
                print()
            
            # Create summary file
            summary_file = export_dir / 'export_summary.txt'
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write("Database Export Summary\n")
                f.write("=" * 80 + "\n")
                f.write(f"Export time: {datetime.now().isoformat()}\n")
                f.write(f"Format: {args.format}\n")
                f.write(f"Tables exported: {len(tables)}\n\n")
                f.write("Tables:\n")
                for table_name in tables:
                    # Get row count
                    cursor.execute(f"SELECT COUNT(*) as count FROM {table_name}")
                    count = cursor.fetchone()['count']
                    f.write(f"  - {table_name}: {count} rows\n")
            
            print("=" * 80)
            print("✅ Export completed successfully!")
            print(f"📁 Files saved to: {export_dir}")
            print()
            print("Exported files:")
            for file in sorted(export_dir.iterdir()):
                size = file.stat().st_size
                size_str = f"{size:,} bytes" if size < 1024 else f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.1f} MB"
                print(f"  - {file.name} ({size_str})")
    
    except Exception as e:
        print(f"❌ Error during export: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
