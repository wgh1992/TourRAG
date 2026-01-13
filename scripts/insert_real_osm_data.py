#!/usr/bin/env python3
"""
Insert REAL OSM viewpoint data from Overpass API

This script fetches real tourist attractions from OpenStreetMap using Overpass API
and inserts them into the database.

Usage:
    python scripts/insert_real_osm_data.py --region europe --limit 1000
    python scripts/insert_real_osm_data.py --bbox "37.7,55.6,37.8,55.7" --limit 100
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
# Alternative: "https://overpass.kumi.systems/api/interpreter"

# Tourism-related OSM tags
TOURISM_TAGS = [
    "attraction",
    "viewpoint",
    "museum",
    "gallery",
    "monument",
    "memorial",
    "artwork",
    "tower",
    "castle",
    "palace",
    "ruins",
    "archaeological_site",
    "zoo",
    "theme_park",
    "aquarium"
]

# Natural features
NATURAL_TAGS = [
    "peak",
    "volcano",
    "cave_entrance",
    "beach",
    "cliff",
    "waterfall"
]

# Historic features
HISTORIC_TAGS = [
    "monument",
    "memorial",
    "castle",
    "palace",
    "ruins",
    "archaeological_site",
    "tomb",
    "tower"
]


def get_region_bbox(region: str) -> Tuple[float, float, float, float]:
    """
    Get bounding box for a region
    
    Returns: (min_lat, min_lon, max_lat, max_lon) for Overpass API
    """
    regions = {
        "europe": (35.0, -10.0, 70.0, 40.0),
        "asia": (5.0, 60.0, 50.0, 150.0),
        "north_america": (15.0, -180.0, 72.0, -50.0),
        "south_america": (-60.0, -90.0, 15.0, -30.0),
        "africa": (-35.0, -20.0, 38.0, 55.0),
        "oceania": (-50.0, 110.0, 0.0, 180.0),
        "italy": (36.6, 6.6, 47.1, 18.5),
        "france": (41.3, -5.0, 51.1, 9.6),
        "spain": (35.2, -9.3, 43.8, 4.3),
        "germany": (47.3, 5.9, 55.1, 15.0),
        "japan": (24.2, 122.9, 45.5, 153.9),
        "china": (18.2, 73.7, 53.6, 135.0),
        "usa": (25.0, -125.0, 49.4, -66.9),
    }
    
    bbox = regions.get(region.lower())
    if not bbox:
        raise ValueError(f"Unknown region: {region}. Available: {list(regions.keys())}")
    
    return bbox


def parse_bbox(bbox_str: str) -> Tuple[float, float, float, float]:
    """
    Parse bounding box string "min_lat,min_lon,max_lat,max_lon" (for Overpass)
    or "min_lon,min_lat,max_lon,max_lat" (standard format)
    """
    parts = [float(x.strip()) for x in bbox_str.split(",")]
    if len(parts) != 4:
        raise ValueError("Bbox must be 'min_lat,min_lon,max_lat,max_lon' or 'min_lon,min_lat,max_lon,max_lat'")
    
    # Auto-detect format: if first value is negative and large, assume lon format
    if abs(parts[0]) > 90:
        # Standard format: min_lon,min_lat,max_lon,max_lat -> convert to lat,lon,lat,lon
        return (parts[1], parts[0], parts[3], parts[2])
    else:
        # Already in lat,lon format
        return tuple(parts)


def build_overpass_query(bbox: Tuple[float, float, float, float], limit: int = 1000, query_type: str = "tourism") -> str:
    """
    Build Overpass QL query to fetch tourist attractions
    bbox format: (min_lat, min_lon, max_lat, max_lon)
    query_type: "tourism", "natural", "historic", or "all"
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    
    # Use simpler queries to avoid timeout - query one type at a time
    if query_type == "tourism":
        # Focus on specific tourism tags that are more common
        query = f"""
[out:json][timeout:25];
(
  node["tourism"~"^(attraction|museum|gallery|monument|memorial|viewpoint|artwork|tower|castle|palace|zoo|theme_park)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["tourism"~"^(attraction|museum|gallery|monument|memorial|viewpoint|artwork|tower|castle|palace|zoo|theme_park)$"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out body;
>;
out skel qt;
"""
    elif query_type == "natural":
        query = f"""
[out:json][timeout:25];
(
  node["natural"~"^(water|peak|volcano|cave_entrance|waterfall|beach|cliff)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["natural"~"^(water|peak|volcano|cave_entrance|waterfall|beach|cliff)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  relation["natural"~"^(water)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  node["water"~"^(lake|reservoir|pond)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["water"~"^(lake|reservoir|pond)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  relation["water"~"^(lake|reservoir|pond)$"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out body {limit};
>;
out skel qt;
"""
    elif query_type == "historic":
        query = f"""
[out:json][timeout:25];
(
  node["historic"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["historic"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out body {limit};
>;
out skel qt;
"""
    else:
        # All types but simplified - use smaller queries to avoid timeout
        # For large regions like China, query types separately is better
        # This "all" query is simplified and may timeout for very large areas
        query = f"""
[out:json][timeout:60];
(
  node["tourism"~"^(attraction|museum|gallery|monument|memorial|viewpoint|artwork|tower|castle|palace|zoo|theme_park)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["tourism"~"^(attraction|museum|gallery|monument|memorial|viewpoint|artwork|tower|castle|palace|zoo|theme_park)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  node["natural"~"^(water|peak|volcano|cave_entrance|waterfall|beach|cliff)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["natural"~"^(water|peak|volcano|cave_entrance|waterfall|beach|cliff)$"]({min_lat},{min_lon},{max_lat},{max_lon});
  node["historic"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["historic"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out body {limit};
>;
out skel qt;
"""
    return query


def fetch_osm_data(bbox: Tuple[float, float, float, float], limit: int = 1000, query_type: str = "tourism", max_retries: int = 3) -> List[Dict[str, Any]]:
    """
    Fetch OSM data from Overpass API with retry mechanism
    """
    query = build_overpass_query(bbox, limit, query_type)
    
    print(f"Querying Overpass API...")
    print(f"  Bbox: {bbox}")
    print(f"  Limit: {limit}")
    print(f"  Type: {query_type}")
    
    all_elements = []
    
    for attempt in range(max_retries):
        try:
            print(f"  Attempt {attempt + 1}/{max_retries}...")
            
            # Use longer timeout for retries
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
            print(f"✓ Fetched {len(elements)} elements from OSM")
            return elements
        
        except requests.exceptions.Timeout as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 10
                print(f"⚠️  Timeout (attempt {attempt + 1}/{max_retries}), waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                print(f"❌ Timeout after {max_retries} attempts")
                # Try with smaller limit
                if limit > 100:
                    print(f"  Trying with smaller limit (100)...")
                    return fetch_osm_data(bbox, limit=100, query_type=query_type, max_retries=1)
                return []
        
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5
                print(f"⚠️  Error (attempt {attempt + 1}/{max_retries}): {e}")
                print(f"  Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                print(f"❌ Error fetching OSM data after {max_retries} attempts: {e}")
                return []
    
    return []


def normalize_category(tags: Dict[str, str]) -> str:
    """
    Normalize OSM tags to our category system
    """
    # Check tourism tags first
    tourism = tags.get("tourism", "").lower()
    if tourism in ["attraction", "viewpoint"]:
        return "attraction"
    elif tourism == "museum":
        return "museum"
    elif tourism == "gallery":
        return "museum"
    elif tourism == "monument":
        return "monument"
    elif tourism == "memorial":
        return "monument"
    elif tourism == "artwork":
        return "monument"
    elif tourism == "tower":
        return "tower"
    elif tourism == "castle":
        return "palace"
    elif tourism == "palace":
        return "palace"
    elif tourism == "zoo":
        return "park"
    elif tourism == "theme_park":
        return "park"
    
    # Check natural tags
    natural = tags.get("natural", "").lower()
    if natural == "peak":
        return "mountain"
    elif natural == "volcano":
        return "mountain"
    elif natural == "cave_entrance":
        return "cave"
    elif natural == "beach":
        return "coast"
    elif natural == "cliff":
        return "coast"
    elif natural == "waterfall":
        return "waterfall"
    elif natural == "water":
        # Check water type to determine if it's a lake
        water_type = tags.get("water", "").lower()
        if water_type in ["lake", "reservoir", "pond"]:
            return "lake"
        # If natural=water but no water tag, still treat as lake if it has a name
        if tags.get("name"):
            return "lake"
    
    # Check water tag directly (some lakes are tagged with water=lake without natural=water)
    water_type = tags.get("water", "").lower()
    if water_type in ["lake", "reservoir", "pond"]:
        return "lake"
    
    # Check historic tags
    historic = tags.get("historic", "").lower()
    if historic == "monument":
        return "monument"
    elif historic == "memorial":
        return "monument"
    elif historic == "castle":
        return "palace"
    elif historic == "palace":
        return "palace"
    elif historic == "ruins":
        return "monument"
    elif historic == "archaeological_site":
        return "monument"
    elif historic == "tower":
        return "tower"
    
    # Check other tags
    if tags.get("amenity") == "place_of_worship":
        return "temple"
    elif tags.get("leisure") == "park":
        return "park"
    elif tags.get("man_made") == "bridge":
        return "bridge"
    elif tags.get("waterway") == "waterfall":
        return "waterfall"
    
    # Default
    return "attraction"


def extract_name(tags: Dict[str, str]) -> Optional[str]:
    """
    Extract primary name from OSM tags
    """
    # Try different name fields in order of preference
    name_fields = ["name", "name:en", "name:primary", "official_name", "alt_name"]
    
    for field in name_fields:
        if field in tags and tags[field]:
            return tags[field]
    
    return None


def extract_coordinates(element: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """
    Extract coordinates from OSM element
    """
    if element["type"] == "node":
        return (element.get("lon"), element.get("lat"))
    elif element["type"] == "way":
        # For ways, use center point (simplified - should calculate centroid)
        if "center" in element:
            return (element["center"].get("lon"), element["center"].get("lat"))
        elif "geometry" in element and element["geometry"]:
            # Calculate centroid from geometry
            lons = [p["lon"] for p in element["geometry"] if "lon" in p]
            lats = [p["lat"] for p in element["geometry"] if "lat" in p]
            if lons and lats:
                return (sum(lons) / len(lons), sum(lats) / len(lats))
    elif element["type"] == "relation":
        # For relations, use center if available
        if "center" in element:
            return (element["center"].get("lon"), element["center"].get("lat"))
    
    return None


def convert_osm_element(element: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Convert OSM element to our viewpoint format
    """
    tags = element.get("tags", {})
    
    # Extract name
    name = extract_name(tags)
    if not name:
        return None  # Skip elements without names
    
    # Extract coordinates
    coords = extract_coordinates(element)
    if not coords:
        return None  # Skip elements without coordinates
    
    lon, lat = coords
    
    # Normalize category
    category = normalize_category(tags)
    
    # Build OSM category tags
    category_osm = {}
    if "tourism" in tags:
        category_osm["tourism"] = tags["tourism"]
    if "natural" in tags:
        category_osm["natural"] = tags["natural"]
    if "historic" in tags:
        category_osm["historic"] = tags["historic"]
    if "amenity" in tags:
        category_osm["amenity"] = tags["amenity"]
    if "leisure" in tags:
        category_osm["leisure"] = tags["leisure"]
    
    # Build name variants
    name_variants = {}
    for key, value in tags.items():
        if key.startswith("name:") and value:
            name_variants[key] = value
    
    # Extract admin area IDs (if available)
    admin_area_ids = []
    if "admin_level" in tags:
        admin_area_ids.append({"admin_level": tags["admin_level"]})
    
    # Calculate popularity (simplified - could use OSM visit count if available)
    popularity = 0.5  # Default, could be improved
    
    return {
        "osm_type": element["type"],
        "osm_id": element["id"],
        "name_primary": name,
        "name_variants": name_variants,
        "category_osm": category_osm,
        "category_norm": category,
        "geom": f"POINT({lon} {lat})",
        "admin_area_ids": admin_area_ids,
        "popularity": popularity
    }


def insert_viewpoints(viewpoints: List[Dict[str, Any]], batch_size: int = 100) -> int:
    """
    Insert viewpoints into database
    """
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
                        print(f"  ⚠️  Error inserting {vp.get('name_primary', 'unknown')}: {e}")
                        continue
                
                conn.commit()
                
                if (i + batch_size) % 500 == 0:
                    print(f"  Progress: {min(i + batch_size, len(viewpoints))}/{len(viewpoints)} processed, {inserted} inserted")
    
    return inserted


def main():
    parser = argparse.ArgumentParser(description='Insert real OSM data from Overpass API')
    parser.add_argument('--region', type=str, help='Region name (e.g., europe, italy, japan)')
    parser.add_argument('--bbox', type=str, help='Bounding box: min_lat,min_lon,max_lat,max_lon')
    parser.add_argument('--limit', type=int, default=500, help='Maximum number of elements to fetch per query (default: 500)')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for insertion')
    parser.add_argument('--type', type=str, default='tourism', choices=['tourism', 'natural', 'historic', 'all'],
                       help='Type of features to query (default: tourism)')
    parser.add_argument('--retries', type=int, default=3, help='Number of retry attempts (default: 3)')
    
    args = parser.parse_args()
    
    if not args.region and not args.bbox:
        parser.error("Must specify either --region or --bbox")
    
    # Get bounding box
    if args.bbox:
        bbox = parse_bbox(args.bbox)
    else:
        bbox = get_region_bbox(args.region)
    
    print("=" * 70)
    print("Insert Real OSM Data from Overpass API")
    print("=" * 70)
    print()
    
    # Fetch OSM data with retries
    elements = fetch_osm_data(bbox, args.limit, args.type, args.retries)
    
    if not elements:
        print("❌ No data fetched. Exiting.")
        print("\n💡 Tips:")
        print("  - Try a smaller region (e.g., --region italy instead of europe)")
        print("  - Reduce limit (e.g., --limit 100)")
        print("  - Try different type (e.g., --type tourism)")
        return
    
    # Convert to viewpoints
    print(f"\nConverting {len(elements)} OSM elements to viewpoints...")
    viewpoints = []
    for element in elements:
        vp = convert_osm_element(element)
        if vp:
            # Filter: only keep attraction category
            if vp.get('category_norm') == 'attraction':
                viewpoints.append(vp)
    
    print(f"✓ Converted {len(viewpoints)} valid attraction viewpoints")
    
    if not viewpoints:
        print("⚠️  No valid viewpoints extracted. Check OSM data format.")
        return
    
    # Insert into database
    print(f"\nInserting viewpoints into database...")
    inserted = insert_viewpoints(viewpoints, args.batch_size)
    
    print(f"\n✅ Inserted {inserted} new viewpoints")
    print(f"   Total processed: {len(viewpoints)}")
    print(f"   Skipped (duplicates): {len(viewpoints) - inserted}")


if __name__ == "__main__":
    main()
