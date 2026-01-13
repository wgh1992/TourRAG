#!/usr/bin/env python3
"""
改进季节标签提取：为每个景点生成多个季节的标签

这个脚本会：
1. 为已有 "unknown" 季节标签的景点生成真正的四季标签
2. 改进 LLM prompt 以更好地提取季节信息
3. 根据类别自动推断季节特征
"""
import sys
import json
from pathlib import Path
from typing import List, Dict, Any
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from app.tools.extract_query_intent import load_tag_schema
from psycopg2.extras import RealDictCursor
from openai import OpenAI
from app.config import settings

# Load tag schema
tag_schema = load_tag_schema(settings.TAG_SCHEMA_VERSION)
VALID_VISUAL_TAGS = list(tag_schema.get("visual_tags", {}).keys())
VALID_SCENE_TAGS = list(tag_schema.get("scene_tags", {}).keys())

# 类别到季节特征的映射
CATEGORY_SEASON_HINTS = {
    "mountain": {
        "spring": ["spring_greenery", "blooming_flowers"],
        "summer": ["summer_lush", "sunny"],
        "autumn": ["autumn_foliage", "falling_leaves"],
        "winter": ["snow_peak", "snowy", "winter_barren", "ice"]
    },
    "lake": {
        "spring": ["spring_greenery", "blooming_flowers"],
        "summer": ["summer_lush", "sunny"],
        "autumn": ["autumn_foliage", "falling_leaves"],
        "winter": ["ice", "winter_barren"]
    },
    "temple": {
        "spring": ["cherry_blossom", "blooming_flowers", "spring_greenery"],
        "summer": ["summer_lush", "sunny"],
        "autumn": ["autumn_foliage", "falling_leaves"],
        "winter": ["snowy", "winter_barren"]
    },
    "park": {
        "spring": ["cherry_blossom", "blooming_flowers", "spring_greenery"],
        "summer": ["summer_lush", "sunny"],
        "autumn": ["autumn_foliage", "falling_leaves"],
        "winter": ["snowy", "winter_barren", "ice"]
    }
}


def extract_season_from_text_improved(
    client: OpenAI,
    name: str,
    category: str,
    wiki_text: str
) -> Dict[str, Dict[str, Any]]:
    """
    改进的季节提取：为每个季节生成标签
    
    Returns:
        Dict with keys: spring, summer, autumn, winter
        Each value is a dict with tags, confidence, evidence
    """
    system_prompt = f"""You are a visual tag extraction tool for a viewpoint RAG system.

Your task is to extract visual characteristics for DIFFERENT SEASONS from Wikipedia text about a tourist attraction.

CRITICAL CONSTRAINTS:
1. tags MUST come from this controlled vocabulary:
   Visual Tags: {', '.join(VALID_VISUAL_TAGS)}
   Scene Tags: {', '.join(VALID_SCENE_TAGS)}
2. Generate tags for EACH season (spring, summer, autumn, winter)
3. For each season, extract:
   - Visual characteristics mentioned in text for that season
   - If text doesn't mention a specific season, infer reasonable tags based on category
4. Provide evidence sentences that support your extraction

Output JSON format:
{{
  "spring": {{
    "tags": ["tag1", "tag2"],
    "confidence": 0.0-1.0,
    "evidence_sentences": ["sentence 1"]
  }},
  "summer": {{...}},
  "autumn": {{...}},
  "winter": {{...}}
}}"""

    user_prompt = f"""Extract visual tags for EACH SEASON from this Wikipedia text about {name} (category: {category}):

{wiki_text[:2000]}

For each season (spring, summer, autumn, winter):
1. Extract visual characteristics mentioned in the text for that season
2. If text doesn't mention a season, infer reasonable tags based on the category
3. For example:
   - Mountain in winter → snow_peak, snowy, winter_barren
   - Temple in spring → cherry_blossom, blooming_flowers, spring_greenery
   - Lake in autumn → autumn_foliage, falling_leaves
4. Provide evidence sentences that support your extraction"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2  # Slightly higher for more creative season inference
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Validate and enhance with category hints
        season_tags = {}
        for season in ["spring", "summer", "autumn", "winter"]:
            season_data = result.get(season, {})
            extracted_tags = season_data.get("tags", [])
            
            # Validate tags
            valid_tags = [tag for tag in extracted_tags if tag in VALID_VISUAL_TAGS + VALID_SCENE_TAGS]
            
            # Add category-based hints if available
            if category in CATEGORY_SEASON_HINTS and season in CATEGORY_SEASON_HINTS[category]:
                category_hints = CATEGORY_SEASON_HINTS[category][season]
                for hint in category_hints:
                    if hint not in valid_tags:
                        valid_tags.append(hint)
            
            # Ensure we have at least the category tag
            if category and category not in valid_tags:
                valid_tags.append(category)
            
            season_tags[season] = {
                "tags": valid_tags,
                "confidence": min(max(season_data.get("confidence", 0.6), 0.0), 1.0),
                "evidence_sentences": season_data.get("evidence_sentences", [])
            }
        
        return season_tags
    
    except Exception as e:
        print(f"Error extracting tags for {name}: {e}")
        # Return default tags based on category
        default_tags = {}
        for season in ["spring", "summer", "autumn", "winter"]:
            tags = [category] if category else []
            if category in CATEGORY_SEASON_HINTS and season in CATEGORY_SEASON_HINTS[category]:
                tags.extend(CATEGORY_SEASON_HINTS[category][season])
            
            default_tags[season] = {
                "tags": tags,
                "confidence": 0.5,
                "evidence_sentences": []
            }
        return default_tags


def main():
    """为只有 unknown 季节标签的景点生成真正的四季标签"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Improve season tags for viewpoints')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of viewpoints to process')
    parser.add_argument('--dry-run', action='store_true', help='Dry run without calling API')
    args = parser.parse_args()
    
    print("=" * 80)
    print("改进季节标签提取")
    print("=" * 80)
    
    # Initialize OpenAI client
    if not args.dry_run:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    else:
        client = None
        print("\n⚠️  DRY RUN MODE - No API calls will be made")
    
    # Find viewpoints that only have "unknown" season tags
    print("\n查找只有 'unknown' 季节标签的景点...")
    with db.get_cursor() as cursor:
        query = """
            SELECT DISTINCT
                v.viewpoint_id,
                v.name_primary,
                v.category_norm,
                w.extract_text,
                w.sections
            FROM viewpoint_entity v
            INNER JOIN viewpoint_wiki w ON v.viewpoint_id = w.viewpoint_id
            WHERE w.extract_text IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM viewpoint_visual_tags vt 
                WHERE vt.viewpoint_id = v.viewpoint_id 
                AND vt.season = 'unknown'
                AND vt.tag_source = 'wiki_weak_supervision'
            )
            AND NOT EXISTS (
                SELECT 1 FROM viewpoint_visual_tags vt 
                WHERE vt.viewpoint_id = v.viewpoint_id 
                AND vt.season IN ('spring', 'summer', 'autumn', 'winter')
            )
            ORDER BY v.viewpoint_id
        """
        if args.limit:
            query += f" LIMIT {args.limit}"
        
        cursor.execute(query)
        viewpoints = cursor.fetchall()
    
    print(f"✓ 找到 {len(viewpoints)} 个需要改进的景点")
    
    if not viewpoints:
        print("\n✓ 所有景点都已经有真正的季节标签！")
        return
    
    if args.dry_run:
        print(f"\n将处理 {len(viewpoints)} 个景点")
        print("运行时不带 --dry-run 来实际处理")
        return
    
    # Process viewpoints
    print(f"\n为每个景点生成四季标签...")
    all_tags = []
    start_time = time.time()
    
    for i, vp in enumerate(viewpoints):
        try:
            # Combine extract_text and sections
            wiki_text = vp['extract_text'] or ""
            if vp.get('sections'):
                sections = json.loads(vp['sections']) if isinstance(vp['sections'], str) else vp['sections']
                for section in sections[:2]:
                    wiki_text += "\n\n" + section.get('content', '')
            
            # Extract season tags
            season_tags = extract_season_from_text_improved(
                client,
                vp['name_primary'],
                vp['category_norm'] or 'attraction',
                wiki_text
            )
            
            # Create tag records for each season
            for season, tag_data in season_tags.items():
                all_tags.append({
                    'viewpoint_id': vp['viewpoint_id'],
                    'season': season,
                    'tags': tag_data['tags'],
                    'confidence': tag_data['confidence'],
                    'evidence': {
                        'source': 'wiki_weak_supervision',
                        'sentence_hash': f"hash_{vp['viewpoint_id']}_{season}",
                        'sentences': tag_data['evidence_sentences'][:3]
                    }
                })
            
            if (i + 1) % 50 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                remaining = (len(viewpoints) - i - 1) / rate if rate > 0 else 0
                print(f"进度: {i + 1}/{len(viewpoints)} 景点 "
                      f"({rate:.1f}/秒, 约 {remaining/60:.1f} 分钟剩余)")
        
        except Exception as e:
            print(f"处理 {vp['name_primary']} 时出错: {e}")
            continue
        
        # Rate limiting
        time.sleep(0.1)
    
    print(f"\n✓ 生成了 {len(all_tags)} 个季节标签记录")
    
    # Insert tags
    print(f"\n插入季节标签到数据库...")
    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            inserted = 0
            for tag_record in all_tags:
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
                        tag_record['viewpoint_id'],
                        tag_record['season'],
                        json.dumps(tag_record['tags']),
                        tag_record['confidence'],
                        json.dumps(tag_record['evidence']),
                        'wiki_weak_supervision'
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"插入标签时出错 (viewpoint {tag_record['viewpoint_id']}): {e}")
                    continue
            
            conn.commit()
    
    print(f"✓ 插入了 {inserted} 个季节标签记录")
    
    # Summary
    print("\n" + "=" * 80)
    print("总结")
    print("=" * 80)
    print(f"处理的景点数: {len(viewpoints)}")
    print(f"生成的标签记录数: {len(all_tags)}")
    print(f"插入的标签记录数: {inserted}")
    
    # Verify
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT season, COUNT(*) as count
            FROM viewpoint_visual_tags
            WHERE tag_source = 'wiki_weak_supervision'
            GROUP BY season
            ORDER BY season
        """)
        season_counts = cursor.fetchall()
        
        print(f"\n验证 - 季节标签分布:")
        for sc in season_counts:
            print(f"  {sc['season']:10} {sc['count']:6,} 标签")
    
    print("=" * 80)


if __name__ == "__main__":
    main()
