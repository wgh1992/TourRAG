#!/usr/bin/env python3
"""
Download only attraction type viewpoints from OSM with Wikipedia/Wikidata filtering

This script downloads only tourism=attraction or tourism=viewpoint from OSM,
with optional filtering for Wikipedia/Wikidata tags and English names.

只下载attraction类型景点，支持Wikipedia/Wikidata过滤和批量区域下载
"""
import sys
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor

# Overpass API endpoint
OVERPASS_API = "https://overpass-api.de/api/interpreter"

# Global regions for batch download
REGIONS = {
    "china": {
        "bbox": "73.66,18.19,135.05,53.56",
        "limit": None,
        "name": "中国"
    },
    "europe": {
        "bbox": "-10.0,35.0,40.0,70.0",
        "limit": None,
        "name": "欧洲"
    },
    "north_america": {
        "bbox": "-170.0,15.0,-50.0,72.0",
        "limit": None,
        "name": "北美"
    },
    "south_america": {
        "bbox": "-85.0,-56.0,-32.0,13.0",
        "limit": None,
        "name": "南美"
    },
    "asia_other": {
        "bbox": "100.0,-10.0,150.0,50.0",
        "limit": None,
        "name": "亚洲其他地区"
    },
    "middle_east_africa": {
        "bbox": "-20.0,-35.0,60.0,40.0",
        "limit": None,
        "name": "中东和非洲"
    }
}


def build_overpass_query_attraction(
    bbox: Tuple[float, float, float, float],
    require_wikipedia: bool = False,
    require_wikidata: bool = False,
    require_name_en: bool = False,
    limit: Optional[int] = None
) -> str:
    """
    Build Overpass QL query to fetch ONLY attraction/viewpoint type
    bbox format: (min_lat, min_lon, max_lat, max_lon)
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    
    # Build filter conditions
    filters = []
    if require_wikipedia:
        filters.append('["wikipedia"]')
    if require_wikidata:
        filters.append('["wikidata"]')
    
    filter_str = "".join(filters) if filters else ""
    
    # Query: only tourism=attraction or tourism=viewpoint
    # Use limit in query if specified, otherwise omit it (no limit)
    limit_str = f" {limit}" if limit else ""
    query = f"""
[out:json][timeout:300];
(
  node["tourism"~"^(attraction|viewpoint)$"]{filter_str}({min_lat},{min_lon},{max_lat},{max_lon});
  way["tourism"~"^(attraction|viewpoint)$"]{filter_str}({min_lat},{min_lon},{max_lat},{max_lon});
);
out body{limit_str};
>;
out skel qt;
"""
    return query


def get_region_bbox(region: str) -> Tuple[float, float, float, float]:
    """Get bounding box for a region"""
    if region in REGIONS:
        bbox_str = REGIONS[region]["bbox"]
        parts = [float(x.strip()) for x in bbox_str.split(",")]
        # Format: min_lon,min_lat,max_lon,max_lat -> convert to min_lat,min_lon,max_lat,max_lon
        return (parts[1], parts[0], parts[3], parts[2])
    
    # Fallback to common regions
    regions = {
        "europe": (35.0, -10.0, 70.0, 40.0),
        "asia": (5.0, 60.0, 50.0, 150.0),
        "north_america": (15.0, -180.0, 72.0, -50.0),
        "south_america": (-60.0, -90.0, 15.0, -30.0),
        "africa": (-35.0, -20.0, 38.0, 55.0),
        "oceania": (-50.0, 110.0, 0.0, 180.0),
        "japan": (24.2, 122.9, 45.5, 153.9),
        "china": (18.2, 73.7, 53.6, 135.0),
        "usa": (25.0, -125.0, 49.4, -66.9),
    }
    
    bbox = regions.get(region.lower())
    if not bbox:
        raise ValueError(f"Unknown region: {region}. Available: {list(regions.keys())}")
    
    return bbox


def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
    """Parse bounding box string"""
    parts = [float(x.strip()) for x in bbox_str.split(",")]
    if len(parts) != 4:
        raise ValueError("Bbox must be 'min_lat,min_lon,max_lat,max_lon' or 'min_lon,min_lat,max_lon,max_lat'")
    
    if abs(parts[0]) > 90:
        return (parts[1], parts[0], parts[3], parts[2])
    else:
        return tuple(parts)


def fetch_osm_data(
    bbox: Tuple[float, float, float, float],
    require_wikipedia: bool = False,
    require_wikidata: bool = False,
    require_name_en: bool = False,
    limit: Optional[int] = None,
    max_retries: int = 3
) -> List[Dict[str, Any]]:
    """Fetch OSM data from Overpass API"""
    query = build_overpass_query_attraction(
        bbox, require_wikipedia, require_wikidata, require_name_en, limit
    )
    
    print(f"  Querying Overpass API...")
    print(f"  Bbox: {bbox}")
    print(f"  Limit: {limit if limit else 'None (no limit)'}")
    print(f"  Require Wikipedia: {require_wikipedia}")
    print(f"  Require Wikidata: {require_wikidata}")
    
    for attempt in range(max_retries):
        try:
            print(f"  Attempt {attempt + 1}/{max_retries}...")
            
            timeout = 90 if attempt > 0 else 60
            response = requests.post(
                OVERPASS_API,
                data={"data": query},
                headers={"User-Agent": "TourRAG/1.0 (contact@example.com)"},
                timeout=timeout
            )
            response.raise_for_status()
            
            data = response.json()
            if "elements" not in data:
                print("⚠️  No elements in response")
                return []
            
            elements = data["elements"]
            print(f"  [INFO] 收到 {len(elements)} 个OSM元素")
            return elements
        
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 10
                print(f"⚠️  Timeout, waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ Timeout after {max_retries} attempts")
                return []
        
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5
                print(f"⚠️  Error: {e}, waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ Error after {max_retries} attempts: {e}")
                return []
    
    return []


def convert_osm_element(element: Dict[str, Any], require_name_en: bool = False) -> Optional[Dict[str, Any]]:
    """Convert OSM element to viewpoint format, only for attraction/viewpoint"""
    tags = element.get("tags", {})
    
    # Check if it's attraction or viewpoint
    tourism = tags.get("tourism", "").lower()
    if tourism not in ["attraction", "viewpoint"]:
        return None
    
    # Extract name
    name = None
    if require_name_en:
        name = tags.get("name:en") or tags.get("name")
    else:
        name_fields = ["name", "name:en", "name:primary", "official_name", "alt_name"]
        for field in name_fields:
            if field in tags and tags[field]:
                name = tags[field]
                break
    
    if not name:
        return None
    
    # Extract coordinates
    if element["type"] == "node":
        lon, lat = element.get("lon"), element.get("lat")
    elif element["type"] == "way":
        if "center" in element:
            lon, lat = element["center"].get("lon"), element["center"].get("lat")
        elif "geometry" in element and element["geometry"]:
            lons = [p["lon"] for p in element["geometry"] if "lon" in p]
            lats = [p["lat"] for p in element["geometry"] if "lat" in p]
            if lons and lats:
                lon, lat = sum(lons) / len(lons), sum(lats) / len(lats)
            else:
                return None
        else:
            return None
    elif element["type"] == "relation":
        if "center" in element:
            lon, lat = element["center"].get("lon"), element["center"].get("lat")
        else:
            return None
    else:
        return None
    
    if not lon or not lat:
        return None
    
    # Build name variants
    name_variants = {}
    for key, value in tags.items():
        if key.startswith("name:") and value:
            name_variants[key] = value
    
    # Build category_osm
    category_osm = {"tourism": tourism}
    
    # Calculate popularity (simplified)
    popularity = 0.5
    if tags.get("wikipedia") or tags.get("wikidata"):
        popularity = 0.7
    
    return {
        "osm_type": element["type"],
        "osm_id": element["id"],
        "name_primary": name,
        "name_variants": name_variants,
        "category_osm": category_osm,
        "category_norm": "attraction",  # Always attraction for this script
        "geom": f"POINT({lon} {lat})",
        "admin_area_ids": [],
        "popularity": popularity
    }


def insert_viewpoints(viewpoints: List[Dict[str, Any]], batch_size: int = 100) -> int:
    """Insert viewpoints into database"""
    inserted = 0
    
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            for i in range(0, len(viewpoints), batch_size):
                batch = viewpoints[i:i + batch_size]
                
                for vp in batch:
                    try:
                        cursor.execute("""
                            INSERT INTO viewpoint_entity (
                                osm_type, osm_id, name_primary, name_variants,
                                category_osm, category_norm, geom, admin_area_ids, popularity
                            ) VALUES (%s, %s, %s, %s, %s, %s, ST_GeomFromText(%s, 4326), %s, %s)
                            ON CONFLICT (osm_type, osm_id) DO NOTHING
                            RETURNING viewpoint_id
                        """, (
                            vp["osm_type"],
                            vp["osm_id"],
                            vp["name_primary"],
                            json.dumps(vp["name_variants"]),
                            json.dumps(vp["category_osm"]),
                            vp["category_norm"],
                            vp["geom"],
                            json.dumps(vp["admin_area_ids"]),
                            vp["popularity"]
                        ))
                        
                        if cursor.fetchone():
                            inserted += 1
                    except Exception as e:
                        continue
                
                conn.commit()
    
    return inserted


def download_region(
    region: str,
    require_wikipedia: bool = False,
    require_wikidata: bool = False,
    require_name_en: bool = False,
    limit: Optional[int] = None
) -> int:
    """Download attractions from a single region"""
    bbox = get_region_bbox(region)
    region_name = REGIONS.get(region, {}).get("name", region)
    
    print(f"\n{'='*70}")
    print(f"下载 {region_name} 的attraction类型景点...")
    print(f"  Bbox: {bbox}")
    if limit:
        print(f"  限制数量: {limit}")
    
    # Use limit if specified, otherwise use a large number (effectively no limit for Overpass)
    query_limit = limit if limit else 999999999  # Very large number for "no limit"
    elements = fetch_osm_data(
        bbox, require_wikipedia, require_wikidata, require_name_en, query_limit
    )
    
    if not elements:
        print(f"  ⚠️  {region_name}: 没有获取到数据")
        return 0
    
    # Convert to viewpoints
    viewpoints = []
    for element in elements:
        vp = convert_osm_element(element, require_name_en)
        if vp:
            viewpoints.append(vp)
    
    print(f"  ✓ 转换为 {len(viewpoints)} 个attraction类型景点")
    
    # Limit if needed
    if limit and len(viewpoints) > limit:
        viewpoints = viewpoints[:limit]
        print(f"  ✓ 限制为前 {limit} 个景点")
    
    # Insert into database
    inserted = insert_viewpoints(viewpoints)
    print(f"  ✅ {region_name}: 成功收集 {inserted} 个景点")
    
    return inserted


def main():
    parser = argparse.ArgumentParser(
        description='Download only attraction type viewpoints from OSM',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--region', type=str, help='Region name (e.g., europe, china)')
    parser.add_argument('--bbox', type=str, help='Bounding box: min_lon,min_lat,max_lon,max_lat')
    parser.add_argument('--batch-regions', action='store_true',
                       help='Batch download from multiple regions')
    parser.add_argument('--require-wikipedia', action='store_true',
                       help='Require Wikipedia tag')
    parser.add_argument('--require-wikidata', action='store_true',
                       help='Require Wikidata tag')
    parser.add_argument('--require-name-en', action='store_true',
                       help='Require English name')
    parser.add_argument('--limit', type=int, default=None,
                       help='Maximum number per region (default: None, no limit)')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='Batch size for insertion')
    parser.add_argument('--yes', action='store_true',
                       help='Skip confirmation')
    
    args = parser.parse_args()
    
    if not args.region and not args.bbox and not args.batch_regions:
        parser.error("Must specify --region, --bbox, or --batch-regions")
    
    print("=" * 70)
    print("Download Attraction-Only Viewpoints from OSM")
    print("=" * 70)
    
    total_inserted = 0
    
    if args.batch_regions:
        # Batch download from all regions (no limit if args.limit is None)
        limit_text = f"每个区域限制: {args.limit}" if args.limit else "无限制（下载所有可用景点）"
        print(f"\n批量下载多个区域（{limit_text}）")
        if not args.yes:
            response = input("Continue? (yes/no): ")
            if response.lower() not in ['yes', 'y']:
                return
        
        for region in REGIONS.keys():
            inserted = download_region(
                region,
                args.require_wikipedia,
                args.require_wikidata,
                args.require_name_en,
                args.limit
            )
            total_inserted += inserted
            time.sleep(2)  # Rate limiting
    
    elif args.bbox:
        # Custom bbox
        bbox = parse_bbox(args.bbox)
        print(f"\n使用自定义bbox: {bbox}")
        
        elements = fetch_osm_data(
            bbox, args.require_wikipedia, args.require_wikidata,
            args.require_name_en, args.limit
        )
        
        viewpoints = []
        for element in elements:
            vp = convert_osm_element(element, args.require_name_en)
            if vp:
                viewpoints.append(vp)
        
        print(f"✓ 转换为 {len(viewpoints)} 个attraction类型景点")
        
        if args.limit and len(viewpoints) > args.limit:
            viewpoints = viewpoints[:args.limit]
            print(f"✓ 限制为前 {args.limit} 个景点")
        
        total_inserted = insert_viewpoints(viewpoints, args.batch_size)
        print(f"✅ 成功插入 {total_inserted} 个景点")
    
    else:
        # Single region
        total_inserted = download_region(
            args.region,
            args.require_wikipedia,
            args.require_wikidata,
            args.require_name_en,
            args.limit
        )
    
    print(f"\n{'='*70}")
    print(f"总计: 成功插入 {total_inserted} 个attraction类型景点")
    print("=" * 70)


if __name__ == "__main__":
    main()
