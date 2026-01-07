#!/usr/bin/env python3
"""
Quick test script for TourRAG search functionality
"""
import requests
import json
import sys

API_BASE = "http://localhost:8000"

def test_health():
    """Test health check endpoint"""
    print("=" * 60)
    print("1. Testing Health Check")
    print("=" * 60)
    try:
        response = requests.get(f"{API_BASE}/health")
        response.raise_for_status()
        print(f"✅ Health check passed: {response.json()}")
        return True
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def test_search(query_text, top_k=5):
    """Test full search endpoint"""
    print("\n" + "=" * 60)
    print(f"2. Testing Search: '{query_text}'")
    print("=" * 60)
    try:
        response = requests.post(
            f"{API_BASE}/api/v1/query",
            params={
                "user_text": query_text,
                "top_k": top_k,
                "language": "auto"
            }
        )
        response.raise_for_status()
        data = response.json()
        
        print(f"\n✅ Search completed in {data['execution_time_ms']}ms")
        print(f"\n📋 Query Intent:")
        intent = data['query_intent']
        print(f"   - Name candidates: {intent.get('name_candidates', [])}")
        print(f"   - Tags: {intent.get('query_tags', [])}")
        print(f"   - Season: {intent.get('season_hint', 'unknown')}")
        if intent.get('geo_hints', {}).get('place_name'):
            print(f"   - Location: {intent['geo_hints']['place_name']}")
        
        print(f"\n🎯 Found {len(data['candidates'])} candidates:")
        for i, candidate in enumerate(data['candidates'], 1):
            print(f"\n   {i}. {candidate['name_primary']}")
            print(f"      Match: {candidate['match_confidence']:.1%}")
            if candidate.get('category_norm'):
                print(f"      Category: {candidate['category_norm']}")
            if candidate.get('visual_tags'):
                for vt in candidate['visual_tags']:
                    print(f"      {vt['season']}: {', '.join(vt['tags'][:5])}")
            if candidate.get('match_explanation'):
                print(f"      Explanation: {candidate['match_explanation'][:100]}...")
        
        # Show MCP tool usage
        if data.get('tool_calls'):
            print(f"\n🔧 MCP Tools Used:")
            for tool_call in data['tool_calls']:
                tool_name = tool_call.get('tool', 'unknown')
                print(f"   - {tool_name}")
        
        return True
    except Exception as e:
        print(f"❌ Search failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"   Error detail: {json.dumps(error_detail, indent=2)}")
            except:
                print(f"   Error text: {e.response.text[:200]}")
        return False

def main():
    """Run all tests"""
    print("\n🌍 TourRAG Search Test")
    print("=" * 60)
    
    # Test 1: Health check
    if not test_health():
        print("\n❌ Server is not running or not accessible.")
        print("   Please start the server with: uvicorn app.main:app --reload")
        sys.exit(1)
    
    # Test 2: Search queries
    test_queries = [
        "Mount Fuji",
        "Mount Fuji in winter",
        "春天的樱花",
        "temple with cherry blossoms",
    ]
    
    # Use first query from command line if provided
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        test_search(query)
    else:
        # Test with first query
        test_search(test_queries[0])
        print(f"\n💡 Tip: Run with custom query: python test_search.py 'your query here'")
    
    print("\n" + "=" * 60)
    print("✅ Tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()

