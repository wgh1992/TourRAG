#!/usr/bin/env python3
"""
Export all viewpoint data as a unified CSV file
整合所有景点信息到一个CSV文件中
Usage: python scripts/export_unified_csv.py [--output OUTPUT_FILE]
"""
import os
import sys
import csv
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
import psycopg2


def get_unified_viewpoint_data(cursor) -> List[Dict[str, Any]]:
    """Get all viewpoint data joined from all tables"""
    
    # Query to join all tables and aggregate 1:N relationships
    query = """
    SELECT 
        -- Basic info from viewpoint_entity
        e.viewpoint_id,
        e.name_primary,
        e.name_variants,
        e.osm_type,
        e.osm_id,
        e.category_norm,
        e.category_osm,
        ST_X(e.geom) as longitude,
        ST_Y(e.geom) as latitude,
        ST_AsText(e.geom) as geometry_wkt,
        e.admin_area_ids,
        e.popularity,
        e.created_at as entity_created_at,
        e.updated_at as entity_updated_at,
        
        -- Wikipedia data
        w.wikipedia_title,
        w.wikipedia_lang,
        w.extract_text,
        w.sections as wiki_sections,
        w.citations as wiki_citations,
        w.last_updated as wiki_last_updated,
        w.created_at as wiki_created_at,
        
        -- Wikidata data
        wd.wikidata_qid,
        wd.claims as wikidata_claims,
        wd.sitelinks_count,
        wd.last_updated as wikidata_last_updated,
        wd.created_at as wikidata_created_at,
        
        -- Commons assets (aggregate - take first/most recent)
        ca.viewpoint_country,
        ca.viewpoint_region,
        ca.viewpoint_category_norm as asset_category_norm,
        ca.viewpoint_category_osm as asset_category_osm,
        ca.viewpoint_area_sqm,
        ST_AsText(ca.viewpoint_boundary) as viewpoint_boundary_wkt,
        ca.viewpoint_admin_areas,
        ca.commons_file_id,
        ca.caption as image_caption,
        ca.license as image_license,
        ca.image_width,
        ca.image_height,
        ca.image_format,
        ca.file_size_bytes,
        ca.downloaded_at as image_downloaded_at,
        
        -- Visual tags (aggregate all seasons)
        COALESCE(
            json_agg(
                DISTINCT jsonb_build_object(
                    'season', vt.season,
                    'tags', vt.tags,
                    'confidence', vt.confidence,
                    'tag_source', vt.tag_source
                )
            ) FILTER (WHERE vt.id IS NOT NULL),
            '[]'::json
        ) as visual_tags
        
    FROM viewpoint_entity e
    LEFT JOIN viewpoint_wiki w ON e.viewpoint_id = w.viewpoint_id
    LEFT JOIN viewpoint_wikidata wd ON e.viewpoint_id = wd.viewpoint_id
    LEFT JOIN LATERAL (
        SELECT * FROM viewpoint_commons_assets 
        WHERE viewpoint_id = e.viewpoint_id 
        ORDER BY downloaded_at DESC NULLS LAST
        LIMIT 1
    ) ca ON true
    LEFT JOIN viewpoint_visual_tags vt ON e.viewpoint_id = vt.viewpoint_id
    GROUP BY 
        e.viewpoint_id, e.name_primary, e.name_variants, e.osm_type, e.osm_id,
        e.category_norm, e.category_osm, e.geom, e.admin_area_ids, e.popularity,
        e.created_at, e.updated_at,
        w.wikipedia_title, w.wikipedia_lang, w.extract_text, w.sections, w.citations,
        w.last_updated, w.created_at,
        wd.wikidata_qid, wd.claims, wd.sitelinks_count, wd.last_updated, wd.created_at,
        ca.viewpoint_country, ca.viewpoint_region, ca.viewpoint_category_norm,
        ca.viewpoint_category_osm, ca.viewpoint_area_sqm, ca.viewpoint_boundary,
        ca.viewpoint_admin_areas, ca.commons_file_id, ca.caption, ca.license,
        ca.image_width, ca.image_height, ca.image_format, ca.file_size_bytes,
        ca.downloaded_at
    ORDER BY e.viewpoint_id
    """
    
    cursor.execute(query)
    return cursor.fetchall()


def format_value(value: Any) -> str:
    """Format a value for CSV output"""
    if value is None:
        return ''
    elif isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, (dict, list)):
        # JSON data - convert to JSON string
        return json.dumps(value, ensure_ascii=False)
    elif isinstance(value, bytes):
        # Binary data - skip or indicate presence
        return f'<BINARY_DATA_{len(value)}_BYTES>'
    else:
        return str(value)


def export_unified_csv(cursor, output_file: str):
    """Export unified viewpoint data to CSV"""
    print("正在查询数据库并整合所有景点信息...")
    rows = get_unified_viewpoint_data(cursor)
    
    if not rows:
        print("⚠️  没有找到任何景点数据")
        return
    
    print(f"✓ 找到 {len(rows)} 个景点")
    print(f"正在导出到 CSV 文件: {output_file}")
    
    # Get column names from first row
    if rows:
        columns = list(rows[0].keys())
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            
            for i, row in enumerate(rows, 1):
                # Convert row to dict and format values
                row_dict = {}
                for col in columns:
                    row_dict[col] = format_value(row[col])
                
                writer.writerow(row_dict)
                
                # Progress indicator
                if i % 1000 == 0:
                    print(f"  已处理 {i}/{len(rows)} 个景点...")
        
        print(f"✅ 成功导出 {len(rows)} 个景点到 {output_file}")
        
        # Show file size
        file_size = os.path.getsize(output_file)
        if file_size < 1024:
            size_str = f"{file_size} bytes"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size / (1024 * 1024):.1f} MB"
        print(f"📊 文件大小: {size_str}")
    else:
        print("⚠️  没有数据可导出")


def main():
    parser = argparse.ArgumentParser(
        description='Export all viewpoint data as a unified CSV file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export to default file
  python scripts/export_unified_csv.py
  
  # Export to custom file
  python scripts/export_unified_csv.py --output viewpoints_all.csv
  
  # Export to timestamped file
  python scripts/export_unified_csv.py --output exports/viewpoints_$(date +%Y%m%d_%H%M%S).csv
        """
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output CSV file path (default: exports/viewpoints_unified_YYYYMMDD_HHMMSS.csv)'
    )
    
    args = parser.parse_args()
    
    # Determine output file
    if args.output:
        output_file = Path(args.output)
    else:
        # Default: timestamped file in exports directory
        exports_dir = Path('exports')
        exports_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = exports_dir / f'viewpoints_unified_{timestamp}.csv'
    
    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    print("=" * 80)
    print("景点数据统一导出工具")
    print("=" * 80)
    print(f"输出文件: {output_file}")
    print()
    
    try:
        with db.get_cursor() as cursor:
            export_unified_csv(cursor, str(output_file))
            
            print()
            print("=" * 80)
            print("✅ 导出完成！")
            print(f"📁 文件位置: {output_file.absolute()}")
            print()
            print("💡 提示:")
            print("   - CSV文件包含所有景点的完整信息")
            print("   - 包括基本信息、Wikipedia、Wikidata、图像元数据和视觉标签")
            print("   - JSON字段（如name_variants、visual_tags）以JSON字符串格式存储")
            print("   - 几何数据以WKT格式存储")
    
    except Exception as e:
        print(f"❌ 导出过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
