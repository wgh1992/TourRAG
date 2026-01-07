#!/usr/bin/env python3
"""
Test script for GPT-4o-mini Agent with Tool Calling
"""
import requests
import json
import sys

API_BASE = "http://localhost:8000"

def test_agent_query(query):
    """Test agent query endpoint"""
    print("=" * 60)
    print(f"Testing Agent Query: '{query}'")
    print("=" * 60)
    
    try:
        response = requests.post(
            f"{API_BASE}/api/v1/agent/query",
            params={
                "user_query": query,
                "language": "auto"
            }
        )
        response.raise_for_status()
        data = response.json()
        
        print(f"\n✅ Agent Response:")
        print(f"\n📝 Answer:")
        print(data.get('answer', 'No answer provided'))
        
        print(f"\n🔧 Tool Calls ({len(data.get('tool_calls', []))} tools used):")
        for i, tool_call in enumerate(data.get('tool_calls', []), 1):
            print(f"\n   {i}. {tool_call.get('tool', 'unknown')}")
            print(f"      Arguments: {json.dumps(tool_call.get('arguments', {}), indent=6, ensure_ascii=False)[:200]}...")
            result = tool_call.get('result', {})
            if isinstance(result, dict):
                if 'candidates' in result:
                    print(f"      Found {result.get('count', 0)} candidates")
                elif 'results' in result:
                    print(f"      Ranked {result.get('count', 0)} results")
                elif 'query_intent' in result:
                    intent = result.get('query_intent', {})
                    print(f"      Extracted: tags={intent.get('query_tags', [])}, season={intent.get('season_hint')}")
        
        print(f"\n📊 Iterations: {data.get('iterations', 0)}")
        
        return True
    except Exception as e:
        print(f"❌ Agent query failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"   Error detail: {json.dumps(error_detail, indent=2)}")
            except:
                print(f"   Error text: {e.response.text[:200]}")
        return False

def main():
    """Run agent tests"""
    print("\n🤖 TourRAG GPT-4o-mini Agent Test")
    print("=" * 60)
    
    # Test queries
    test_queries = [
        "Mount Fuji in winter",
        "春天的樱花寺庙",
        "What are the best mountain viewpoints in Japan?",
        "Show me temples with cherry blossoms",
    ]
    
    # Use query from command line if provided
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        test_agent_query(query)
    else:
        # Test with first query
        test_agent_query(test_queries[0])
        print(f"\n💡 Tip: Run with custom query: python test_agent.py 'your query here'")
    
    print("\n" + "=" * 60)
    print("✅ Test completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()

