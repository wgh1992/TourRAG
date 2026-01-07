#!/usr/bin/env python3
"""
Ensure all viewpoints have complete data:
1. Wikipedia/Wikidata history info
2. Visual tags extracted by LLM from Wikipedia text

This script checks and fills any missing data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor


def check_data_completeness():
    """Check data completeness for all viewpoints"""
    print("=" * 60)
    print("Data Completeness Check")
    print("=" * 60)
    
    with db.get_cursor() as cursor:
        # Total viewpoints
        cursor.execute("SELECT COUNT(*) as count FROM viewpoint_entity")
        total = cursor.fetchone()['count']
        
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
        
        # Viewpoints with LLM-extracted tags
        cursor.execute("""
            SELECT COUNT(DISTINCT viewpoint_id) as count
            FROM viewpoint_visual_tags
            WHERE tag_source = 'wiki_weak_supervision'
        """)
        with_llm_tags = cursor.fetchone()['count']
        
        print(f"\nTotal viewpoints: {total}")
        print(f"  With Wikipedia: {with_wiki} ({with_wiki/total*100:.1f}%)")
        print(f"  With Wikidata: {with_wikidata} ({with_wikidata/total*100:.1f}%)")
        print(f"  With visual tags: {with_tags} ({with_tags/total*100:.1f}%)")
        print(f"  With LLM-extracted tags: {with_llm_tags} ({with_llm_tags/total*100:.1f}%)")
        
        # Missing data
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM viewpoint_entity v
            WHERE NOT EXISTS (
                SELECT 1 FROM viewpoint_wiki w WHERE w.viewpoint_id = v.viewpoint_id
            )
        """)
        missing_wiki = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM viewpoint_entity v
            WHERE NOT EXISTS (
                SELECT 1 FROM viewpoint_wikidata wd WHERE wd.viewpoint_id = v.viewpoint_id
            )
        """)
        missing_wikidata = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM viewpoint_entity v
            WHERE EXISTS (
                SELECT 1 FROM viewpoint_wiki w WHERE w.viewpoint_id = v.viewpoint_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM viewpoint_visual_tags vt 
                WHERE vt.viewpoint_id = v.viewpoint_id 
                AND vt.tag_source = 'wiki_weak_supervision'
            )
        """)
        missing_llm_tags = cursor.fetchone()['count']
        
        print(f"\nMissing data:")
        print(f"  Wikipedia: {missing_wiki}")
        print(f"  Wikidata: {missing_wikidata}")
        print(f"  LLM-extracted visual tags: {missing_llm_tags}")
        
        return {
            'total': total,
            'missing_wiki': missing_wiki,
            'missing_wikidata': missing_wikidata,
            'missing_llm_tags': missing_llm_tags
        }


def main():
    """Main function"""
    status = check_data_completeness()
    
    print("\n" + "=" * 60)
    print("Recommendations")
    print("=" * 60)
    
    if status['missing_wiki'] > 0:
        print(f"\n⚠️  Run: python scripts/insert_wiki_data.py")
        print(f"   To add Wikipedia data for {status['missing_wiki']} viewpoints")
    
    if status['missing_wikidata'] > 0:
        print(f"\n⚠️  Run: python scripts/insert_wiki_data.py")
        print(f"   To add Wikidata data for {status['missing_wikidata']} viewpoints")
    
    if status['missing_llm_tags'] > 0:
        print(f"\n⚠️  Run: python scripts/generate_visual_tags_from_wiki.py")
        print(f"   To generate LLM-extracted visual tags for {status['missing_llm_tags']} viewpoints")
        print(f"   Note: This uses GPT-4o API and may take time/cost")
    
    if status['missing_wiki'] == 0 and status['missing_wikidata'] == 0 and status['missing_llm_tags'] == 0:
        print("\n✅ All viewpoints have complete data!")
    
    print("=" * 60)


if __name__ == "__main__":
    main()

