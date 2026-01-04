#!/usr/bin/env python3
"""
Insert sample viewpoint data for testing
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
import json


def insert_sample_data():
    """Insert sample viewpoint entities"""
    
    sample_viewpoints = [
        {
            "osm_type": "node",
            "osm_id": 123456789,
            "name_primary": "Mount Fuji",
            "name_variants": {
                "name:en": "Mount Fuji",
                "name:ja": "富士山",
                "name:zh": "富士山",
                "alt_name": "Fuji-san"
            },
            "category_osm": {
                "natural": "volcano",
                "tourism": "attraction"
            },
            "category_norm": "mountain",
            "geom": "POINT(138.7274 35.3606)",  # Simplified - would use PostGIS in production
            "admin_area_ids": [123, 456],
            "popularity": 0.95
        },
        {
            "osm_type": "way",
            "osm_id": 987654321,
            "name_primary": "Tokyo Skytree",
            "name_variants": {
                "name:en": "Tokyo Skytree",
                "name:ja": "東京スカイツリー",
                "name:zh": "东京晴空塔"
            },
            "category_osm": {
                "tourism": "attraction",
                "man_made": "tower"
            },
            "category_norm": "tower",
            "geom": "POINT(139.8107 35.7101)",
            "admin_area_ids": [789],
            "popularity": 0.88
        }
    ]
    
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                for vp in sample_viewpoints:
                    # Insert entity
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
                        viewpoint_id = result[0]
                        print(f"✓ Inserted: {vp['name_primary']} (ID: {viewpoint_id})")
                        
                        # Insert sample visual tags
                        if vp["name_primary"] == "Mount Fuji":
                            cursor.execute("""
                                INSERT INTO viewpoint_visual_tags (
                                    viewpoint_id, season, tags, confidence, evidence, tag_source
                                ) VALUES (%s, %s, %s, %s, %s, %s)
                            """, (
                                viewpoint_id,
                                "winter",
                                json.dumps(["snow_peak", "mountain", "sunrise"]),
                                0.9,
                                json.dumps({
                                    "source": "commons_vision",
                                    "file_id": "File:Mount_Fuji_winter.jpg",
                                    "reference": "commons:12345"
                                }),
                                "commons_vision"
                            ))
                            
                            cursor.execute("""
                                INSERT INTO viewpoint_visual_tags (
                                    viewpoint_id, season, tags, confidence, evidence, tag_source
                                ) VALUES (%s, %s, %s, %s, %s, %s)
                            """, (
                                viewpoint_id,
                                "spring",
                                json.dumps(["cherry_blossom", "mountain", "sunny"]),
                                0.85,
                                json.dumps({
                                    "source": "wiki_weak_supervision",
                                    "sentence_hash": "abc123",
                                    "reference": "wikipedia:Mount_Fuji#Spring"
                                }),
                                "wiki_weak_supervision"
                            ))
                            print(f"  → Added visual tags for Mount Fuji")
        
        print("\n✓ Sample data inserted successfully")
        return True
    except Exception as e:
        print(f"Error inserting sample data: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = insert_sample_data()
    sys.exit(0 if success else 1)

