#!/usr/bin/env python3
"""
Insert Wikipedia and Wikidata data for all viewpoints

This script generates realistic Wikipedia/Wikidata test data for all viewpoints
in the database.
"""
import sys
import json
import random
from pathlib import Path
from typing import List, Dict, Any
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor

# Sample Wikipedia extracts by category
WIKI_EXTRACTS = {
    "mountain": [
        "is a prominent peak known for its majestic beauty and challenging climbing routes. The mountain has been a significant landmark for centuries, attracting climbers and tourists from around the world.",
        "stands as one of the most iconic natural landmarks in the region. With its distinctive shape and cultural significance, it has been featured in numerous works of art and literature throughout history.",
        "is a volcanic peak that has shaped the landscape and culture of the surrounding area. The mountain holds spiritual significance for local communities and offers breathtaking views from its summit."
    ],
    "temple": [
        "is a historic temple complex dating back several centuries. The temple is renowned for its exquisite architecture, intricate carvings, and spiritual significance. It serves as an important pilgrimage site and cultural landmark.",
        "is one of the most revered religious sites in the region. Built in traditional architectural style, the temple complex includes multiple halls, pagodas, and gardens that reflect the rich cultural heritage of the area.",
        "has been a center of religious and cultural activities for generations. The temple's architecture combines traditional elements with unique local styles, making it a significant example of regional temple design."
    ],
    "museum": [
        "is a world-class museum housing an extensive collection of artifacts, artworks, and historical objects. The museum's exhibitions span multiple periods and cultures, offering visitors a comprehensive view of human history and creativity.",
        "is renowned for its exceptional collection and innovative exhibition design. The museum building itself is an architectural masterpiece, and its galleries showcase works from ancient times to the contemporary era.",
        "serves as a cultural hub, preserving and presenting the region's rich heritage through carefully curated exhibitions. The museum's collection includes rare artifacts, paintings, sculptures, and interactive displays."
    ],
    "park": [
        "is a beautiful urban park that serves as a green oasis in the heart of the city. The park features well-maintained gardens, walking paths, recreational facilities, and serves as a popular gathering place for locals and visitors.",
        "covers a vast area of natural and landscaped grounds, offering visitors opportunities for relaxation, recreation, and appreciation of nature. The park includes various themed gardens, water features, and cultural monuments.",
        "is a historic park that has been carefully preserved and enhanced over the years. It combines natural beauty with cultural elements, featuring monuments, sculptures, and spaces for various activities and events."
    ],
    "tower": [
        "is a remarkable architectural achievement, standing as one of the tallest structures in the region. The tower offers panoramic views of the surrounding area and has become an iconic symbol of the city's skyline.",
        "represents a blend of modern engineering and aesthetic design. The tower serves multiple functions including observation, telecommunications, and as a tourist attraction, drawing millions of visitors annually.",
        "is a historic tower that has witnessed centuries of history. Its unique design and strategic location have made it a significant landmark and a testament to the architectural achievements of its era."
    ],
    "bridge": [
        "is an engineering marvel that spans a major waterway, connecting different parts of the city. The bridge's distinctive design and historical significance have made it one of the most recognizable landmarks in the region.",
        "has been a vital transportation link for over a century. The bridge's architecture reflects the engineering techniques of its time while remaining functional and aesthetically pleasing to this day.",
        "is a suspension bridge known for its elegant design and impressive scale. It has become an iconic symbol of the city and is considered one of the most beautiful bridges in the world."
    ],
    "lake": [
        "is a pristine body of water surrounded by natural beauty. The lake serves as an important ecosystem, supporting diverse wildlife and providing recreational opportunities for visitors throughout the year.",
        "is a large freshwater lake that has been a source of water, transportation, and recreation for local communities for centuries. The lake's scenic beauty and ecological importance make it a protected natural area.",
        "is known for its crystal-clear waters and stunning mountain backdrop. The lake offers various water activities and is particularly beautiful during different seasons, each offering unique natural displays."
    ],
    "monument": [
        "is a significant historical monument commemorating important events and figures. The monument's design and location reflect its cultural and historical importance, serving as a reminder of the past.",
        "stands as a testament to the region's rich history and cultural heritage. The monument has been carefully preserved and continues to serve as an important site for remembrance and education.",
        "is an architectural masterpiece that combines artistic expression with historical significance. The monument attracts visitors from around the world who come to appreciate its design and learn about its historical context."
    ],
    "palace": [
        "is a magnificent palace complex that once served as a royal residence. The palace showcases exquisite architecture, opulent interiors, and extensive gardens, representing the pinnacle of architectural and artistic achievement of its era.",
        "has been a center of political and cultural life for centuries. The palace complex includes multiple buildings, courtyards, and gardens, each reflecting different periods of construction and renovation.",
        "is a UNESCO World Heritage site known for its historical significance and architectural beauty. The palace preserves the lifestyle and culture of past rulers while serving as a major tourist attraction."
    ],
    "coast": [
        "is a stunning coastal area known for its beautiful beaches, dramatic cliffs, and pristine waters. The coastline offers spectacular views and serves as an important habitat for marine life.",
        "features a diverse coastal landscape with sandy beaches, rocky shores, and unique geological formations. The area is popular for water sports, nature observation, and scenic walks along the coast.",
        "is a protected coastal region that combines natural beauty with recreational opportunities. The coastline's unique features and biodiversity make it an important conservation area."
    ],
    "cave": [
        "is a fascinating cave system featuring impressive stalactites, stalagmites, and underground chambers. The caves have been formed over millions of years and contain unique geological formations.",
        "is a historic cave complex that has served various purposes throughout history, from shelter to religious sites. The caves feature ancient carvings and paintings that provide insights into past civilizations.",
        "is one of the largest and most beautiful cave systems in the region. The caves offer guided tours that showcase the spectacular underground formations and geological wonders."
    ],
    "waterfall": [
        "is a magnificent waterfall that cascades down rocky cliffs, creating a spectacular natural display. The waterfall is particularly impressive during the rainy season when water flow is at its peak.",
        "is a multi-tiered waterfall surrounded by lush vegetation. The area around the waterfall has been developed for tourism while preserving the natural beauty of the site.",
        "is one of the most photographed natural attractions in the region. The waterfall's height and volume create a dramatic scene, especially when viewed from various observation points."
    ],
    "valley": [
        "is a picturesque valley surrounded by mountains, offering breathtaking views and diverse landscapes. The valley has been inhabited for centuries and contains numerous historical and cultural sites.",
        "is a fertile valley that has supported agriculture and settlement for generations. The valley's natural beauty and cultural heritage make it a popular destination for visitors.",
        "is a deep valley carved by ancient rivers, featuring dramatic cliffs and diverse ecosystems. The valley offers hiking trails and scenic viewpoints that showcase its natural beauty."
    ],
    "island": [
        "is a beautiful island known for its pristine beaches, clear waters, and tropical climate. The island offers a perfect escape with its natural beauty and relaxed atmosphere.",
        "is a historic island that has played an important role in regional history. The island combines natural beauty with cultural sites, making it a unique destination for visitors.",
        "is a volcanic island featuring diverse landscapes from sandy beaches to mountainous terrain. The island's unique geology and biodiversity make it a fascinating destination for nature lovers."
    ],
    "cityscape": [
        "is a vibrant urban area known for its modern architecture, cultural attractions, and dynamic city life. The area offers a mix of historic and contemporary elements that reflect the city's evolution.",
        "represents the heart of a major metropolitan area, featuring iconic buildings, public spaces, and cultural institutions. The cityscape combines architectural heritage with modern development.",
        "is a bustling urban district that showcases the best of city living, from shopping and dining to cultural experiences. The area's skyline and street life create a vibrant atmosphere."
    ]
}

# Sample Wikidata claims templates
WIKIDATA_CLAIMS = {
    "P31": ["Q515", "Q570116"],  # instance of: city, tourist attraction
    "P625": None,  # coordinate location (will be generated)
    "P131": None,  # located in administrative territorial entity
    "P17": None,  # country
    "P571": None,  # inception date
    "P2044": None,  # elevation above sea level
    "P18": None,  # image
}


def generate_wikipedia_extract(name: str, category: str) -> str:
    """Generate a Wikipedia-style extract for a viewpoint"""
    extracts = WIKI_EXTRACTS.get(category, WIKI_EXTRACTS["mountain"])
    base_extract = random.choice(extracts)
    return f"{name} {base_extract}"


def generate_wikipedia_sections(name: str, category: str) -> List[Dict[str, Any]]:
    """Generate Wikipedia-style sections"""
    sections = [
        {
            "title": "History",
            "content": f"The history of {name} dates back centuries, with the site playing an important role in the region's cultural and historical development. Over the years, {name} has witnessed significant events and transformations.",
            "level": 2
        },
        {
            "title": "Architecture" if category in ["temple", "palace", "monument", "tower", "bridge"] else "Features",
            "content": f"{name} is characterized by its distinctive features and design elements. The site showcases unique architectural or natural characteristics that make it stand out among similar attractions.",
            "level": 2
        },
        {
            "title": "Tourism",
            "content": f"{name} attracts visitors from around the world, offering various activities and experiences. The site has been developed to accommodate tourists while preserving its historical and natural integrity.",
            "level": 2
        }
    ]
    return sections


def generate_citations() -> List[Dict[str, Any]]:
    """Generate sample citations"""
    citations = [
        {
            "ref": "ref1",
            "text": "Official tourism website",
            "url": "https://example.com/tourism"
        },
        {
            "ref": "ref2",
            "text": "Historical records and archives",
            "url": None
        },
        {
            "ref": "ref3",
            "text": "UNESCO World Heritage documentation",
            "url": "https://whc.unesco.org"
        }
    ]
    return random.sample(citations, random.randint(1, 3))


def generate_wikidata_qid() -> str:
    """Generate a realistic Wikidata QID"""
    # Generate QID in format Q + random number
    qid_num = random.randint(100000, 999999999)
    return f"Q{qid_num}"


def generate_wikidata_claims(category: str, name: str) -> Dict[str, Any]:
    """Generate Wikidata claims structure"""
    claims = {}
    
    # Instance of
    if category == "mountain":
        claims["P31"] = [{"value": "Q8502", "label": "mountain"}]
    elif category == "temple":
        claims["P31"] = [{"value": "Q44539", "label": "temple"}]
    elif category == "museum":
        claims["P31"] = [{"value": "Q33506", "label": "museum"}]
    elif category == "park":
        claims["P31"] = [{"value": "Q22698", "label": "park"}]
    elif category == "tower":
        claims["P31"] = [{"value": "Q12518", "label": "tower"}]
    elif category == "bridge":
        claims["P31"] = [{"value": "Q12280", "label": "bridge"}]
    elif category == "lake":
        claims["P31"] = [{"value": "Q23397", "label": "lake"}]
    else:
        claims["P31"] = [{"value": "Q570116", "label": "tourist attraction"}]
    
    # Inception date (random year between 1000 and 2020)
    if category in ["temple", "palace", "monument", "bridge"]:
        year = random.randint(1000, 2020)
        claims["P571"] = [{"value": f"{year}-01-01", "label": f"inception in {year}"}]
    
    # Elevation (for mountains)
    if category == "mountain":
        elevation = random.randint(500, 8848)  # 500m to Mount Everest height
        claims["P2044"] = [{"value": elevation, "unit": "meter", "label": f"{elevation} meters"}]
    
    # Image (placeholder)
    claims["P18"] = [{"value": f"File:{name.replace(' ', '_')}.jpg", "label": "main image"}]
    
    return claims


def insert_wikipedia_data_batch(viewpoint_data: List[Dict[str, Any]], batch_size: int = 100):
    """Insert Wikipedia data in batches"""
    inserted = 0
    
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for i in range(0, len(viewpoint_data), batch_size):
                    batch = viewpoint_data[i:i + batch_size]
                    
                    for vp in batch:
                        try:
                            # Generate Wikipedia title
                            wikipedia_title = vp['name_primary'].replace(' ', '_')
                            
                            # Insert Wikipedia data
                            cursor.execute("""
                                INSERT INTO viewpoint_wiki (
                                    viewpoint_id, wikipedia_title, wikipedia_lang,
                                    extract_text, sections, citations
                                ) VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT (viewpoint_id) DO UPDATE
                                SET wikipedia_title = EXCLUDED.wikipedia_title,
                                    extract_text = EXCLUDED.extract_text,
                                    sections = EXCLUDED.sections,
                                    citations = EXCLUDED.citations,
                                    last_updated = CURRENT_TIMESTAMP
                            """, (
                                vp['viewpoint_id'],
                                wikipedia_title,
                                'en',
                                vp['extract_text'],
                                json.dumps(vp['sections']),
                                json.dumps(vp['citations'])
                            ))
                            inserted += 1
                        except Exception as e:
                            print(f"Error inserting Wikipedia data for {vp['name_primary']}: {e}")
                            continue
                    
                    conn.commit()
                    if (i + batch_size) % 1000 == 0:
                        print(f"Progress: {min(i + batch_size, len(viewpoint_data))}/{len(viewpoint_data)} Wikipedia records processed")
        
        return inserted
    except Exception as e:
        print(f"Error in Wikipedia batch insert: {e}")
        import traceback
        traceback.print_exc()
        return inserted


def insert_wikidata_data_batch(viewpoint_data: List[Dict[str, Any]], batch_size: int = 100):
    """Insert Wikidata data in batches"""
    inserted = 0
    
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for i in range(0, len(viewpoint_data), batch_size):
                    batch = viewpoint_data[i:i + batch_size]
                    
                    for vp in batch:
                        try:
                            cursor.execute("""
                                INSERT INTO viewpoint_wikidata (
                                    viewpoint_id, wikidata_qid, claims, sitelinks_count
                                ) VALUES (%s, %s, %s, %s)
                                ON CONFLICT (viewpoint_id) DO UPDATE
                                SET wikidata_qid = EXCLUDED.wikidata_qid,
                                    claims = EXCLUDED.claims,
                                    sitelinks_count = EXCLUDED.sitelinks_count,
                                    last_updated = CURRENT_TIMESTAMP
                            """, (
                                vp['viewpoint_id'],
                                vp['wikidata_qid'],
                                json.dumps(vp['claims']),
                                vp['sitelinks_count']
                            ))
                            inserted += 1
                        except Exception as e:
                            continue
                    
                    conn.commit()
                    if (i + batch_size) % 1000 == 0:
                        print(f"Progress: {min(i + batch_size, len(viewpoint_data))}/{len(viewpoint_data)} Wikidata records processed")
        
        return inserted
    except Exception as e:
        print(f"Error in Wikidata batch insert: {e}")
        return inserted


def main():
    """Main function to insert Wikipedia and Wikidata data for all viewpoints"""
    print("=" * 60)
    print("Wikipedia & Wikidata Data Insertion Script")
    print("=" * 60)
    
    # Fetch all viewpoints
    print("\nFetching all viewpoints from database...")
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT viewpoint_id, name_primary, category_norm
            FROM viewpoint_entity
            ORDER BY viewpoint_id
        """)
        viewpoints = cursor.fetchall()
    
    print(f"✓ Found {len(viewpoints)} viewpoints")
    
    # Prepare Wikipedia data
    print("\nGenerating Wikipedia data...")
    start_time = time.time()
    wiki_data = []
    
    for vp in viewpoints:
        extract = generate_wikipedia_extract(vp['name_primary'], vp['category_norm'] or 'mountain')
        sections = generate_wikipedia_sections(vp['name_primary'], vp['category_norm'] or 'mountain')
        citations = generate_citations()
        
        wiki_data.append({
            'viewpoint_id': vp['viewpoint_id'],
            'name_primary': vp['name_primary'],
            'category_norm': vp['category_norm'],
            'extract_text': extract,
            'sections': sections,
            'citations': citations
        })
    
    print(f"✓ Generated Wikipedia data in {time.time() - start_time:.2f}s")
    
    # Insert Wikipedia data
    print("\nInserting Wikipedia data...")
    start_time = time.time()
    wiki_inserted = insert_wikipedia_data_batch(wiki_data, batch_size=100)
    elapsed = time.time() - start_time
    
    print(f"✓ Inserted {wiki_inserted} Wikipedia records in {elapsed:.2f}s")
    print(f"  Average: {wiki_inserted/elapsed:.1f} records/second")
    
    # Prepare Wikidata data
    print("\nGenerating Wikidata data...")
    start_time = time.time()
    wikidata_data = []
    
    for vp in viewpoints:
        qid = generate_wikidata_qid()
        claims = generate_wikidata_claims(vp['category_norm'] or 'mountain', vp['name_primary'])
        sitelinks_count = random.randint(5, 50)  # Random number of language links
        
        wikidata_data.append({
            'viewpoint_id': vp['viewpoint_id'],
            'wikidata_qid': qid,
            'claims': claims,
            'sitelinks_count': sitelinks_count
        })
    
    print(f"✓ Generated Wikidata data in {time.time() - start_time:.2f}s")
    
    # Insert Wikidata data
    print("\nInserting Wikidata data...")
    start_time = time.time()
    wikidata_inserted = insert_wikidata_data_batch(wikidata_data, batch_size=100)
    elapsed = time.time() - start_time
    
    print(f"✓ Inserted {wikidata_inserted} Wikidata records in {elapsed:.2f}s")
    print(f"  Average: {wikidata_inserted/elapsed:.1f} records/second")
    
    # Summary
    print("\n" + "=" * 60)
    print("Insertion Summary")
    print("=" * 60)
    print(f"Total viewpoints: {len(viewpoints)}")
    print(f"Wikipedia records inserted: {wiki_inserted}")
    print(f"Wikidata records inserted: {wikidata_inserted}")
    print("=" * 60)
    
    # Verify
    with db.get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM viewpoint_wiki")
        wiki_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as count FROM viewpoint_wikidata")
        wikidata_count = cursor.fetchone()['count']
        
        print(f"\nVerification:")
        print(f"  Wikipedia records in DB: {wiki_count}")
        print(f"  Wikidata records in DB: {wikidata_count}")


if __name__ == "__main__":
    main()

