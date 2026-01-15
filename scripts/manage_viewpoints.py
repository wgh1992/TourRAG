#!/usr/bin/env python3
"""
Unified Viewpoint Management Script
整合所有景点管理功能的主脚本

This script provides a unified interface for all viewpoint management operations:
- Database initialization
- Data insertion (OSM, Wiki, Commons, Sample)
- Image downloading
- Tag generation
- Data cleanup
- Status checking
"""
import sys
import argparse
import subprocess
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor


def print_header(title: str):
    """Print a formatted header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title: str):
    """Print a formatted section"""
    print(f"\n{'─' * 70}")
    print(f"  {title}")
    print(f"{'─' * 70}")


def check_database_connection() -> bool:
    """Check if database connection is available"""
    try:
        with db.get_cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


def run_script(script_name: str, args: list = None, description: str = None) -> bool:
    """Run a Python script and return success status"""
    script_path = Path(__file__).parent / script_name
    if not script_path.exists():
        print(f"❌ Script not found: {script_name}")
        return False
    
    if description:
        print(f"\n📋 {description}")
    
    cmd = ["python", str(script_path)]
    if args:
        cmd.extend(args)
    
    print(f"   Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=Path(__file__).parent.parent, check=False)
        return result.returncode == 0
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def init_database():
    """Initialize database schema"""
    print_header("Database Initialization")
    
    if not check_database_connection():
        print("❌ Cannot connect to database. Please check your configuration.")
        return False
    
    print("\n📋 Running database migrations...")
    
    # Run migrations
    migrations = [
        "migrations/001_initial_schema.sql",
        "migrations/002_add_image_storage.sql",
        "migrations/003_add_viewpoint_metadata.sql",
        "migrations/004_add_tag_source_gpt_4o_mini_image_history.sql"
    ]
    
    for migration in migrations:
        migration_path = Path(__file__).parent.parent / migration
        if migration_path.exists():
            print(f"   Running: {migration}")
            result = subprocess.run(
                ["psql", "-d", "tourrag_db", "-f", str(migration_path)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"   ✓ {migration} completed")
            else:
                print(f"   ⚠️  {migration} had warnings (may already be applied)")
        else:
            print(f"   ⚠️  Migration not found: {migration}")
    
    # Run init_db.py for tag schema
    return run_script("init_db.py", description="Initializing tag schema")


def insert_osm_data(limit: Optional[int] = None):
    """Insert OSM test data"""
    print_header("Insert OSM Data")
    
    args = []
    if limit:
        # Note: insert_osm_data.py doesn't have --limit, but we can add it
        pass
    
    return run_script("insert_osm_data.py", args, "Inserting OSM viewpoint data")


def insert_sample_data():
    """Insert sample data"""
    print_header("Insert Sample Data")
    return run_script("insert_sample_data.py", description="Inserting sample viewpoint data")


def insert_wiki_data():
    """Insert Wikipedia and Wikidata data"""
    print_header("Insert Wikipedia & Wikidata Data")
    return run_script("insert_wiki_data.py", description="Inserting Wikipedia and Wikidata data")


def insert_commons_assets(all_assets: bool = False, viewpoint_name: Optional[str] = None):
    """Insert Commons assets metadata"""
    print_header("Insert Commons Assets")
    
    args = []
    if all_assets:
        args.append("--all")
    elif viewpoint_name:
        args.extend(["--viewpoint-name", viewpoint_name])
    
    return run_script("insert_commons_assets.py", args, "Inserting Commons assets metadata")


def download_viewpoint_images(limit: Optional[int] = None, skip_downloaded: bool = False, 
                              batch_size: int = 50, batch_delay: float = 2.0):
    """Download images for all viewpoints with full metadata"""
    print_header("Download Viewpoint Images & Metadata")
    
    args = []
    if limit:
        args.extend(["--limit", str(limit)])
    if skip_downloaded:
        args.append("--skip-downloaded")
    args.extend(["--batch-size", str(batch_size)])
    args.extend(["--batch-delay", str(batch_delay)])
    
    return run_script("download_all_viewpoint_images.py", args, 
                     "Downloading satellite images and metadata for all viewpoints")


def download_commons_images(limit: Optional[int] = None, skip_downloaded: bool = False,
                           viewpoint_id: Optional[int] = None):
    """Download images from Wikimedia Commons"""
    print_header("Download Commons Images")
    
    args = []
    if limit:
        args.extend(["--limit", str(limit)])
    if skip_downloaded:
        args.append("--skip-downloaded")
    if viewpoint_id:
        args.extend(["--viewpoint-id", str(viewpoint_id)])
    
    return run_script("download_commons_images.py", args, "Downloading images from Wikimedia Commons")


def generate_visual_tags(limit: Optional[int] = None, dry_run: bool = False):
    """Generate visual tags from Wikipedia using LLM"""
    print_header("Generate Visual Tags")
    
    args = []
    if limit:
        args.extend(["--limit", str(limit)])
    if dry_run:
        args.append("--dry-run")
    
    return run_script("generate_visual_tags_from_wiki.py", args,
                     "Generating visual tags from Wikipedia using LLM")


def generate_image_visual_tags(image_dir: Optional[str] = None, limit: Optional[int] = None,
                               dry_run: bool = False, batch_size: int = 50,
                               sleep: float = 0.1, model: Optional[str] = None):
    """Generate visual tags and summaries from images + history text"""
    print_header("Generate Visual Tags from Images")

    args = []
    if image_dir:
        args.extend(["--image-dir", image_dir])
    if limit:
        args.extend(["--limit", str(limit)])
    if dry_run:
        args.append("--dry-run")
    if batch_size:
        args.extend(["--batch-size", str(batch_size)])
    if sleep is not None:
        args.extend(["--sleep", str(sleep)])
    if model:
        args.extend(["--model", model])

    return run_script(
        "generate_visual_tags_from_images.py",
        args,
        "Generating visual tags, season info, and summaries from images + history"
    )


def check_downloaded_images():
    """Check downloaded images status (using check_viewpoint_summary.py)"""
    print_header("Check Downloaded Images")
    return run_script("check_viewpoint_summary.py", ["--images"], description="Checking downloaded images")


def check_data_completeness():
    """Check data completeness (using check_viewpoint_summary.py)"""
    print_header("Data Completeness Check")
    return run_script("check_viewpoint_summary.py", description="Checking data completeness")


def cleanup_incomplete_viewpoints(execute: bool = False, require_history_only: bool = False,
                                   require_tags_only: bool = False):
    """Clean up incomplete viewpoints"""
    print_header("Cleanup Incomplete Viewpoints")
    
    args = []
    if execute:
        args.append("--execute")
    if require_history_only:
        args.append("--require-history-only")
    if require_tags_only:
        args.append("--require-tags-only")
    
    return run_script("cleanup_incomplete_viewpoints.py", args,
                     "Cleaning up incomplete viewpoints")


def cleanup_and_generate_tags(generate_tags: bool = False, cleanup: bool = False,
                               execute: bool = False, limit: Optional[int] = None,
                               require_history_only: bool = False):
    """Generate tags and cleanup incomplete viewpoints (using cleanup_incomplete_viewpoints.py)"""
    print_header("Generate Tags & Cleanup")
    
    args = []
    if generate_tags:
        args.append("--generate-tags")
        if limit:
            args.extend(["--tags-limit", str(limit)])
    if execute:
        args.append("--execute")
    if require_history_only:
        args.append("--require-history-only")
    
    return run_script("cleanup_incomplete_viewpoints.py", args,
                     "Generating tags and cleaning up incomplete viewpoints")


def remove_duplicates(execute: bool = False, by_name: bool = False, by_wikidata: bool = False,
                      by_location: bool = False, name_only: bool = True, distance_threshold: float = 100.0):
    """Remove duplicate viewpoints"""
    print_header("Remove Duplicate Viewpoints")
    
    args = []
    if execute:
        args.append("--execute")
    if by_name:
        args.append("--by-name")
    if by_wikidata:
        args.append("--by-wikidata")
    if by_location:
        args.append("--by-location")
    if name_only:
        args.append("--name-only")
    if distance_threshold != 100.0:
        args.extend(["--distance-threshold", str(distance_threshold)])
    
    return run_script("remove_duplicate_viewpoints.py", args,
                     "Removing duplicate viewpoints")


def show_status():
    """Show current database status"""
    print_header("Database Status")
    
    if not check_database_connection():
        return False
    
    try:
        with db.get_cursor() as cursor:
            # Total viewpoints
            cursor.execute("SELECT COUNT(*) as count FROM viewpoint_entity")
            total_viewpoints = cursor.fetchone()['count']
            
            # Viewpoints with images
            cursor.execute("""
                SELECT COUNT(DISTINCT viewpoint_id) as count
                FROM viewpoint_commons_assets
                WHERE downloaded_at IS NOT NULL
            """)
            with_images = cursor.fetchone()['count']
            
            # Viewpoints with Wikipedia
            cursor.execute("SELECT COUNT(*) as count FROM viewpoint_wiki")
            with_wiki = cursor.fetchone()['count']
            
            # Viewpoints with Wikidata
            cursor.execute("SELECT COUNT(*) as count FROM viewpoint_wikidata")
            with_wikidata = cursor.fetchone()['count']
            
            # Viewpoints with visual tags
            cursor.execute("""
                SELECT COUNT(DISTINCT viewpoint_id) as count
                FROM viewpoint_visual_tags
            """)
            with_tags = cursor.fetchone()['count']
            
            # Viewpoints with metadata (category, country, etc.)
            # Note: boundary and area are only for polygon types, most viewpoints are points
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM viewpoint_commons_assets
                WHERE viewpoint_category_norm IS NOT NULL
                   OR viewpoint_country IS NOT NULL
                   OR viewpoint_boundary IS NOT NULL
            """)
            with_metadata = cursor.fetchone()['count']
            
            # Viewpoints with category info (most important metadata)
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM viewpoint_commons_assets
                WHERE viewpoint_category_norm IS NOT NULL
            """)
            with_category = cursor.fetchone()['count']
            
            # Viewpoints with country info
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM viewpoint_commons_assets
                WHERE viewpoint_country IS NOT NULL
            """)
            with_country = cursor.fetchone()['count']
            
            # Viewpoints with boundary (only for polygon types)
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM viewpoint_commons_assets
                WHERE viewpoint_boundary IS NOT NULL
            """)
            with_boundary = cursor.fetchone()['count']
            
            # Total images
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM viewpoint_commons_assets
                WHERE image_blob IS NOT NULL
            """)
            total_images = cursor.fetchone()['count']
            
            print(f"\n📊 Database Statistics:")
            print(f"   Total viewpoints: {total_viewpoints}")
            print(f"   With images: {with_images} ({with_images/total_viewpoints*100:.1f}%)" if total_viewpoints > 0 else "   With images: 0")
            print(f"   With Wikipedia: {with_wiki} ({with_wiki/total_viewpoints*100:.1f}%)" if total_viewpoints > 0 else "   With Wikipedia: 0")
            print(f"   With Wikidata: {with_wikidata} ({with_wikidata/total_viewpoints*100:.1f}%)" if total_viewpoints > 0 else "   With Wikidata: 0")
            print(f"   With visual tags: {with_tags} ({with_tags/total_viewpoints*100:.1f}%)" if total_viewpoints > 0 else "   With visual tags: 0")
            print(f"   With category metadata: {with_category} ({with_category/total_viewpoints*100:.1f}%)" if total_viewpoints > 0 else "   With category metadata: 0")
            print(f"   With country info: {with_country} ({with_country/total_viewpoints*100:.1f}%)" if total_viewpoints > 0 else "   With country info: 0")
            print(f"   With polygon boundary: {with_boundary} (only for polygon types)" if with_boundary > 0 else "   With polygon boundary: 0 (most viewpoints are points)")
            print(f"   Total images stored: {total_images}")
            
            # Show category distribution
            cursor.execute("""
                SELECT category_norm, COUNT(*) as count
                FROM viewpoint_entity
                WHERE category_norm IS NOT NULL
                GROUP BY category_norm
                ORDER BY count DESC
                LIMIT 10
            """)
            categories = cursor.fetchall()
            if categories:
                print(f"\n📂 Top Categories:")
                for cat in categories:
                    print(f"   {cat['category_norm']}: {cat['count']}")
            
            # Show country distribution
            cursor.execute("""
                SELECT viewpoint_country, COUNT(*) as count
                FROM viewpoint_commons_assets
                WHERE viewpoint_country IS NOT NULL
                GROUP BY viewpoint_country
                ORDER BY count DESC
                LIMIT 10
            """)
            countries = cursor.fetchall()
            if countries:
                print(f"\n🌍 Top Countries:")
                for country in countries:
                    print(f"   {country['viewpoint_country']}: {country['count']}")
            
        return True
    except Exception as e:
        print(f"❌ Error checking status: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main function with unified CLI"""
    parser = argparse.ArgumentParser(
        description='Unified Viewpoint Management Script',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize database
  python scripts/manage_viewpoints.py init

  # Insert OSM test data
  python scripts/manage_viewpoints.py insert-osm

  # Insert Wikipedia data
  python scripts/manage_viewpoints.py insert-wiki

  # Download images with metadata
  python scripts/manage_viewpoints.py download-images --limit 10

  # Generate visual tags
  python scripts/manage_viewpoints.py generate-tags --limit 100

  # Check status
  python scripts/manage_viewpoints.py status

  # Full workflow
  python scripts/manage_viewpoints.py workflow --limit 10
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Init command
    subparsers.add_parser('init', help='Initialize database schema')
    
    # Insert commands
    insert_parser = subparsers.add_parser('insert', help='Insert data')
    insert_subparsers = insert_parser.add_subparsers(dest='insert_type', help='Type of data to insert')
    insert_subparsers.add_parser('osm', help='Insert OSM test data')
    insert_subparsers.add_parser('sample', help='Insert sample data')
    insert_subparsers.add_parser('wiki', help='Insert Wikipedia/Wikidata data')
    commons_parser = insert_subparsers.add_parser('commons', help='Insert Commons assets')
    commons_parser.add_argument('--all', action='store_true', help='Insert all sample assets')
    commons_parser.add_argument('--viewpoint-name', type=str, help='Insert for specific viewpoint')
    
    # Download commands
    download_parser = subparsers.add_parser('download', help='Download images')
    download_subparsers = download_parser.add_subparsers(dest='download_type', help='Type of download')
    images_parser = download_subparsers.add_parser('images', help='Download viewpoint images with metadata')
    images_parser.add_argument('--limit', type=int, help='Limit number of viewpoints')
    images_parser.add_argument('--skip-downloaded', action='store_true', help='Skip already downloaded')
    images_parser.add_argument('--batch-size', type=int, default=50, help='Batch size')
    images_parser.add_argument('--batch-delay', type=float, default=2.0, help='Batch delay in seconds')
    commons_dl_parser = download_subparsers.add_parser('commons', help='Download Commons images')
    commons_dl_parser.add_argument('--limit', type=int, help='Limit number of images')
    commons_dl_parser.add_argument('--skip-downloaded', action='store_true', help='Skip already downloaded')
    commons_dl_parser.add_argument('--viewpoint-id', type=int, help='Download for specific viewpoint')
    
    # Generate commands
    tags_parser = subparsers.add_parser('generate-tags', help='Generate visual tags from Wikipedia')
    tags_parser.add_argument('--limit', type=int, help='Limit number of viewpoints')
    tags_parser.add_argument('--dry-run', action='store_true', help='Dry run without API calls')

    image_tags_parser = subparsers.add_parser('generate-image-tags', help='Generate visual tags from images + history')
    image_tags_parser.add_argument('--image-dir', type=str, default="exports/images/all_image", help='Image directory')
    image_tags_parser.add_argument('--limit', type=int, help='Limit number of viewpoints')
    image_tags_parser.add_argument('--batch-size', type=int, default=50, help='Batch size')
    image_tags_parser.add_argument('--sleep', type=float, default=0.1, help='Delay between API calls')
    image_tags_parser.add_argument('--model', type=str, default=None, help='OpenAI model')
    image_tags_parser.add_argument('--dry-run', action='store_true', help='Dry run without API calls')
    
    # Check commands
    subparsers.add_parser('check-images', help='Check downloaded images')
    subparsers.add_parser('check-completeness', help='Check data completeness')
    subparsers.add_parser('status', help='Show database status')
    
    # Cleanup commands
    cleanup_parser = subparsers.add_parser('cleanup', help='Cleanup incomplete viewpoints')
    cleanup_parser.add_argument('--execute', action='store_true', help='Actually delete (default is dry-run)')
    cleanup_parser.add_argument('--require-history-only', action='store_true', help='Only require history')
    cleanup_parser.add_argument('--require-tags-only', action='store_true', help='Only require tags')
    
    # Remove duplicates command
    remove_dup_parser = subparsers.add_parser('remove-duplicates', help='Remove duplicate viewpoints')
    remove_dup_parser.add_argument('--execute', action='store_true', help='Actually delete (default is dry-run)')
    remove_dup_parser.add_argument('--by-name', action='store_true', help='Find duplicates by name')
    remove_dup_parser.add_argument('--by-wikidata', action='store_true', help='Find duplicates by Wikidata QID')
    remove_dup_parser.add_argument('--by-location', action='store_true', help='Find duplicates by location (SLOW)')
    remove_dup_parser.add_argument('--name-only', action='store_true', default=True, help='Find duplicates by name only (FAST, default)')
    remove_dup_parser.add_argument('--distance-threshold', type=float, default=100.0, help='Distance threshold in meters (default: 100)')
    
    # Workflow command
    workflow_parser = subparsers.add_parser('workflow', help='Run complete workflow')
    workflow_parser.add_argument('--limit', type=int, help='Limit number of viewpoints')
    workflow_parser.add_argument('--skip-init', action='store_true', help='Skip database initialization')
    workflow_parser.add_argument('--skip-insert', action='store_true', help='Skip data insertion')
    workflow_parser.add_argument('--skip-download', action='store_true', help='Skip image download')
    workflow_parser.add_argument('--skip-tags', action='store_true', help='Skip tag generation')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Execute commands
    success = True
    
    if args.command == 'init':
        success = init_database()
    
    elif args.command == 'insert':
        if args.insert_type == 'osm':
            success = insert_osm_data()
        elif args.insert_type == 'sample':
            success = insert_sample_data()
        elif args.insert_type == 'wiki':
            success = insert_wiki_data()
        elif args.insert_type == 'commons':
            success = insert_commons_assets(
                all_assets=args.all,
                viewpoint_name=getattr(args, 'viewpoint_name', None)
            )
        else:
            print("❌ Please specify insert type: osm, sample, wiki, or commons")
            success = False
    
    elif args.command == 'download':
        if args.download_type == 'images':
            success = download_viewpoint_images(
                limit=getattr(args, 'limit', None),
                skip_downloaded=getattr(args, 'skip_downloaded', False),
                batch_size=getattr(args, 'batch_size', 50),
                batch_delay=getattr(args, 'batch_delay', 2.0)
            )
        elif args.download_type == 'commons':
            success = download_commons_images(
                limit=getattr(args, 'limit', None),
                skip_downloaded=getattr(args, 'skip_downloaded', False),
                viewpoint_id=getattr(args, 'viewpoint_id', None)
            )
        else:
            print("❌ Please specify download type: images or commons")
            success = False
    
    elif args.command == 'generate-tags':
        success = generate_visual_tags(
            limit=getattr(args, 'limit', None),
            dry_run=getattr(args, 'dry_run', False)
        )

    elif args.command == 'generate-image-tags':
        success = generate_image_visual_tags(
            image_dir=getattr(args, 'image_dir', None),
            limit=getattr(args, 'limit', None),
            dry_run=getattr(args, 'dry_run', False),
            batch_size=getattr(args, 'batch_size', 50),
            sleep=getattr(args, 'sleep', 0.1),
            model=getattr(args, 'model', None)
        )
    
    elif args.command == 'check-images':
        success = check_downloaded_images()
    
    elif args.command == 'check-completeness':
        success = check_data_completeness()
    
    elif args.command == 'status':
        success = show_status()
    
    elif args.command == 'cleanup':
        success = cleanup_incomplete_viewpoints(
            execute=getattr(args, 'execute', False),
            require_history_only=getattr(args, 'require_history_only', False),
            require_tags_only=getattr(args, 'require_tags_only', False)
        )
    
    elif args.command == 'remove-duplicates':
        success = remove_duplicates(
            execute=getattr(args, 'execute', False),
            by_name=getattr(args, 'by_name', False),
            by_wikidata=getattr(args, 'by_wikidata', False),
            by_location=getattr(args, 'by_location', False),
            name_only=getattr(args, 'name_only', True),
            distance_threshold=getattr(args, 'distance_threshold', 100.0)
        )
    
    elif args.command == 'workflow':
        print_header("Complete Workflow")
        
        # Step 1: Initialize database
        if not getattr(args, 'skip_init', False):
            print_section("Step 1: Initialize Database")
            if not init_database():
                print("⚠️  Database initialization had issues, but continuing...")
        
        # Step 2: Insert data
        if not getattr(args, 'skip_insert', False):
            print_section("Step 2: Insert Data")
            if not insert_osm_data():
                print("⚠️  OSM data insertion had issues, but continuing...")
            if not insert_wiki_data():
                print("⚠️  Wiki data insertion had issues, but continuing...")
        
        # Step 3: Download images
        if not getattr(args, 'skip_download', False):
            print_section("Step 3: Download Images & Metadata")
            download_viewpoint_images(
                limit=getattr(args, 'limit', None),
                skip_downloaded=True,
                batch_size=50,
                batch_delay=2.0
            )
        
        # Step 4: Generate tags
        if not getattr(args, 'skip_tags', False):
            print_section("Step 4: Generate Visual Tags")
            generate_visual_tags(limit=getattr(args, 'limit', None))
        
        # Final status
        print_section("Final Status")
        show_status()
        
        success = True
    
    else:
        print(f"❌ Unknown command: {args.command}")
        parser.print_help()
        success = False
    
    if success:
        print("\n✅ Operation completed successfully!")
    else:
        print("\n❌ Operation completed with errors")
        sys.exit(1)


if __name__ == "__main__":
    main()
