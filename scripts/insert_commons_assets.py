#!/usr/bin/env python3
"""
Insert sample Commons assets metadata for testing image download functionality.

This script inserts Commons asset metadata (without images) so that the
download script can then download and store the actual images.
"""
import sys
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor


# Sample Commons assets for popular tourist attractions
SAMPLE_COMMONS_ASSETS = [
    {
        "name_pattern": "Mount Fuji",
        "assets": [
            {
                "commons_file_id": "File:Great_Wall_of_China_July_2006.JPG",
                "commons_page": "https://commons.wikimedia.org/wiki/File:Great_Wall_of_China_July_2006.JPG",
                "caption": "Great Wall of China (using as test - replace with actual Mount Fuji image)",
                "categories": ["China", "World Heritage"],
                "depicts_wikidata": ["Q107706"],
                "license": "CC BY-SA 2.5"
            }
        ]
    },
    {
        "name_pattern": "Tokyo Skytree",
        "assets": [
            {
                "commons_file_id": "File:Tokyo_Skytree_2012.JPG",
                "commons_page": "https://commons.wikimedia.org/wiki/File:Tokyo_Skytree_2012.JPG",
                "caption": "Tokyo Skytree tower",
                "categories": ["Tokyo Skytree", "Tokyo", "Towers"],
                "depicts_wikidata": ["Q39051"],  # Tokyo Skytree QID
                "license": "CC BY-SA 3.0"
            }
        ]
    },
    {
        "name_pattern": "Eiffel Tower",
        "assets": [
            {
                "commons_file_id": "File:Tour_Eiffel_Wikimedia_Commons.jpg",
                "commons_page": "https://commons.wikimedia.org/wiki/File:Tour_Eiffel_Wikimedia_Commons.jpg",
                "caption": "Eiffel Tower in Paris",
                "categories": ["Eiffel Tower", "Paris", "Towers"],
                "depicts_wikidata": ["Q243"],  # Eiffel Tower QID
                "license": "CC BY-SA 4.0"
            }
        ]
    },
    {
        "name_pattern": "Great Wall",
        "assets": [
            {
                "commons_file_id": "File:Great_Wall_of_China_July_2006.JPG",
                "commons_page": "https://commons.wikimedia.org/wiki/File:Great_Wall_of_China_July_2006.JPG",
                "caption": "Great Wall of China",
                "categories": ["Great Wall", "China", "World Heritage"],
                "depicts_wikidata": ["Q107706"],  # Great Wall QID
                "license": "CC BY-SA 2.5"
            }
        ]
    }
]


def calculate_hash(text: str) -> str:
    """Calculate SHA256 hash of text."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:64]


def find_viewpoint_by_name(name_pattern: str) -> List[Dict[str, Any]]:
    """
    Find viewpoints matching a name pattern.
    
    Args:
        name_pattern: Name or partial name to search for
    
    Returns:
        List of matching viewpoints
    """
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT viewpoint_id, name_primary, name_variants
            FROM viewpoint_entity
            WHERE name_primary ILIKE %s
               OR name_variants::text ILIKE %s
            ORDER BY popularity DESC
            LIMIT 10
        """, (f"%{name_pattern}%", f"%{name_pattern}%"))
        
        return cursor.fetchall()


def insert_commons_assets_for_viewpoint(
    viewpoint_id: int,
    assets: List[Dict[str, Any]]
) -> int:
    """
    Insert Commons assets for a viewpoint.
    
    Args:
        viewpoint_id: Viewpoint ID
        assets: List of asset dictionaries
    
    Returns:
        Number of assets inserted
    """
    inserted = 0
    
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                for asset in assets:
                    # Calculate hash from file ID
                    file_hash = calculate_hash(asset["commons_file_id"])
                    
                    # Insert or update asset
                    cursor.execute("""
                        INSERT INTO viewpoint_commons_assets (
                            viewpoint_id,
                            commons_file_id,
                            commons_page,
                            caption,
                            categories,
                            depicts_wikidata,
                            timestamp,
                            hash,
                            license
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (viewpoint_id, commons_file_id) DO UPDATE
                        SET commons_page = EXCLUDED.commons_page,
                            caption = EXCLUDED.caption,
                            categories = EXCLUDED.categories,
                            depicts_wikidata = EXCLUDED.depicts_wikidata,
                            license = EXCLUDED.license
                        RETURNING id
                    """, (
                        viewpoint_id,
                        asset["commons_file_id"],
                        asset.get("commons_page"),
                        asset.get("caption"),
                        json.dumps(asset.get("categories", [])),
                        json.dumps(asset.get("depicts_wikidata", [])),
                        datetime.now(),
                        file_hash,
                        asset.get("license", "Unknown")
                    ))
                    
                    result = cursor.fetchone()
                    if result:
                        inserted += 1
                
                conn.commit()
                return inserted
    except Exception as e:
        print(f"Error inserting assets for viewpoint {viewpoint_id}: {e}")
        import traceback
        traceback.print_exc()
        return inserted


def main():
    """Main function to insert Commons assets."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Insert Commons assets metadata')
    parser.add_argument('--all', action='store_true', help='Insert assets for all sample viewpoints')
    parser.add_argument('--viewpoint-name', type=str, help='Insert assets for specific viewpoint name')
    parser.add_argument('--dry-run', action='store_true', help='Dry run without inserting')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Commons Assets Metadata Insertion Script")
    print("=" * 60)
    
    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No data will be inserted")
    
    total_inserted = 0
    
    # Determine which viewpoints to process
    if args.viewpoint_name:
        # Process specific viewpoint
        viewpoints_to_process = [{"name_pattern": args.viewpoint_name}]
    elif args.all:
        # Process all sample viewpoints
        viewpoints_to_process = SAMPLE_COMMONS_ASSETS
    else:
        # Default: process first sample
        viewpoints_to_process = SAMPLE_COMMONS_ASSETS[:1]
        print("\nNote: Use --all to insert assets for all sample viewpoints")
    
    for viewpoint_config in viewpoints_to_process:
        name_pattern = viewpoint_config["name_pattern"]
        assets = viewpoint_config["assets"]
        
        print(f"\n🔍 Searching for viewpoints matching: '{name_pattern}'")
        
        # Find matching viewpoints
        viewpoints = find_viewpoint_by_name(name_pattern)
        
        if not viewpoints:
            print(f"  ⚠️  No viewpoints found matching '{name_pattern}'")
            print(f"     Tip: Run insert_sample_data.py first to create sample viewpoints")
            continue
        
        # Use the first (most popular) match
        viewpoint = viewpoints[0]
        viewpoint_id = viewpoint['viewpoint_id']
        viewpoint_name = viewpoint['name_primary']
        
        print(f"  ✓ Found: {viewpoint_name} (ID: {viewpoint_id})")
        print(f"  📦 Inserting {len(assets)} Commons assets...")
        
        if not args.dry_run:
            inserted = insert_commons_assets_for_viewpoint(viewpoint_id, assets)
            total_inserted += inserted
            print(f"  ✓ Inserted {inserted} assets")
        else:
            print(f"  [DRY RUN] Would insert {len(assets)} assets")
            total_inserted += len(assets)
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total assets {'would be ' if args.dry_run else ''}inserted: {total_inserted}")
    
    if not args.dry_run and total_inserted > 0:
        # Show statistics
        with db.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM viewpoint_commons_assets")
            total_assets = cursor.fetchone()['count']
            print(f"Total Commons assets in database: {total_assets}")
    
    print("=" * 60)
    
    if total_inserted > 0 and not args.dry_run:
        print("\n✅ Next step: Run download script to download images:")
        print("   python scripts/download_commons_images.py --limit 10")


if __name__ == "__main__":
    main()

