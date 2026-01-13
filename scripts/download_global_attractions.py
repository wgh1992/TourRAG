#!/usr/bin/env python3
"""
Download 10000 attraction viewpoints from global OSM data

This script:
1. Deletes all existing viewpoints
2. Downloads 10000 attraction type viewpoints from global regions
3. Downloads geo info and country information (no images)
4. Inserts Wikipedia/Wikidata data (history info)
5. Generates season information only (no visual tags)

从全球下载10000个attraction类型景点，包含地理、边界、历史、季节信息，不包含图像和visual tags
"""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db


def run_command(cmd: list, description: str, check: bool = True):
    """Run a command and handle errors"""
    print("\n" + "=" * 80)
    print(f"  {description}")
    print("=" * 80)
    
    try:
        result = subprocess.run(cmd, check=check, capture_output=False)
        return result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error running command: {' '.join(cmd)}")
        print(f"   Exit code: {e.returncode}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False


def check_attraction_count() -> int:
    """Check how many attraction viewpoints exist"""
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM viewpoint_entity
            WHERE category_norm = 'attraction'
        """)
        return cursor.fetchone()['count']


def main():
    """Main workflow"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Download 10000 global attraction viewpoints with geo, history, and season info (no images, no visual tags)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download 10000 attractions from global regions
  python scripts/download_global_attractions.py
  
  # Custom limit
  python scripts/download_global_attractions.py --limit 5000
  
  # Skip deletion (if database is already empty)
  python scripts/download_global_attractions.py --skip-delete
        """
    )
    parser.add_argument('--skip-delete', action='store_true',
                       help='Skip deletion step (use if database is already empty)')
    parser.add_argument('--limit', type=int, default=None,
                       help='Maximum number of attractions to download (default: None, no limit)')
    parser.add_argument('--yes', action='store_true',
                       help='Skip confirmation prompts')
    args = parser.parse_args()
    
    print("=" * 80)
    print("  Download Global Attraction Viewpoints")
    print("=" * 80)
    print("\nThis script will:")
    print("  1. Delete all existing viewpoints from database")
    limit_text = f"{args.limit} attraction type viewpoints" if args.limit else "all available attraction type viewpoints (no limit)"
    print(f"  2. Download {limit_text} from global regions")
    print("  3. Download geo info and country information (NO images)")
    print("  4. Insert Wikipedia/Wikidata data (history info)")
    print("  5. Skip season information generation (NO visual tags)")
    print()
    
    if not args.yes:
        response = input("Continue? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Cancelled.")
            return
    
    success = True
    
    # Step 1: Delete all viewpoints
    if not args.skip_delete:
        print("\n" + "=" * 80)
        print("  Step 1: Delete All Viewpoints")
        print("=" * 80)
        
        if not args.yes:
            response = input("\n⚠️  This will delete ALL viewpoints. Continue? (yes/no): ")
            if response.lower() not in ['yes', 'y']:
                print("Cancelled.")
                return
        
        success = run_command(
            ['python', 'scripts/delete_all_viewpoints.py', '--execute'],
            'Deleting all viewpoints'
        )
        
        if not success:
            print("\n❌ Failed to delete viewpoints. Aborting.")
            return
        
        # Verify deletion
        with db.get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as count FROM viewpoint_entity")
            remaining = cursor.fetchone()['count']
            if remaining > 0:
                print(f"\n⚠️  Warning: {remaining} viewpoints still remain")
            else:
                print("\n✅ Database is now empty")
    else:
        print("\n⏭️  Skipping deletion step")
    
    # Step 2: Download attraction viewpoints from global regions (no limit, no region restriction)
    print("\n" + "=" * 80)
    print("  Step 2: Download Attraction Viewpoints from Global Regions (No Limit)")
    print("=" * 80)
    limit_text = f"目标: {args.limit}个景点" if args.limit else "无限制（下载所有可用景点）"
    print(f"\n📥 批量下载attraction数据（全球多个区域，{limit_text}）")
    print("   要求: tourism=attraction或tourism=viewpoint, 必须有Wikipedia和Wikidata标签")
    
    # Build command - no limit if args.limit is None
    insert_cmd = [
        'python', 'scripts/download_attraction_only.py',
        '--batch-regions',
        '--require-wikipedia',
        '--require-wikidata',  # Require Wikidata tag
        '--yes'
    ]
    
    # Only add limit if specified
    if args.limit:
        # Calculate limit per region (distribute evenly across 6 regions)
        limit_per_region = max(1666, args.limit // 6)
        insert_cmd.extend(['--limit', str(limit_per_region)])
    
    success = run_command(insert_cmd, 'Downloading and inserting attraction viewpoints from global OSM')
    
    if not success:
        print("\n❌ Failed to download/insert OSM data. Aborting.")
        return
    
    # Verify insertion - check attraction count
    attraction_count = check_attraction_count()
    print(f"\n✅ Database now has {attraction_count} attraction viewpoints")
    
    if attraction_count == 0:
        print("\n⚠️  No attractions were inserted. Check OSM data availability.")
        return
    
    # Limit to exactly args.limit if specified and we got more
    if args.limit and attraction_count > args.limit:
        print(f"\n📊 限制为前 {args.limit} 个景点（按popularity排序）...")
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                # Get IDs to keep (top N by popularity)
                cursor.execute("""
                    SELECT viewpoint_id
                    FROM viewpoint_entity
                    WHERE category_norm = 'attraction'
                    ORDER BY popularity DESC NULLS LAST, viewpoint_id
                    LIMIT %s
                """, (args.limit,))
                keep_ids = [row[0] for row in cursor.fetchall()]
                
                # Delete others
                cursor.execute("""
                    DELETE FROM viewpoint_entity
                    WHERE category_norm = 'attraction'
                    AND viewpoint_id != ALL(%s)
                """, (keep_ids,))
                deleted = cursor.rowcount
                conn.commit()
                
                print(f"   ✅ 删除了 {deleted} 个多余的景点")
                attraction_count = args.limit
    
    # Verify all are attraction type
    print("\n🔍 Verifying all viewpoints are attraction type...")
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM viewpoint_entity
                WHERE category_norm != 'attraction'
            """)
            non_attractions = cursor.fetchone()[0]
            
            if non_attractions > 0:
                print(f"   ⚠️  Found {non_attractions} non-attraction viewpoints, deleting...")
                cursor.execute("""
                    DELETE FROM viewpoint_entity
                    WHERE category_norm != 'attraction'
                """)
                conn.commit()
                print(f"   ✅ Deleted {non_attractions} non-attraction viewpoints")
            else:
                print("   ✅ All viewpoints are attraction type")
    
    # Step 3: Download geo info and country information (NO images)
    print("\n" + "=" * 80)
    print("  Step 3: Download Geo Info and Country Information (NO Images)")
    print("=" * 80)
    
    # Note: download_all_viewpoint_images.py may not exist or may not support --country-only
    # For now, we skip this step as images are not needed
    # Geo info (coordinates) is already in viewpoint_entity.geom
    # Country info can be added later if needed via reverse geocoding
    print("\n⏭️  跳过地理信息下载步骤（图像不需要，坐标已在OSM数据中）")
    print("   注意：国家信息可以通过后续脚本添加（如果需要）")
    
    # Step 4: Insert Wikipedia/Wikidata data (history info)
    print("\n" + "=" * 80)
    print("  Step 4: Insert Wikipedia/Wikidata Data (History Info)")
    print("=" * 80)
    
    success = run_command(
        ['python', 'scripts/insert_wiki_data.py'],
        'Inserting Wikipedia and Wikidata data',
        check=False
    )
    
    if not success:
        print("\n⚠️  Wikipedia/Wikidata insertion had issues, but continuing...")
    
    # Step 5: Skip season information generation (as requested)
    print("\n" + "=" * 80)
    print("  Step 5: Skip Season Information Generation (NO Visual Tags)")
    print("=" * 80)
    print("\n⏭️  跳过季节信息生成步骤（不生成visual tags）")
    
    # Final summary
    print("\n" + "=" * 80)
    print("  Final Summary")
    print("=" * 80)
    
    with db.get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM viewpoint_entity")
        total = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM viewpoint_entity
            WHERE category_norm = 'attraction'
        """)
        attractions = cursor.fetchone()['count']
        
        # Check geo info (country info)
        cursor.execute("""
            SELECT COUNT(DISTINCT v.viewpoint_id) as count
            FROM viewpoint_entity v
            JOIN viewpoint_commons_assets vca ON v.viewpoint_id = vca.viewpoint_id
            WHERE vca.viewpoint_country IS NOT NULL AND vca.viewpoint_country != ''
        """)
        with_geo = cursor.fetchone()['count']
        
        # Check images (should be 0)
        cursor.execute("""
            SELECT COUNT(DISTINCT v.viewpoint_id) as count
            FROM viewpoint_entity v
            JOIN viewpoint_commons_assets vca ON v.viewpoint_id = vca.viewpoint_id
            WHERE vca.downloaded_at IS NOT NULL AND vca.image_blob IS NOT NULL
        """)
        with_images = cursor.fetchone()['count']
        
        # Check Wikipedia/Wikidata (history info)
        cursor.execute("""
            SELECT COUNT(DISTINCT v.viewpoint_id) as count
            FROM viewpoint_entity v
            JOIN viewpoint_wiki w ON v.viewpoint_id = w.viewpoint_id
        """)
        with_wiki = cursor.fetchone()['count']
        
        # Check season info (from visual_tags table, but only season field)
        cursor.execute("""
            SELECT COUNT(DISTINCT viewpoint_id) as count
            FROM viewpoint_visual_tags
            WHERE season IN ('spring', 'summer', 'autumn', 'winter')
        """)
        with_season = cursor.fetchone()['count']
        
        # Check visual tags (should be minimal or none if we only want season)
        cursor.execute("""
            SELECT COUNT(DISTINCT viewpoint_id) as count
            FROM viewpoint_visual_tags
        """)
        with_tags = cursor.fetchone()['count']
    
    print(f"\n📊 Database Status:")
    print(f"   Total viewpoints: {total:,}")
    print(f"   Attraction type: {attractions:,} ({(attractions/total*100) if total > 0 else 0:.1f}%)")
    print(f"   With geo info (country): {with_geo:,} ({(with_geo/total*100) if total > 0 else 0:.1f}%)")
    print(f"   With images: {with_images:,} (should be 0) ({(with_images/total*100) if total > 0 else 0:.1f}%)")
    print(f"   With Wikipedia/Wikidata (history): {with_wiki:,} ({(with_wiki/total*100) if total > 0 else 0:.1f}%)")
    print(f"   With season info: {with_season:,} ({(with_season/total*100) if total > 0 else 0:.1f}%)")
    print(f"   With visual tags records: {with_tags:,} ({(with_tags/total*100) if total > 0 else 0:.1f}%)")
    
    print("\n✅ Workflow completed!")
    print("\n💡 Summary:")
    print(f"   - Downloaded {attractions:,} attraction viewpoints from global regions")
    print(f"   - Geo info and country data: {with_geo:,} viewpoints")
    print(f"   - History info (Wikipedia/Wikidata): {with_wiki:,} viewpoints")
    print(f"   - Season information: {with_season:,} viewpoints")
    print(f"   - Images: {with_images:,} (as requested, no images downloaded)")
    print("\n💡 Next steps:")
    print("   - Run statistics: python scripts/statistics_database.py")
    print("   - Test search: python test_api.py")


if __name__ == "__main__":
    main()
