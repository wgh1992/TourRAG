#!/usr/bin/env python3
"""
Complete workflow to:
1. Delete all viewpoints from database
2. Insert only attraction type viewpoints from OSM
3. Download images, geo info, history, and season info for attractions

完整工作流：
1. 删除数据库中所有景点
2. 只插入attraction类型的景点
3. 下载attraction类型的数据（地理、图像、历史、季节信息）
"""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db


def run_command(cmd: list, description: str):
    """Run a command and handle errors"""
    print("\n" + "=" * 80)
    print(f"  {description}")
    print("=" * 80)
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        return True
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
        description='Complete workflow: Delete all viewpoints, insert only attractions, download all data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full workflow with default settings
  python scripts/setup_attraction_only.py
  
  # Skip deletion (if database is already empty)
  python scripts/setup_attraction_only.py --skip-delete
  
  # Only insert attractions from a specific region
  python scripts/setup_attraction_only.py --region europe --limit 1000
  
  # Skip image download (only insert data)
  python scripts/setup_attraction_only.py --skip-download
        """
    )
    parser.add_argument('--skip-delete', action='store_true',
                       help='Skip deletion step (use if database is already empty)')
    parser.add_argument('--skip-download', action='store_true',
                       help='Skip image download step (only insert OSM data)')
    parser.add_argument('--skip-wiki', action='store_true',
                       help='Skip Wikipedia/Wikidata data insertion')
    parser.add_argument('--skip-tags', action='store_true',
                       help='Skip visual tags generation')
    parser.add_argument('--region', type=str, default='europe',
                       help='Region to fetch OSM data from (default: europe). Use "all" for batch download from multiple regions.')
    parser.add_argument('--limit', type=int, default=5000,
                       help='Maximum number of attractions to fetch (default: 5000)')
    parser.add_argument('--batch-regions', action='store_true',
                       help='Batch download from multiple regions (same as --region all)')
    parser.add_argument('--yes', action='store_true',
                       help='Skip confirmation prompts')
    args = parser.parse_args()
    
    print("=" * 80)
    print("  Setup Attraction-Only Database")
    print("=" * 80)
    print("\nThis script will:")
    print("  1. Delete all existing viewpoints from database")
    print("  2. Insert only 'attraction' type viewpoints from OSM")
    print("  3. Download images, geo info, history, and season info")
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
    
    # Step 2: Insert only attraction type from OSM (using enhanced download script)
    print("\n" + "=" * 80)
    print("  Step 2: Insert Attraction Type Viewpoints from OSM")
    print("=" * 80)
    
    # Use new download_attraction_only.py script (enhanced with filtering)
    # Handle batch regions flag
    if args.batch_regions or args.region == 'all':
        # Batch download from multiple regions
        insert_cmd = [
            'python', 'scripts/download_attraction_only.py',
            '--batch-regions',
            '--require-wikipedia',
            '--limit', str(args.limit),
            '--yes'
        ]
        print(f"\n📥 批量下载attraction数据（多个区域，要求Wikipedia标签）")
    else:
        # Single region
        insert_cmd = [
            'python', 'scripts/download_attraction_only.py',
            '--region', args.region,
            '--limit', str(args.limit),
            '--require-wikipedia',
            '--yes'
        ]
        print(f"\n📥 下载attraction数据（区域: {args.region}, 限制: {args.limit}）")
        print("   要求: tourism=attraction或tourism=viewpoint, 必须有Wikipedia标签")
    
    success = run_command(insert_cmd, 'Downloading and inserting attraction viewpoints from OSM')
    
    if not success:
        print("\n❌ Failed to download/insert OSM data. Aborting.")
        return
    
    # Verify insertion - check attraction count
    attraction_count = check_attraction_count()
    print(f"\n✅ Database now has {attraction_count} attraction viewpoints")
    
    if attraction_count == 0:
        print("\n⚠️  No attractions were inserted. Check OSM data availability.")
        return
    
    # Verify all are attraction type (should already be filtered)
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
    
    # Step 3: Insert Wikipedia/Wikidata data
    if not args.skip_wiki:
        print("\n" + "=" * 80)
        print("  Step 3: Insert Wikipedia/Wikidata Data")
        print("=" * 80)
        
        success = run_command(
            ['python', 'scripts/insert_wiki_data.py'],
            'Inserting Wikipedia and Wikidata data'
        )
        
        if not success:
            print("\n⚠️  Wikipedia/Wikidata insertion had issues, but continuing...")
    else:
        print("\n⏭️  Skipping Wikipedia/Wikidata insertion")
    
    # Step 4: Download images and metadata
    if not args.skip_download:
        print("\n" + "=" * 80)
        print("  Step 4: Download Images, Geo Info, and Metadata")
        print("=" * 80)
        
        download_cmd = [
            'python', 'scripts/download_all_viewpoint_images.py',
            '--category', 'attraction',
            '--yes'
        ]
        
        success = run_command(download_cmd, 'Downloading images and metadata for attractions')
        
        if not success:
            print("\n⚠️  Image download had issues, but continuing...")
    else:
        print("\n⏭️  Skipping image download")
    
    # Step 5: Generate visual tags (season info)
    if not args.skip_tags:
        print("\n" + "=" * 80)
        print("  Step 5: Generate Visual Tags (Season Info)")
        print("=" * 80)
        
        # Check if generate_visual_tags_from_wiki.py exists
        tags_script = Path(__file__).parent / 'generate_visual_tags_from_wiki.py'
        if tags_script.exists():
            success = run_command(
                ['python', 'scripts/generate_visual_tags_from_wiki.py'],
                'Generating visual tags from Wikipedia'
            )
            
            if not success:
                print("\n⚠️  Tag generation had issues, but continuing...")
        else:
            print("\n⚠️  generate_visual_tags_from_wiki.py not found, skipping tag generation")
    else:
        print("\n⏭️  Skipping visual tags generation")
    
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
        
        cursor.execute("""
            SELECT COUNT(DISTINCT v.viewpoint_id) as count
            FROM viewpoint_entity v
            JOIN viewpoint_commons_assets vca ON v.viewpoint_id = vca.viewpoint_id
            WHERE vca.downloaded_at IS NOT NULL
        """)
        with_images = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(DISTINCT v.viewpoint_id) as count
            FROM viewpoint_entity v
            JOIN viewpoint_wiki w ON v.viewpoint_id = w.viewpoint_id
        """)
        with_wiki = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(DISTINCT v.viewpoint_id) as count
            FROM viewpoint_entity v
            JOIN viewpoint_visual_tags vt ON v.viewpoint_id = vt.viewpoint_id
        """)
        with_tags = cursor.fetchone()['count']
    
    print(f"\n📊 Database Status:")
    print(f"   Total viewpoints: {total:,}")
    print(f"   Attraction type: {attractions:,} ({(attractions/total*100) if total > 0 else 0:.1f}%)")
    print(f"   With images: {with_images:,} ({(with_images/total*100) if total > 0 else 0:.1f}%)")
    print(f"   With Wikipedia: {with_wiki:,} ({(with_wiki/total*100) if total > 0 else 0:.1f}%)")
    print(f"   With visual tags: {with_tags:,} ({(with_tags/total*100) if total > 0 else 0:.1f}%)")
    
    print("\n✅ Workflow completed!")
    print("\n💡 Next steps:")
    print("   - Run statistics: python scripts/statistics_database.py")
    print("   - Test search: python test_api.py")


if __name__ == "__main__":
    main()
