#!/usr/bin/env python3
"""
Insert OSM viewpoint data for testing (5000 records)

This script generates realistic OSM-style test data and inserts into the database.
For production, you would fetch real data from OSM Overpass API or OSM extracts.
"""
import sys
import json
import random
from pathlib import Path
from typing import List, Dict, Any
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db

# Sample data templates
CATEGORIES = [
    "mountain", "lake", "temple", "museum", "park", "coast", 
    "cityscape", "monument", "bridge", "palace", "tower", 
    "cave", "waterfall", "valley", "island"
]

OSM_TYPES = ["node", "way", "relation"]

# Popular tourist destinations for realistic names
PLACE_NAMES = [
    # Mountains
    "Mount Fuji", "Mount Everest", "Mount Kilimanjaro", "Mount Rainier", "Mount Whitney",
    "Mount McKinley", "Mount Elbrus", "Mount Blanc", "Matterhorn", "Mount Cook",
    # Temples
    "Senso-ji Temple", "Fushimi Inari Shrine", "Todai-ji Temple", "Kiyomizu-dera",
    "Golden Temple", "Angkor Wat", "Borobudur", "Wat Pho", "Temple of Heaven",
    # Museums
    "Louvre Museum", "British Museum", "Metropolitan Museum", "Uffizi Gallery",
    "Hermitage Museum", "Prado Museum", "Rijksmuseum", "National Gallery",
    # Parks
    "Central Park", "Hyde Park", "Yoyogi Park", "Ueno Park", "Golden Gate Park",
    "Stanley Park", "Griffith Park", "Regent's Park", "Bois de Boulogne",
    # Towers
    "Eiffel Tower", "Tokyo Skytree", "CN Tower", "Burj Khalifa", "Shanghai Tower",
    "Petronas Towers", "Taipei 101", "One World Trade Center",
    # Bridges
    "Golden Gate Bridge", "Tower Bridge", "Brooklyn Bridge", "Sydney Harbour Bridge",
    "Millau Viaduct", "Akashi Kaikyo Bridge", "Great Belt Bridge",
    # Others
    "Grand Canyon", "Niagara Falls", "Victoria Falls", "Iguazu Falls",
    "Great Barrier Reef", "Santorini", "Bali", "Maldives", "Bora Bora"
]

COUNTRIES = [
    "Japan", "China", "USA", "France", "Italy", "UK", "Spain", "Germany",
    "Thailand", "Indonesia", "India", "Australia", "New Zealand", "Canada",
    "Brazil", "Argentina", "Chile", "Peru", "Mexico", "Greece", "Turkey"
]

CITIES = [
    "Tokyo", "Kyoto", "Osaka", "Paris", "London", "New York", "Los Angeles",
    "San Francisco", "Sydney", "Melbourne", "Bangkok", "Singapore", "Hong Kong",
    "Shanghai", "Beijing", "Seoul", "Barcelona", "Rome", "Venice", "Florence",
    "Amsterdam", "Berlin", "Vienna", "Prague", "Istanbul", "Dubai", "Cairo"
]


def generate_osm_id() -> int:
    """Generate a realistic OSM ID"""
    return random.randint(1000000, 999999999)


def generate_name_variants(name: str, category: str) -> Dict[str, str]:
    """Generate name variants in multiple languages"""
    variants = {
        "name:en": name,
        "name:primary": name
    }
    
    # Add some Chinese names for certain categories
    if random.random() < 0.3:
        variants["name:zh"] = f"{name} (中文)"
    
    # Add Japanese names for Japan-related places
    if random.random() < 0.2:
        variants["name:ja"] = f"{name} (日本語)"
    
    # Add alt_name sometimes
    if random.random() < 0.2:
        variants["alt_name"] = f"{name} (Alternative)"
    
    return variants


def generate_category_osm(category_norm: str) -> Dict[str, str]:
    """Generate OSM category tags based on normalized category"""
    category_map = {
        "mountain": {"natural": "peak", "tourism": "attraction"},
        "lake": {"natural": "water", "water": "lake"},
        "temple": {"amenity": "place_of_worship", "religion": "buddhist"},
        "museum": {"tourism": "museum"},
        "park": {"leisure": "park"},
        "coast": {"natural": "coastline"},
        "cityscape": {"place": "city"},
        "monument": {"historic": "monument"},
        "bridge": {"man_made": "bridge"},
        "palace": {"historic": "palace"},
        "tower": {"man_made": "tower"},
        "cave": {"natural": "cave"},
        "waterfall": {"waterway": "waterfall"},
        "valley": {"natural": "valley"},
        "island": {"place": "island"}
    }
    return category_map.get(category_norm, {"tourism": "attraction"})


def generate_geometry() -> str:
    """Generate a random point geometry (simplified)"""
    # Realistic coordinate ranges
    lon = random.uniform(-180, 180)
    lat = random.uniform(-90, 90)
    return f"POINT({lon} {lat})"


def generate_viewpoint_data(index: int) -> Dict[str, Any]:
    """Generate a single viewpoint data record"""
    # Select category
    category = random.choice(CATEGORIES)
    
    # Generate name
    if index < len(PLACE_NAMES):
        base_name = PLACE_NAMES[index % len(PLACE_NAMES)]
        if index >= len(PLACE_NAMES):
            base_name = f"{base_name} {index // len(PLACE_NAMES) + 1}"
    else:
        # Generate synthetic names
        city = random.choice(CITIES)
        if category == "mountain":
            base_name = f"{city} Mountain"
        elif category == "temple":
            base_name = f"{city} Temple"
        elif category == "park":
            base_name = f"{city} Park"
        elif category == "museum":
            base_name = f"{city} Museum"
        else:
            base_name = f"{city} {category.title()}"
    
    # Generate OSM data
    osm_type = random.choice(OSM_TYPES)
    osm_id = generate_osm_id()
    
    name_variants = generate_name_variants(base_name, category)
    category_osm = generate_category_osm(category)
    
    # Generate admin area IDs (simplified)
    admin_area_ids = [random.randint(1, 1000) for _ in range(random.randint(1, 3))]
    
    # Generate popularity (0.0 to 1.0)
    popularity = random.uniform(0.1, 1.0)
    
    return {
        "osm_type": osm_type,
        "osm_id": osm_id,
        "name_primary": base_name,
        "name_variants": name_variants,
        "category_osm": category_osm,
        "category_norm": category,
        "geom": generate_geometry(),
        "admin_area_ids": admin_area_ids,
        "popularity": round(popularity, 3)
    }


def insert_viewpoints_batch(viewpoints: List[Dict[str, Any]], batch_size: int = 100):
    """Insert viewpoints in batches"""
    total = len(viewpoints)
    inserted = 0
    
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                for i in range(0, total, batch_size):
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
                            
                            result = cursor.fetchone()
                            if result:
                                inserted += 1
                        except Exception as e:
                            print(f"Error inserting {vp['name_primary']}: {e}")
                            continue
                    
                    conn.commit()
                    if (i + batch_size) % 500 == 0:
                        print(f"Progress: {min(i + batch_size, total)}/{total} processed, {inserted} inserted")
        
        return inserted
    except Exception as e:
        print(f"Error in batch insert: {e}")
        import traceback
        traceback.print_exc()
        return inserted


def insert_sample_visual_tags(viewpoint_ids: List[int], sample_count: int = 1000):
    """Insert sample visual tags for some viewpoints"""
    seasons = ["spring", "summer", "autumn", "winter", "unknown"]
    tag_sources = ["commons_vision", "wiki_weak_supervision", "manual"]
    
    visual_tag_templates = {
        "mountain": {
            "winter": ["snow_peak", "mountain", "sunrise"],
            "spring": ["mountain", "spring_greenery", "sunny"],
            "summer": ["mountain", "summer_lush", "sunny"],
            "autumn": ["mountain", "autumn_foliage", "sunset"]
        },
        "temple": {
            "spring": ["temple", "cherry_blossom", "sunny"],
            "summer": ["temple", "sunny"],
            "autumn": ["temple", "autumn_foliage"],
            "winter": ["temple", "snowy"]
        },
        "park": {
            "spring": ["park", "blooming_flowers", "spring_greenery"],
            "summer": ["park", "summer_lush", "sunny"],
            "autumn": ["park", "autumn_foliage", "falling_leaves"],
            "winter": ["park", "winter_barren", "snowy"]
        }
    }
    
    inserted = 0
    try:
        from psycopg2.extras import RealDictCursor
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get category for each viewpoint
                cursor.execute("""
                    SELECT viewpoint_id, category_norm 
                    FROM viewpoint_entity 
                    WHERE viewpoint_id = ANY(%s)
                """, (viewpoint_ids,))
                
                viewpoint_categories = {row['viewpoint_id']: row['category_norm'] for row in cursor.fetchall()}
                
                for vp_id in random.sample(viewpoint_ids, min(sample_count, len(viewpoint_ids))):
                    category = viewpoint_categories.get(vp_id, "mountain")
                    season = random.choice(seasons)
                    
                    # Get tags based on category and season
                    if category in visual_tag_templates and season in visual_tag_templates[category]:
                        tags = visual_tag_templates[category][season]
                    else:
                        tags = [category, "sunny"]
                    
                    tag_source = random.choice(tag_sources)
                    confidence = random.uniform(0.6, 1.0)
                    
                    evidence = {
                        "source": tag_source,
                        "reference": f"test_{vp_id}_{season}",
                        "file_id": f"test_file_{vp_id}.jpg" if tag_source == "commons_vision" else None
                    }
                    
                    try:
                        cursor.execute("""
                            INSERT INTO viewpoint_visual_tags (
                                viewpoint_id, season, tags, confidence, evidence, tag_source
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (viewpoint_id, season, tag_source) DO UPDATE
                            SET tags = EXCLUDED.tags,
                                confidence = EXCLUDED.confidence,
                                evidence = EXCLUDED.evidence
                        """, (
                            vp_id,
                            season,
                            json.dumps(tags),
                            confidence,
                            json.dumps(evidence),
                            tag_source
                        ))
                        inserted += 1
                    except Exception as e:
                        continue
                
                conn.commit()
        
        return inserted
    except Exception as e:
        print(f"Error inserting visual tags: {e}")
        return inserted


def main():
    """Main function to insert 5000 OSM test records"""
    print("=" * 60)
    print("OSM Test Data Insertion Script")
    print("=" * 60)
    
    num_records = 5000
    print(f"\nGenerating {num_records} viewpoint records...")
    
    # Generate all viewpoint data
    start_time = time.time()
    viewpoints = []
    for i in range(num_records):
        viewpoints.append(generate_viewpoint_data(i))
        if (i + 1) % 1000 == 0:
            print(f"Generated {i + 1}/{num_records} records...")
    
    print(f"\n✓ Generated {len(viewpoints)} records in {time.time() - start_time:.2f}s")
    
    # Insert into database
    print(f"\nInserting records into database...")
    start_time = time.time()
    inserted_count = insert_viewpoints_batch(viewpoints, batch_size=100)
    elapsed = time.time() - start_time
    
    print(f"\n✓ Inserted {inserted_count} viewpoints in {elapsed:.2f}s")
    print(f"  Average: {inserted_count/elapsed:.1f} records/second")
    
    # Get inserted viewpoint IDs
    print(f"\nFetching inserted viewpoint IDs...")
    with db.get_cursor() as cursor:
        cursor.execute("SELECT viewpoint_id FROM viewpoint_entity ORDER BY viewpoint_id")
        viewpoint_ids = [row['viewpoint_id'] for row in cursor.fetchall()]
    
    print(f"✓ Found {len(viewpoint_ids)} viewpoints in database")
    
    # Insert sample visual tags (for 20% of viewpoints)
    visual_tag_count = min(1000, len(viewpoint_ids) // 5)
    print(f"\nInserting visual tags for {visual_tag_count} viewpoints...")
    start_time = time.time()
    visual_tags_inserted = insert_sample_visual_tags(viewpoint_ids, visual_tag_count)
    elapsed = time.time() - start_time
    
    print(f"✓ Inserted visual tags for {visual_tags_inserted} viewpoints in {elapsed:.2f}s")
    
    # Summary
    print("\n" + "=" * 60)
    print("Insertion Summary")
    print("=" * 60)
    print(f"Viewpoints inserted: {inserted_count}")
    print(f"Visual tags inserted: {visual_tags_inserted}")
    print(f"Total records in database: {len(viewpoint_ids)}")
    print("=" * 60)
    
    # Show some statistics
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT category_norm, COUNT(*) as count
            FROM viewpoint_entity
            GROUP BY category_norm
            ORDER BY count DESC
        """)
        print("\nCategory distribution:")
        for row in cursor.fetchall():
            print(f"  {row['category_norm']}: {row['count']}")


if __name__ == "__main__":
    main()

