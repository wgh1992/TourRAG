#!/usr/bin/env python3
"""
Remove duplicate viewpoints from database

This script identifies and removes duplicate viewpoints based on:
1. Same name_primary (exact match)
2. Same Wikidata QID
3. Very close geographic locations (within distance threshold)
"""
import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple, Any
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor


def calculate_completeness_score(viewpoint_id: int, cursor) -> int:
    """Calculate completeness score for a viewpoint (higher = more complete)"""
    score = 0
    
    # Check for Wikipedia
    cursor.execute("SELECT 1 FROM viewpoint_wiki WHERE viewpoint_id = %s", (viewpoint_id,))
    if cursor.fetchone():
        score += 2
    
    # Check for Wikidata
    cursor.execute("SELECT 1 FROM viewpoint_wikidata WHERE viewpoint_id = %s", (viewpoint_id,))
    if cursor.fetchone():
        score += 2
    
    # Check for visual tags
    cursor.execute("SELECT COUNT(*) as count FROM viewpoint_visual_tags WHERE viewpoint_id = %s", (viewpoint_id,))
    tag_count = cursor.fetchone()['count']
    score += min(tag_count, 3)  # Max 3 points for tags
    
    # Check for images
    cursor.execute("""
        SELECT COUNT(*) as count 
        FROM viewpoint_commons_assets 
        WHERE viewpoint_id = %s AND downloaded_at IS NOT NULL
    """, (viewpoint_id,))
    image_count = cursor.fetchone()['count']
    score += min(image_count, 2)  # Max 2 points for images
    
    # Check for metadata
    cursor.execute("""
        SELECT 
            CASE WHEN viewpoint_category_norm IS NOT NULL THEN 1 ELSE 0 END +
            CASE WHEN viewpoint_country IS NOT NULL THEN 1 ELSE 0 END +
            CASE WHEN viewpoint_boundary IS NOT NULL THEN 1 ELSE 0 END as metadata_count
        FROM viewpoint_commons_assets
        WHERE viewpoint_id = %s
        LIMIT 1
    """, (viewpoint_id,))
    result = cursor.fetchone()
    if result and result['metadata_count']:
        score += min(result['metadata_count'], 2)  # Max 2 points for metadata
    
    return score


def find_duplicates_by_name_only() -> List[Tuple[int, List[int]]]:
    """Find duplicate viewpoints with same name_primary (without location check)"""
    duplicates = []
    
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT name_primary, array_agg(viewpoint_id ORDER BY viewpoint_id) as ids
            FROM viewpoint_entity
            GROUP BY name_primary
            HAVING COUNT(*) > 1
            ORDER BY name_primary
        """)
        
        for row in cursor.fetchall():
            ids = row['ids']
            if len(ids) > 1:
                duplicates.append((row['name_primary'], ids))
    
    return duplicates


def find_duplicates_by_name(distance_threshold_meters: float = 100.0) -> List[Tuple[int, List[int]]]:
    """
    Find duplicate viewpoints with same name_primary AND close location
    Only considers viewpoints as duplicates if they have the same name AND are within distance threshold
    """
    duplicates = []
    
    with db.get_cursor() as cursor:
        # Find viewpoints with same name that are close to each other
        # This query finds pairs of viewpoints with same name within distance threshold
        cursor.execute("""
            WITH same_name_pairs AS (
                SELECT 
                    v1.name_primary,
                    v1.viewpoint_id as id1,
                    v2.viewpoint_id as id2,
                    ST_Distance(
                        v1.geom::geography,
                        v2.geom::geography
                    ) as distance_meters
                FROM viewpoint_entity v1
                JOIN viewpoint_entity v2 
                    ON v1.name_primary = v2.name_primary
                    AND v1.viewpoint_id < v2.viewpoint_id
                WHERE v1.geom IS NOT NULL 
                    AND v2.geom IS NOT NULL
                    AND ST_DWithin(
                        v1.geom::geography,
                        v2.geom::geography,
                        %s
                    )
            )
            SELECT name_primary, id1, id2, distance_meters
            FROM same_name_pairs
            ORDER BY name_primary, distance_meters
        """, (distance_threshold_meters,))
        
        # Group pairs into clusters
        clusters = defaultdict(set)
        for row in cursor.fetchall():
            name = row['name_primary']
            id1, id2 = row['id1'], row['id2']
            
            # Find existing cluster or create new one
            found_cluster = None
            for cluster_id, cluster in clusters.items():
                if id1 in cluster or id2 in cluster:
                    found_cluster = cluster_id
                    break
            
            if found_cluster:
                clusters[found_cluster].add(id1)
                clusters[found_cluster].add(id2)
            else:
                clusters[id1].add(id1)
                clusters[id1].add(id2)
        
        # Convert clusters to list format
        for cluster in clusters.values():
            if len(cluster) > 1:
                ids = sorted(list(cluster))
                # Get name for the first ID
                cursor.execute("SELECT name_primary FROM viewpoint_entity WHERE viewpoint_id = %s", (ids[0],))
                name = cursor.fetchone()['name_primary']
                duplicates.append((name, ids))
    
    return duplicates


def find_duplicates_by_wikidata() -> List[Tuple[str, List[int]]]:
    """Find duplicate viewpoints with same Wikidata QID"""
    duplicates = []
    
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT wd.wikidata_qid, array_agg(wd.viewpoint_id ORDER BY wd.viewpoint_id) as ids
            FROM viewpoint_wikidata wd
            GROUP BY wd.wikidata_qid
            HAVING COUNT(*) > 1
            ORDER BY wd.wikidata_qid
        """)
        
        for row in cursor.fetchall():
            ids = row['ids']
            if len(ids) > 1:
                duplicates.append((row['wikidata_qid'], ids))
    
    return duplicates


def find_duplicates_by_location(distance_threshold_meters: float = 100.0) -> List[Tuple[int, List[int]]]:
    """
    Find duplicate viewpoints that are very close geographically
    Uses PostGIS ST_DWithin with spatial index for fast distance calculation
    Optimized to use GIST index on geom column
    """
    duplicates = []
    
    with db.get_cursor() as cursor:
        # Use ST_DWithin with geography for accurate distance, but leverage spatial index
        # This query is optimized to use the GIST index on geom
        print("   Processing location pairs (this may take a while)...")
        cursor.execute("""
            WITH nearby_pairs AS (
                SELECT 
                    v1.viewpoint_id as id1,
                    v2.viewpoint_id as id2,
                    ST_Distance(
                        v1.geom::geography,
                        v2.geom::geography
                    ) as distance_meters
                FROM viewpoint_entity v1
                INNER JOIN viewpoint_entity v2 
                    ON v1.viewpoint_id < v2.viewpoint_id
                    AND v1.geom IS NOT NULL 
                    AND v2.geom IS NOT NULL
                    AND ST_DWithin(
                        v1.geom::geography,
                        v2.geom::geography,
                        %s
                    )
            )
            SELECT id1, id2, distance_meters
            FROM nearby_pairs
            ORDER BY distance_meters
            LIMIT 10000
        """, (distance_threshold_meters,))
        
        # Group pairs into clusters
        clusters = defaultdict(set)
        for row in cursor.fetchall():
            id1, id2 = row['id1'], row['id2']
            # Find existing cluster or create new one
            found_cluster = None
            for cluster_id, cluster in clusters.items():
                if id1 in cluster or id2 in cluster:
                    found_cluster = cluster_id
                    break
            
            if found_cluster:
                clusters[found_cluster].add(id1)
                clusters[found_cluster].add(id2)
            else:
                clusters[id1].add(id1)
                clusters[id1].add(id2)
        
        # Convert clusters to list format
        for cluster in clusters.values():
            if len(cluster) > 1:
                ids = sorted(list(cluster))
                duplicates.append((ids[0], ids))
    
    return duplicates


def select_viewpoint_to_keep(viewpoint_ids: List[int], cursor) -> int:
    """Select the best viewpoint to keep from a list of duplicates"""
    if len(viewpoint_ids) == 1:
        return viewpoint_ids[0]
    
    # Calculate completeness score for each viewpoint
    scores = {}
    for vp_id in viewpoint_ids:
        scores[vp_id] = calculate_completeness_score(vp_id, cursor)
    
    # Sort by score (descending), then by viewpoint_id (ascending for consistency)
    # Keep the one with highest score, or if tied, keep the one with smaller ID (older/earlier)
    best_id = max(viewpoint_ids, key=lambda x: (scores.get(x, 0), -x))
    
    return best_id


def delete_viewpoints(viewpoint_ids: List[int], dry_run: bool = True) -> int:
    """Delete viewpoints and their related data (CASCADE will handle related tables)"""
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
    
    parser = argparse.ArgumentParser(description='Remove duplicate viewpoints')
    parser.add_argument('--execute', action='store_true',
                       help='Actually delete viewpoints (default is dry-run)')
    parser.add_argument('--distance-threshold', type=float, default=100.0,
                       help='Distance threshold in meters for location-based duplicates (default: 100)')
    parser.add_argument('--by-name', action='store_true',
                       help='Find duplicates by name only')
    parser.add_argument('--by-wikidata', action='store_true',
                       help='Find duplicates by Wikidata QID only')
    parser.add_argument('--by-location', action='store_true',
                       help='Find duplicates by location only (SLOW - may take a long time)')
    parser.add_argument('--name-only', action='store_true',
                       help='Find duplicates by name without location check (FAST - recommended)')
    parser.add_argument('--skip-location', action='store_true',
                       help='Skip location-based duplicate detection (faster)')
    args = parser.parse_args()
    
    print("=" * 70)
    print("Remove Duplicate Viewpoints")
    print("=" * 70)
    
    # Find duplicates
    all_duplicates = {}  # viewpoint_id -> list of duplicate IDs (including itself)
    to_delete = set()
    
    with db.get_cursor() as cursor:
        # Find duplicates by name
        if args.name_only:
            print("\n🔍 Finding duplicates by name only (no location check)...")
            name_duplicates = find_duplicates_by_name_only()
            print(f"   Found {len(name_duplicates)} groups of duplicates by name")
        elif args.by_name:
            print("\n🔍 Finding duplicates by name (with location check)...")
            name_duplicates = find_duplicates_by_name(args.distance_threshold)
            print(f"   Found {len(name_duplicates)} groups of duplicates by name and location")
        elif not args.by_wikidata and not args.by_location:
            # Default: use name-only for speed
            print("\n🔍 Finding duplicates by name only (fast mode)...")
            name_duplicates = find_duplicates_by_name_only()
            print(f"   Found {len(name_duplicates)} groups of duplicates by name")
        else:
            name_duplicates = []
        
        # Process name duplicates
        if name_duplicates:
            for name, ids in name_duplicates:
                keep_id = select_viewpoint_to_keep(ids, cursor)
                for vp_id in ids:
                    if vp_id != keep_id:
                        to_delete.add(vp_id)
                        if vp_id not in all_duplicates:
                            all_duplicates[vp_id] = []
                        all_duplicates[vp_id].extend([name, 'name'])
            
            if name_duplicates:
                print(f"   Examples:")
                for name, ids in name_duplicates[:5]:
                    keep_id = select_viewpoint_to_keep(ids, cursor)
                    cursor.execute("SELECT name_primary FROM viewpoint_entity WHERE viewpoint_id = %s", (keep_id,))
                    keep_name = cursor.fetchone()['name_primary']
                    print(f"     '{name}': {len(ids)} duplicates, keeping ID {keep_id} ({keep_name})")
        
        # Find duplicates by Wikidata QID
        if args.by_wikidata or (not args.by_name and not args.by_location):
            print("\n🔍 Finding duplicates by Wikidata QID...")
            wikidata_duplicates = find_duplicates_by_wikidata()
            print(f"   Found {len(wikidata_duplicates)} groups of duplicates by Wikidata QID")
            
            for qid, ids in wikidata_duplicates:
                keep_id = select_viewpoint_to_keep(ids, cursor)
                for vp_id in ids:
                    if vp_id != keep_id:
                        to_delete.add(vp_id)
                        if vp_id not in all_duplicates:
                            all_duplicates[vp_id] = []
                        all_duplicates[vp_id].extend([qid, 'wikidata'])
            
            if wikidata_duplicates:
                print(f"   Examples:")
                for qid, ids in wikidata_duplicates[:5]:
                    keep_id = select_viewpoint_to_keep(ids, cursor)
                    cursor.execute("SELECT name_primary FROM viewpoint_entity WHERE viewpoint_id = %s", (keep_id,))
                    keep_name = cursor.fetchone()['name_primary']
                    print(f"     QID {qid}: {len(ids)} duplicates, keeping ID {keep_id} ({keep_name})")
        
        # Find duplicates by location (only if explicitly requested, as it's slow)
        if args.by_location:
            print(f"\n🔍 Finding duplicates by location (threshold: {args.distance_threshold}m)...")
            print("   ⚠️  This may take a long time for large datasets...")
            location_duplicates = find_duplicates_by_location(args.distance_threshold)
            print(f"   Found {len(location_duplicates)} groups of duplicates by location")
            
        else:
            location_duplicates = []
        
        # Process location duplicates
        if location_duplicates:
            for first_id, ids in location_duplicates:
                keep_id = select_viewpoint_to_keep(ids, cursor)
                for vp_id in ids:
                    if vp_id != keep_id:
                        to_delete.add(vp_id)
                        if vp_id not in all_duplicates:
                            all_duplicates[vp_id] = []
                        all_duplicates[vp_id].extend([f"location_group_{first_id}", 'location'])
            
            print(f"   Examples:")
            for first_id, ids in location_duplicates[:5]:
                keep_id = select_viewpoint_to_keep(ids, cursor)
                cursor.execute("SELECT name_primary FROM viewpoint_entity WHERE viewpoint_id = %s", (keep_id,))
                keep_name = cursor.fetchone()['name_primary']
                print(f"     Location group: {len(ids)} duplicates, keeping ID {keep_id} ({keep_name})")
    
    # Summary
    print(f"\n📊 Summary:")
    print(f"   Total duplicate viewpoints to remove: {len(to_delete)}")
    
    if not to_delete:
        print("\n✅ No duplicate viewpoints found!")
        return
    
    # Show some examples
    print(f"\n📋 Examples of viewpoints to be removed:")
    with db.get_cursor() as cursor:
        for vp_id in list(to_delete)[:10]:
            cursor.execute("""
                SELECT 
                    v.viewpoint_id,
                    v.name_primary,
                    CASE WHEN w.viewpoint_id IS NULL THEN 'No' ELSE 'Yes' END as has_wiki,
                    CASE WHEN wd.viewpoint_id IS NULL THEN 'No' ELSE 'Yes' END as has_wikidata,
                    (SELECT COUNT(*) FROM viewpoint_visual_tags WHERE viewpoint_id = v.viewpoint_id) as tag_count,
                    (SELECT COUNT(*) FROM viewpoint_commons_assets WHERE viewpoint_id = v.viewpoint_id AND downloaded_at IS NOT NULL) as image_count
                FROM viewpoint_entity v
                LEFT JOIN viewpoint_wiki w ON v.viewpoint_id = w.viewpoint_id
                LEFT JOIN viewpoint_wikidata wd ON v.viewpoint_id = wd.viewpoint_id
                WHERE v.viewpoint_id = %s
            """, (vp_id,))
            row = cursor.fetchone()
            if row:
                print(f"   ID {row['viewpoint_id']}: {row['name_primary']}")
                print(f"      Wiki: {row['has_wiki']}, Wikidata: {row['has_wikidata']}, Tags: {row['tag_count']}, Images: {row['image_count']}")
    
    if len(to_delete) > 10:
        print(f"   ... and {len(to_delete) - 10} more")
    
    # Delete viewpoints
    dry_run = not args.execute
    if dry_run:
        print(f"\n⚠️  DRY RUN MODE - No deletions will be performed")
        print(f"   Use --execute to actually delete viewpoints")
    
    deleted = delete_viewpoints(list(to_delete), dry_run=dry_run)
    
    if args.execute:
        print(f"\n✅ Deleted {deleted} duplicate viewpoints")
        
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
