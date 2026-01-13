#!/usr/bin/env python3
"""
Generate season information only for viewpoints (no complex visual tags)

This script extracts season information from Wikipedia text and stores it
with minimal tags (only category). No complex visual tags are generated.

只为景点生成季节信息，不生成复杂的visual tags
"""
import sys
import json
from pathlib import Path
from typing import List, Dict, Any
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from app.services.llm_service import get_llm_service
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from app.config import settings


def extract_season_from_text(
    client: OpenAI,
    name: str,
    category: str,
    wiki_text: str
) -> Dict[str, str]:
    """
    Extract season information from Wikipedia text.
    Returns a dict mapping season to whether it's mentioned in text.
    
    Returns:
        Dict with keys: spring, summer, autumn, winter
        Values: "mentioned" or "inferred" or "unknown"
    """
    system_prompt = f"""You are a season extraction tool for a viewpoint RAG system.

Your task is to extract which seasons are relevant for visiting {name} (category: {category}) from Wikipedia text.

CRITICAL CONSTRAINTS:
1. season must be one of: spring, summer, autumn, winter, unknown
2. Extract seasons that are explicitly mentioned in the text
3. If no season is mentioned, infer reasonable seasons based on the category:
   - Mountains: all seasons (winter for snow, spring/summer for hiking, autumn for foliage)
   - Temples/Parks: spring (cherry blossoms), autumn (foliage), summer (lush), winter (snow)
   - Lakes: spring, summer, autumn (avoid winter if frozen)
   - Beaches/Coasts: summer (best season)
4. Return a simple JSON with season information

Output JSON format:
{{
  "spring": "mentioned|inferred|unknown",
  "summer": "mentioned|inferred|unknown",
  "autumn": "mentioned|inferred|unknown",
  "winter": "mentioned|inferred|unknown"
}}"""

    user_prompt = f"""Extract season information from this Wikipedia text about {name} (category: {category}):

{wiki_text[:2000]}

Determine which seasons are:
1. Explicitly mentioned in the text (mark as "mentioned")
2. Can be reasonably inferred from the category/context (mark as "inferred")
3. Not applicable or unknown (mark as "unknown")"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"Error extracting season for {name}: {e}")
        # Return default: all seasons as inferred
        return {
            "spring": "inferred",
            "summer": "inferred",
            "autumn": "inferred",
            "winter": "inferred"
        }


def generate_season_records(
    client: OpenAI,
    name: str,
    category: str,
    wiki_text: str
) -> List[Dict[str, Any]]:
    """
    Generate season records with minimal tags (only category).
    
    Returns:
        List of season records, each with season, tags (only category), confidence, evidence
    """
    season_info = extract_season_from_text(client, name, category, wiki_text)
    
    season_records = []
    
    for season, status in season_info.items():
        if season == "unknown":
            continue  # Skip unknown season
        
        if status in ["mentioned", "inferred"]:
            # Only include category in tags, no complex visual tags
            tags = [category] if category else []
            
            # Confidence based on whether it's mentioned or inferred
            confidence = 0.8 if status == "mentioned" else 0.6
            
            season_records.append({
                "season": season,
                "tags": tags,
                "confidence": confidence,
                "evidence": {
                    "source": "wiki_season_extraction",
                    "status": status,
                    "sentence_hash": f"hash_{name}_{season}"
                }
            })
    
    # If no seasons found, add at least one default season
    if not season_records:
        season_records.append({
            "season": "unknown",
            "tags": [category] if category else [],
            "confidence": 0.5,
            "evidence": {
                "source": "wiki_season_extraction",
                "status": "default",
                "sentence_hash": f"hash_{name}_unknown"
            }
        })
    
    return season_records


def insert_season_records_batch(
    viewpoint_seasons: List[Dict[str, Any]],
    batch_size: int = 50
) -> int:
    """Insert season records in batches"""
    inserted = 0
    
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for i in range(0, len(viewpoint_seasons), batch_size):
                    batch = viewpoint_seasons[i:i + batch_size]
                    
                    for vp_season in batch:
                        try:
                            cursor.execute("""
                                INSERT INTO viewpoint_visual_tags (
                                    viewpoint_id, season, tags, confidence, evidence, tag_source
                                ) VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT (viewpoint_id, season, tag_source) DO UPDATE
                                SET tags = EXCLUDED.tags,
                                    confidence = EXCLUDED.confidence,
                                    evidence = EXCLUDED.evidence,
                                    updated_at = CURRENT_TIMESTAMP
                            """, (
                                vp_season['viewpoint_id'],
                                vp_season['season'],
                                json.dumps(vp_season['tags']),
                                vp_season['confidence'],
                                json.dumps(vp_season['evidence']),
                                'wiki_season_extraction'
                            ))
                            inserted += 1
                        except Exception as e:
                            print(f"Error inserting season for viewpoint {vp_season['viewpoint_id']}: {e}")
                            continue
                    
                    conn.commit()
                    if (i + batch_size) % 500 == 0:
                        print(f"Progress: {min(i + batch_size, len(viewpoint_seasons))}/{len(viewpoint_seasons)} season records processed")
        
        return inserted
    except Exception as e:
        print(f"Error in batch insert: {e}")
        import traceback
        traceback.print_exc()
        return inserted


def main():
    """Main function to generate season information only"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate season information only (no complex visual tags)')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of viewpoints to process')
    parser.add_argument('--batch-size', type=int, default=10, help='Number of viewpoints to process in parallel batch')
    parser.add_argument('--dry-run', action='store_true', help='Dry run without calling API')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Season Information Generation (No Visual Tags)")
    print("=" * 60)
    
    # Initialize OpenAI client
    if not args.dry_run:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    else:
        client = None
        print("\n⚠️  DRY RUN MODE - No API calls will be made")
    
    # Fetch viewpoints without season info or with incomplete season info
    print("\nFetching viewpoints from database...")
    with db.get_cursor() as cursor:
        # Get all viewpoints with their Wikipedia data that don't have season info
        query = """
            SELECT 
                v.viewpoint_id,
                v.name_primary,
                v.category_norm,
                w.extract_text,
                w.sections
            FROM viewpoint_entity v
            INNER JOIN viewpoint_wiki w ON v.viewpoint_id = w.viewpoint_id
            WHERE w.extract_text IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM viewpoint_visual_tags vt 
                WHERE vt.viewpoint_id = v.viewpoint_id 
                AND vt.tag_source = 'wiki_season_extraction'
                AND vt.season IN ('spring', 'summer', 'autumn', 'winter')
            )
            ORDER BY v.viewpoint_id
        """
        if args.limit:
            query += f" LIMIT {args.limit}"
        
        cursor.execute(query)
        viewpoints = cursor.fetchall()
    
    print(f"✓ Found {len(viewpoints)} viewpoints that need season information")
    
    if not viewpoints:
        print("\n✓ All viewpoints already have season information!")
        return
    
    if args.dry_run:
        print(f"\nWould process {len(viewpoints)} viewpoints")
        print("Run without --dry-run to actually process")
        return
    
    # Generate season information using LLM
    print(f"\nGenerating season information using GPT-4o-mini...")
    print(f"This will process {len(viewpoints)} viewpoints")
    print("Note: This may take a while and consume OpenAI API credits")
    print("Tags will only include category (no complex visual tags)")
    
    all_season_records = []
    start_time = time.time()
    
    for i, vp in enumerate(viewpoints):
        try:
            # Combine extract_text and sections for richer context
            wiki_text = vp['extract_text'] or ""
            if vp.get('sections'):
                sections = json.loads(vp['sections']) if isinstance(vp['sections'], str) else vp['sections']
                for section in sections[:2]:  # Use first 2 sections
                    wiki_text += "\n\n" + section.get('content', '')
            
            # Generate season records (minimal tags, only category)
            season_records = generate_season_records(
                client,
                vp['name_primary'],
                vp['category_norm'] or 'attraction',
                wiki_text
            )
            
            # Add viewpoint_id to each record
            for record in season_records:
                record['viewpoint_id'] = vp['viewpoint_id']
                all_season_records.append(record)
            
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                remaining = (len(viewpoints) - i - 1) / rate if rate > 0 else 0
                print(f"Progress: {i + 1}/{len(viewpoints)} viewpoints processed "
                      f"({rate:.1f}/sec, ~{remaining/60:.1f} min remaining)")
        
        except Exception as e:
            print(f"Error processing {vp['name_primary']}: {e}")
            continue
        
        # Rate limiting
        time.sleep(0.1)
    
    print(f"\n✓ Generated {len(all_season_records)} season records in {time.time() - start_time:.2f}s")
    
    # Insert season records
    print(f"\nInserting season records into database...")
    start_time = time.time()
    inserted = insert_season_records_batch(all_season_records, batch_size=50)
    elapsed = time.time() - start_time
    
    print(f"✓ Inserted {inserted} season records in {elapsed:.2f}s")
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Viewpoints processed: {len(viewpoints)}")
    print(f"Season records generated: {len(all_season_records)}")
    print(f"Season records inserted: {inserted}")
    
    # Verify
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT season, COUNT(*) as count
            FROM viewpoint_visual_tags
            WHERE tag_source = 'wiki_season_extraction'
            GROUP BY season
            ORDER BY season
        """)
        season_counts = cursor.fetchall()
        
        print(f"\nVerification - Season distribution:")
        for sc in season_counts:
            print(f"  {sc['season']:10} {sc['count']:6,} records")
        
        cursor.execute("""
            SELECT COUNT(DISTINCT viewpoint_id) as count
            FROM viewpoint_visual_tags
            WHERE tag_source = 'wiki_season_extraction'
        """)
        total_with_season = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as total FROM viewpoint_entity")
        total_viewpoints = cursor.fetchone()['total']
        
        print(f"\nCoverage:")
        print(f"  Total viewpoints: {total_viewpoints}")
        print(f"  Viewpoints with season info: {total_with_season}")
        print(f"  Coverage: {total_with_season/total_viewpoints*100:.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()
