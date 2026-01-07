#!/usr/bin/env python3
"""
Diagnostic script to check why search might not be working
"""
import sys
from app.services.database import db
from app.services.retrieval import get_retrieval_service
from app.tools.extract_query_intent import get_extract_query_intent_tool
from app.schemas.query import ExtractQueryIntentInput, QueryIntent, GeoHints

def check_database():
    """Check if database has data"""
    print("=" * 60)
    print("1. Checking Database")
    print("=" * 60)
    
    try:
        with db.get_cursor() as cursor:
            # Check total viewpoints
            cursor.execute("SELECT COUNT(*) as count FROM viewpoint_entity")
            total = cursor.fetchone()['count']
            print(f"✅ Total viewpoints in database: {total}")
            
            if total == 0:
                print("❌ ERROR: Database is empty! Please run data insertion scripts.")
                return False
            
            # Check viewpoints with names
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM viewpoint_entity 
                WHERE name_primary IS NOT NULL AND name_primary != ''
            """)
            with_names = cursor.fetchone()['count']
            print(f"✅ Viewpoints with names: {with_names}")
            
            # Check sample viewpoints
            cursor.execute("""
                SELECT viewpoint_id, name_primary, category_norm, popularity
                FROM viewpoint_entity
                ORDER BY popularity DESC NULLS LAST
                LIMIT 5
            """)
            samples = cursor.fetchall()
            print(f"\n📋 Sample viewpoints (top 5 by popularity):")
            for row in samples:
                print(f"   - {row['name_primary']} (ID: {row['viewpoint_id']}, Category: {row['category_norm']}, Popularity: {row['popularity']})")
            
            # Check categories
            cursor.execute("""
                SELECT category_norm, COUNT(*) as count
                FROM viewpoint_entity
                WHERE category_norm IS NOT NULL
                GROUP BY category_norm
                ORDER BY count DESC
                LIMIT 10
            """)
            categories = cursor.fetchall()
            print(f"\n📋 Top categories:")
            for row in categories:
                print(f"   - {row['category_norm']}: {row['count']} viewpoints")
            
            return True
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return False

def test_intent_extraction(query_text):
    """Test query intent extraction"""
    print("\n" + "=" * 60)
    print(f"2. Testing Intent Extraction: '{query_text}'")
    print("=" * 60)
    
    try:
        tool = get_extract_query_intent_tool()
        input_data = ExtractQueryIntentInput(
            user_text=query_text,
            language="auto"
        )
        
        import asyncio
        result = asyncio.run(tool.extract(input_data))
        intent = result.query_intent
        
        print(f"✅ Intent extracted successfully:")
        print(f"   - Name candidates: {intent.name_candidates}")
        print(f"   - Query tags: {intent.query_tags}")
        print(f"   - Season hint: {intent.season_hint}")
        print(f"   - Scene hints: {intent.scene_hints}")
        print(f"   - Geo hints: {intent.geo_hints}")
        print(f"   - Confidence notes: {intent.confidence_notes}")
        
        return intent
    except Exception as e:
        print(f"❌ Intent extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_retrieval(query_intent):
    """Test retrieval service"""
    print("\n" + "=" * 60)
    print("3. Testing Retrieval Service")
    print("=" * 60)
    
    try:
        retrieval = get_retrieval_service()
        candidates, sql_queries = retrieval.search(
            query_intent=query_intent,
            top_n=10
        )
        
        print(f"✅ Retrieved {len(candidates)} candidates")
        
        if sql_queries:
            print(f"\n📋 SQL Query executed:")
            for q in sql_queries:
                print(f"   SQL: {q.get('sql', 'N/A')[:200]}...")
                print(f"   Params: {q.get('params', [])[:5]}...")
        
        if candidates:
            print(f"\n📋 Top candidates:")
            for i, candidate in enumerate(candidates[:5], 1):
                print(f"   {i}. {candidate.name_primary}")
                print(f"      - Name score: {candidate.name_score:.2f}")
                print(f"      - Category score: {candidate.category_score:.2f}")
                print(f"      - Popularity: {candidate.popularity:.2f}")
        else:
            print("❌ WARNING: No candidates returned!")
            print(f"   Query intent: name_candidates={query_intent.name_candidates}, tags={query_intent.query_tags}")
        
        return candidates
    except Exception as e:
        print(f"❌ Retrieval failed: {e}")
        import traceback
        traceback.print_exc()
        return []

def main():
    """Run diagnostics"""
    print("\n🔍 TourRAG Search Diagnostics")
    print("=" * 60)
    
    # Check database
    if not check_database():
        print("\n❌ Database check failed. Please fix database issues first.")
        sys.exit(1)
    
    # Test with a query
    query = sys.argv[1] if len(sys.argv) > 1 else "Mount Fuji"
    print(f"\n🔍 Testing with query: '{query}'")
    
    # Test intent extraction
    intent = test_intent_extraction(query)
    if not intent:
        print("\n❌ Intent extraction failed. Check OpenAI API key and configuration.")
        sys.exit(1)
    
    # Test retrieval
    candidates = test_retrieval(intent)
    
    if not candidates:
        print("\n❌ WARNING: No candidates found!")
        print("\n💡 Possible issues:")
        print("   1. Query intent doesn't match any viewpoints in database")
        print("   2. Name candidates don't match any viewpoint names")
        print("   3. Category tags don't match any viewpoint categories")
        print("   4. Database might need more data")
        print("\n💡 Try:")
        print("   - Use a more specific query with known viewpoint names")
        print("   - Check if viewpoint names in database match your query")
        print("   - Try category-based queries like 'mountain' or 'temple'")
    else:
        print(f"\n✅ Search is working! Found {len(candidates)} candidates.")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()

