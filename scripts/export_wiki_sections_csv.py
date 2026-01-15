#!/usr/bin/env python3
"""
Export Wikipedia sections data to CSV

This script exports viewpoint Wikipedia data including sections to a CSV file.
Usage: python scripts/export_wiki_sections_csv.py [--output OUTPUT_FILE]
"""
import sys
import csv
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor


def get_wiki_sections_data(cursor) -> List[Dict[str, Any]]:
    """Get Wikipedia sections data from database"""
    query = """
    SELECT 
        vw.viewpoint_id,
        ve.name_primary,
        ve.category_norm,
        vw.wikipedia_title,
        vw.wikipedia_lang,
        vw.extract_text,
        vw.sections,
        vw.citations,
        vw.last_updated,
        vw.created_at
    FROM viewpoint_wiki vw
    JOIN viewpoint_entity ve ON vw.viewpoint_id = ve.viewpoint_id
    WHERE vw.sections IS NOT NULL
    ORDER BY vw.viewpoint_id
    """
    
    cursor.execute(query)
    return cursor.fetchall()


def format_sections_for_csv(sections) -> str:
    """Format sections JSON for CSV export"""
    if not sections:
        return ""
    
    try:
        if isinstance(sections, str):
            sections = json.loads(sections)
        
        # Format as readable text
        formatted = []
        for section in sections:
            title = section.get('title', '')
            content = section.get('content', '')
            level = section.get('level', 2)
            
            if content:
                formatted.append(f"{'  ' * (level - 2)}## {title}\n{content[:500]}")
            else:
                formatted.append(f"{'  ' * (level - 2)}## {title}")
        
        return "\n\n".join(formatted)
    except Exception as e:
        return str(sections)


def format_citations_for_csv(citations) -> str:
    """Format citations JSON for CSV export"""
    if not citations:
        return ""
    
    try:
        if isinstance(citations, str):
            citations = json.loads(citations)
        
        formatted = []
        for citation in citations:
            ref = citation.get('ref', '')
            text = citation.get('text', '')
            url = citation.get('url', '')
            
            if url:
                formatted.append(f"{text}: {url}")
            else:
                formatted.append(text)
        
        return "; ".join(formatted)
    except Exception as e:
        return str(citations)


def export_to_csv(output_file: str):
    """Export Wikipedia sections data to CSV"""
    print("=" * 60)
    print("Wikipedia Sections CSV Export")
    print("=" * 60)
    
    print("\nFetching data from database...")
    try:
        with db.get_cursor() as cursor:
            rows = get_wiki_sections_data(cursor)
        
        print(f"✓ Found {len(rows)} records with sections")
    except Exception as e:
        print(f"✗ Error fetching data: {e}")
        import traceback
        traceback.print_exc()
        return
    
    if not rows:
        print("⚠️  No data to export")
        return
    
    print(f"\nExporting to CSV: {output_file}")
    
    # Define CSV columns
    columns = [
        'viewpoint_id',
        'name_primary',
        'category_norm',
        'wikipedia_title',
        'wikipedia_lang',
        'extract_text',
        'sections_formatted',
        'sections_count',
        'sections_json',
        'citations_formatted',
        'citations_json',
        'last_updated',
        'created_at'
    ]
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        
        for i, row in enumerate(rows, 1):
            # Parse sections
            sections = row.get('sections')
            sections_json = json.dumps(sections, ensure_ascii=False) if sections else ""
            sections_formatted = format_sections_for_csv(sections)
            sections_count = len(sections) if sections else 0
            
            # Parse citations
            citations = row.get('citations')
            citations_json = json.dumps(citations, ensure_ascii=False) if citations else ""
            citations_formatted = format_citations_for_csv(citations)
            
            # Prepare row
            csv_row = {
                'viewpoint_id': row.get('viewpoint_id'),
                'name_primary': row.get('name_primary', ''),
                'category_norm': row.get('category_norm', ''),
                'wikipedia_title': row.get('wikipedia_title', ''),
                'wikipedia_lang': row.get('wikipedia_lang', ''),
                'extract_text': row.get('extract_text', ''),
                'sections_formatted': sections_formatted,
                'sections_count': sections_count,
                'sections_json': sections_json,
                'citations_formatted': citations_formatted,
                'citations_json': citations_json,
                'last_updated': str(row.get('last_updated', '')) if row.get('last_updated') else '',
                'created_at': str(row.get('created_at', '')) if row.get('created_at') else ''
            }
            
            writer.writerow(csv_row)
            
            # Progress indicator
            if i % 500 == 0:
                print(f"  Processed {i}/{len(rows)} records...")
    
    print(f"\n✅ Successfully exported {len(rows)} records to {output_file}")
    
    # Show file size
    import os
    file_size = os.path.getsize(output_file)
    if file_size < 1024:
        size_str = f"{file_size} bytes"
    elif file_size < 1024 * 1024:
        size_str = f"{file_size / 1024:.1f} KB"
    else:
        size_str = f"{file_size / (1024 * 1024):.1f} MB"
    print(f"📊 File size: {size_str}")


def main():
    parser = argparse.ArgumentParser(
        description="Export Wikipedia sections data to CSV"
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output CSV file path (default: exports/wiki_sections_YYYYMMDD_HHMMSS.csv)'
    )
    
    args = parser.parse_args()
    
    # Generate output filename if not provided
    if not args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(__file__).parent.parent / "exports"
        output_dir.mkdir(exist_ok=True)
        args.output = str(output_dir / f"wiki_sections_{timestamp}.csv")
    
    export_to_csv(args.output)


if __name__ == "__main__":
    main()
