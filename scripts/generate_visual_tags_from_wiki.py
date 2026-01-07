#!/usr/bin/env python3
"""
Generate visual tags for all viewpoints using LLM extraction from Wikipedia text

This script uses GPT-4o to extract structured visual tags from Wikipedia text
for all viewpoints that don't have visual tags yet.
"""
import sys
import json
import random
from pathlib import Path
from typing import List, Dict, Any, Optional
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from app.services.llm_service import get_llm_service
from app.tools.extract_query_intent import load_tag_schema
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from app.config import settings

# Load tag schema
tag_schema = load_tag_schema(settings.TAG_SCHEMA_VERSION)

# Get valid tags
VALID_VISUAL_TAGS = list(tag_schema.get("visual_tags", {}).keys())
VALID_SCENE_TAGS = list(tag_schema.get("scene_tags", {}).keys())
SEASONS = ["spring", "summer", "autumn", "winter", "unknown"]


def extract_visual_tags_from_text(
    client: OpenAI,
    name: str,
    category: str,
    wiki_text: str
) -> Dict[str, Any]:
    """
    Use GPT-4o to extract visual tags from Wikipedia text.
    
    Returns:
        Dict with season, tags, confidence, evidence
    """
    system_prompt = f"""You are a visual tag extraction tool for a viewpoint RAG system.

Your task is to extract visual characteristics and seasonal information from Wikipedia text about a tourist attraction.

CRITICAL CONSTRAINTS:
1. tags MUST come from this controlled vocabulary:
   Visual Tags: {', '.join(VALID_VISUAL_TAGS)}
   Scene Tags: {', '.join(VALID_SCENE_TAGS)}
2. season must be one of: spring, summer, autumn, winter, unknown
3. Extract tags that describe visual features mentioned in the text
4. Infer season from text if possible (e.g., "cherry blossoms" → spring, "snow" → winter)
5. Provide evidence (quote relevant sentences from the text)

Output JSON format:
{{
  "season": "spring|summer|autumn|winter|unknown",
  "tags": ["tag1", "tag2", ...],
  "confidence": 0.0-1.0,
  "evidence_sentences": ["sentence 1", "sentence 2"]
}}"""

    user_prompt = f"""Extract visual tags from this Wikipedia text about {name} (category: {category}):

{wiki_text[:2000]}  # Limit text length

Extract:
1. Visual characteristics (snow_peak, cherry_blossom, autumn_foliage, etc.)
2. Scene types (sunrise, sunset, night_view, etc.)
3. Season hints from the text
4. Provide evidence sentences that support your extraction."""

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
        
        # Validate and clean tags
        extracted_tags = result.get("tags", [])
        valid_tags = [tag for tag in extracted_tags if tag in VALID_VISUAL_TAGS + VALID_SCENE_TAGS]
        
        # Ensure we have at least the category tag
        if category and category not in valid_tags:
            valid_tags.append(category)
        
        return {
            "season": result.get("season", "unknown"),
            "tags": valid_tags,
            "confidence": min(max(result.get("confidence", 0.7), 0.0), 1.0),
            "evidence_sentences": result.get("evidence_sentences", [])
        }
    except Exception as e:
        print(f"Error extracting tags for {name}: {e}")
        # Return default tags
        return {
            "season": "unknown",
            "tags": [category] if category else [],
            "confidence": 0.5,
            "evidence_sentences": []
        }


def generate_multiple_season_tags(
    client: OpenAI,
    name: str,
    category: str,
    wiki_text: str
) -> List[Dict[str, Any]]:
    """
    Generate visual tags for multiple seasons based on Wikipedia text.
    
    Returns:
        List of tag records for different seasons
    """
    # First, extract general tags
    base_tags = extract_visual_tags_from_text(client, name, category, wiki_text)
    
    # Generate season-specific variations
    season_tags = []
    
    # Add the extracted season
    if base_tags["season"] != "unknown":
        season_tags.append({
            "season": base_tags["season"],
            "tags": base_tags["tags"],
            "confidence": base_tags["confidence"],
            "evidence": {
                "source": "wiki_weak_supervision",
                "sentence_hash": f"hash_{name}_{base_tags['season']}",
                "sentences": base_tags["evidence_sentences"][:3]  # Limit to 3 sentences
            }
        })
    
    # Add unknown season as fallback
    season_tags.append({
        "season": "unknown",
        "tags": base_tags["tags"],
        "confidence": base_tags["confidence"] * 0.8,  # Lower confidence for unknown season
        "evidence": {
            "source": "wiki_weak_supervision",
            "sentence_hash": f"hash_{name}_unknown",
            "sentences": base_tags["evidence_sentences"][:2]
        }
    })
    
    return season_tags


def insert_visual_tags_batch(
    viewpoint_tags: List[Dict[str, Any]],
    batch_size: int = 50
) -> int:
    """Insert visual tags in batches"""
    inserted = 0
    
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for i in range(0, len(viewpoint_tags), batch_size):
                    batch = viewpoint_tags[i:i + batch_size]
                    
                    for vp_tag in batch:
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
                                vp_tag['viewpoint_id'],
                                vp_tag['season'],
                                json.dumps(vp_tag['tags']),
                                vp_tag['confidence'],
                                json.dumps(vp_tag['evidence']),
                                'wiki_weak_supervision'
                            ))
                            inserted += 1
                        except Exception as e:
                            print(f"Error inserting tags for viewpoint {vp_tag['viewpoint_id']}: {e}")
                            continue
                    
                    conn.commit()
                    if (i + batch_size) % 500 == 0:
                        print(f"Progress: {min(i + batch_size, len(viewpoint_tags))}/{len(viewpoint_tags)} tags processed")
        
        return inserted
    except Exception as e:
        print(f"Error in batch insert: {e}")
        import traceback
        traceback.print_exc()
        return inserted


def main():
    """Main function to generate visual tags for all viewpoints"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate visual tags from Wikipedia using LLM')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of viewpoints to process')
    parser.add_argument('--batch-size', type=int, default=10, help='Number of viewpoints to process in parallel batch')
    parser.add_argument('--dry-run', action='store_true', help='Dry run without calling API')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Visual Tags Generation from Wikipedia (LLM Extraction)")
    print("=" * 60)
    
    # Initialize OpenAI client
    if not args.dry_run:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    else:
        client = None
        print("\n⚠️  DRY RUN MODE - No API calls will be made")
    
    # Fetch viewpoints without visual tags or with incomplete tags
    print("\nFetching viewpoints from database...")
    with db.get_cursor() as cursor:
        # Get all viewpoints with their Wikipedia data
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
                AND vt.tag_source = 'wiki_weak_supervision'
            )
            ORDER BY v.viewpoint_id
        """
        if args.limit:
            query += f" LIMIT {args.limit}"
        
        cursor.execute(query)
        viewpoints = cursor.fetchall()
    
    print(f"✓ Found {len(viewpoints)} viewpoints that need visual tags")
    
    if not viewpoints:
        print("\n✓ All viewpoints already have visual tags!")
        return
    
    if args.dry_run:
        print(f"\nWould process {len(viewpoints)} viewpoints")
        print("Run without --dry-run to actually process")
        return
    
    # Generate visual tags using LLM
    print(f"\nGenerating visual tags using GPT-4o-mini...")
    print(f"This will process {len(viewpoints)} viewpoints")
    print("Note: This may take a while and consume OpenAI API credits")
    
    all_tags = []
    start_time = time.time()
    
    for i, vp in enumerate(viewpoints):
        try:
            # Combine extract_text and sections for richer context
            wiki_text = vp['extract_text'] or ""
            if vp.get('sections'):
                sections = json.loads(vp['sections']) if isinstance(vp['sections'], str) else vp['sections']
                for section in sections[:2]:  # Use first 2 sections
                    wiki_text += "\n\n" + section.get('content', '')
            
            # Generate tags
            season_tag_records = generate_multiple_season_tags(
                client,
                vp['name_primary'],
                vp['category_norm'] or 'mountain',
                wiki_text
            )
            
            # Add viewpoint_id to each record
            for tag_record in season_tag_records:
                tag_record['viewpoint_id'] = vp['viewpoint_id']
                all_tags.append(tag_record)
            
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                remaining = (len(viewpoints) - i - 1) / rate if rate > 0 else 0
                print(f"Progress: {i + 1}/{len(viewpoints)} viewpoints processed "
                      f"({rate:.1f}/sec, ~{remaining/60:.1f} min remaining)")
        
        except Exception as e:
            print(f"Error processing {vp['name_primary']}: {e}")
            continue
    
    print(f"\n✓ Generated {len(all_tags)} visual tag records in {time.time() - start_time:.2f}s")
    
    # Insert tags
    print(f"\nInserting visual tags into database...")
    start_time = time.time()
    inserted = insert_visual_tags_batch(all_tags, batch_size=50)
    elapsed = time.time() - start_time
    
    print(f"✓ Inserted {inserted} visual tag records in {elapsed:.2f}s")
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Viewpoints processed: {len(viewpoints)}")
    print(f"Visual tag records generated: {len(all_tags)}")
    print(f"Visual tag records inserted: {inserted}")
    
    # Verify
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(DISTINCT viewpoint_id) as count
            FROM viewpoint_visual_tags
            WHERE tag_source = 'wiki_weak_supervision'
        """)
        total_with_tags = cursor.fetchone()['count']
        
        cursor.execute("SELECT COUNT(*) as total FROM viewpoint_entity")
        total_viewpoints = cursor.fetchone()['total']
        
        print(f"\nVerification:")
        print(f"  Total viewpoints: {total_viewpoints}")
        print(f"  Viewpoints with visual tags: {total_with_tags}")
        print(f"  Coverage: {total_with_tags/total_viewpoints*100:.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    main()

