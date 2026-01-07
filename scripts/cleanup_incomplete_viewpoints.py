#!/usr/bin/env python3
"""
Clean up incomplete viewpoints from database

Remove viewpoints that don't have:
1. Wikipedia history info
2. Visual tags (at least one tag record)
"""
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor


def find_incomplete_viewpoints() -> List[int]:
    """Find viewpoints missing history or tags"""
    incomplete_ids = []
    
    with db.get_cursor() as cursor:
        # Find viewpoints without Wikipedia
        cursor.execute("""
            SELECT v.viewpoint_id, v.name_primary
            FROM viewpoint_entity v
            WHERE NOT EXISTS (
                SELECT 1 FROM viewpoint_wiki w 
                WHERE w.viewpoint_id = v.viewpoint_id
            )
        """)
        no_wiki = cursor.fetchall()
        
        # Find viewpoints without Wikidata
        cursor.execute("""
            SELECT v.viewpoint_id, v.name_primary
            FROM viewpoint_entity v
            WHERE NOT EXISTS (
                SELECT 1 FROM viewpoint_wikidata wd 
                WHERE wd.viewpoint_id = v.viewpoint_id
            )
        """)
        no_wikidata = cursor.fetchall()
        
        # Find viewpoints without visual tags
        cursor.execute("""
            SELECT v.viewpoint_id, v.name_primary
            FROM viewpoint_entity v
            WHERE NOT EXISTS (
                SELECT 1 FROM viewpoint_visual_tags vt 
                WHERE vt.viewpoint_id = v.viewpoint_id
            )
        """)
        no_tags = cursor.fetchall()
        
        # Combine all incomplete viewpoints
        incomplete_ids = set()
        incomplete_ids.update(row['viewpoint_id'] for row in no_wiki)
        incomplete_ids.update(row['viewpoint_id'] for row in no_wikidata)
        incomplete_ids.update(row['viewpoint_id'] for row in no_tags)
        
        return {
            'ids': list(incomplete_ids),
            'no_wiki': [row['viewpoint_id'] for row in no_wiki],
            'no_wikidata': [row['viewpoint_id'] for row in no_wikidata],
            'no_tags': [row['viewpoint_id'] for row in no_tags],
            'details': {
                'no_wiki': no_wiki,
                'no_wikidata': no_wikidata,
                'no_tags': no_tags
            }
        }


def delete_viewpoints(viewpoint_ids: List[int], dry_run: bool = True) -> int:
    """Delete viewpoints and their related data"""
    if not viewpoint_ids:
        return 0
    
    deleted = 0
    
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                if dry_run:
                    print(f"\n[DRY RUN] Would delete {len(viewpoint_ids)} viewpoints:")
                    for vp_id in viewpoint_ids[:10]:  # Show first 10
                        cursor.execute("SELECT name_primary FROM viewpoint_entity WHERE viewpoint_id = %s", (vp_id,))
                        row = cursor.fetchone()
                        if row:
                            print(f"  - {row['name_primary']} (ID: {vp_id})")
                    if len(viewpoint_ids) > 10:
                        print(f"  ... and {len(viewpoint_ids) - 10} more")
                    return 0
                
                # Delete viewpoints (CASCADE will handle related tables)
                placeholders = ','.join(['%s'] * len(viewpoint_ids))
                cursor.execute(f"""
                    DELETE FROM viewpoint_entity
                    WHERE viewpoint_id IN ({placeholders})
                """, viewpoint_ids)
                
                deleted = cursor.rowcount
                conn.commit()
        
        return deleted
    except Exception as e:
        print(f"Error deleting viewpoints: {e}")
        import traceback
        traceback.print_exc()
        return 0


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Clean up incomplete viewpoints')
    parser.add_argument('--execute', action='store_true', 
                       help='Actually delete viewpoints (default is dry-run)')
    parser.add_argument('--require-history-only', action='store_true',
                       help='Only require history (Wikipedia/Wikidata), not tags')
    parser.add_argument('--require-tags-only', action='store_true',
                       help='Only require tags, not history')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Cleanup Incomplete Viewpoints")
    print("=" * 60)
    
    # Find incomplete viewpoints
    print("\nScanning database for incomplete viewpoints...")
    incomplete = find_incomplete_viewpoints()
    
    print(f"\nFound incomplete viewpoints:")
    print(f"  Without Wikipedia: {len(incomplete['no_wiki'])}")
    print(f"  Without Wikidata: {len(incomplete['no_wikidata'])}")
    print(f"  Without visual tags: {len(incomplete['no_tags'])}")
    print(f"  Total unique incomplete: {len(incomplete['ids'])}")
    
    # Filter based on requirements
    if args.require_history_only:
        # Only require history, not tags
        to_delete = set(incomplete['no_wiki']) | set(incomplete['no_wikidata'])
        print(f"\n[History-only mode] Will delete {len(to_delete)} viewpoints missing history")
    elif args.require_tags_only:
        # Only require tags, not history
        to_delete = set(incomplete['no_tags'])
        print(f"\n[Tags-only mode] Will delete {len(to_delete)} viewpoints missing tags")
    else:
        # Require both history AND tags (default)
        # Delete if missing history OR missing tags
        to_delete = incomplete['ids']
        print(f"\n[Full mode] Will delete {len(to_delete)} viewpoints missing history OR tags")
    
    if not to_delete:
        print("\n✅ No incomplete viewpoints found!")
        return
    
    # Show some examples
    print(f"\nExamples of incomplete viewpoints:")
    with db.get_cursor() as cursor:
        for vp_id in list(to_delete)[:5]:
            cursor.execute("""
                SELECT 
                    v.viewpoint_id,
                    v.name_primary,
                    CASE WHEN w.viewpoint_id IS NULL THEN 'No' ELSE 'Yes' END as has_wiki,
                    CASE WHEN wd.viewpoint_id IS NULL THEN 'No' ELSE 'Yes' END as has_wikidata,
                    CASE WHEN vt.viewpoint_id IS NULL THEN 'No' ELSE 'Yes' END as has_tags
                FROM viewpoint_entity v
                LEFT JOIN viewpoint_wiki w ON v.viewpoint_id = w.viewpoint_id
                LEFT JOIN viewpoint_wikidata wd ON v.viewpoint_id = wd.viewpoint_id
                LEFT JOIN viewpoint_visual_tags vt ON v.viewpoint_id = vt.viewpoint_id
                WHERE v.viewpoint_id = %s
            """, (vp_id,))
            row = cursor.fetchone()
            if row:
                print(f"  ID {row['viewpoint_id']}: {row['name_primary']}")
                print(f"    Wikipedia: {row['has_wiki']}, Wikidata: {row['has_wikidata']}, Tags: {row['has_tags']}")
    
    # Delete viewpoints
    dry_run = not args.execute
    if dry_run:
        print(f"\n⚠️  DRY RUN MODE - No deletions will be performed")
        print(f"   Use --execute to actually delete viewpoints")
    
    deleted = delete_viewpoints(list(to_delete), dry_run=dry_run)
    
    if args.execute:
        print(f"\n✅ Deleted {deleted} incomplete viewpoints")
        
        # Verify
        with db.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM viewpoint_entity")
            remaining = cursor.fetchone()['count']
            print(f"   Remaining viewpoints: {remaining}")
    else:
        print(f"\n[DRY RUN] Would delete {len(to_delete)} viewpoints")
        print(f"   Run with --execute to perform deletion")


if __name__ == "__main__":
    main()

