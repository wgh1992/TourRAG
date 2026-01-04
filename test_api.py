#!/usr/bin/env python3
"""
Simple test script for TourRAG API
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def test_health():
    """Test health check endpoint"""
    print("=" * 60)
    print("1. Testing Health Check")
    print("=" * 60)
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_extract_intent():
    """Test extract query intent endpoint"""
    print("\n" + "=" * 60)
    print("2. Testing Extract Query Intent")
    print("=" * 60)
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/extract-query-intent",
            json={
                "user_text": "我想看春天的樱花，最好是日本的寺庙",
                "language": "zh"
            }
        )
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"\nQuery Intent:")
        print(f"  Name Candidates: {result['query_intent']['name_candidates']}")
        print(f"  Query Tags: {result['query_intent']['query_tags']}")
        print(f"  Season Hint: {result['query_intent']['season_hint']}")
        print(f"  Geo Hints: {result['query_intent']['geo_hints']}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_query():
    """Test main query endpoint"""
    print("\n" + "=" * 60)
    print("3. Testing Main Query Endpoint")
    print("=" * 60)
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/query",
            params={
                "user_text": "mountain",
                "top_k": 5
            }
        )
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"\nFound {len(result['candidates'])} candidates")
        print(f"Execution time: {result['execution_time_ms']}ms")
        print(f"\nTop Results:")
        for i, candidate in enumerate(result['candidates'][:3], 1):
            print(f"\n{i}. {candidate['name_primary']}")
            print(f"   Category: {candidate['category_norm']}")
            print(f"   Confidence: {candidate['match_confidence']:.2f}")
            if candidate.get('historical_summary'):
                summary = candidate['historical_summary'][:100]
                print(f"   Summary: {summary}...")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_viewpoint_detail():
    """Test viewpoint detail endpoint"""
    print("\n" + "=" * 60)
    print("4. Testing Viewpoint Detail Endpoint")
    print("=" * 60)
    try:
        response = requests.get(f"{BASE_URL}/api/v1/viewpoint/1")
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"\nViewpoint: {result['name_primary']}")
        print(f"Category: {result['category_norm']}")
        if result.get('wikipedia'):
            print(f"Wikipedia: {result['wikipedia']['title']}")
            print(f"Extract: {result['wikipedia']['extract'][:100]}...")
        if result.get('wikidata'):
            print(f"Wikidata QID: {result['wikidata']['qid']}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("TourRAG API Test Suite")
    print("=" * 60)
    
    results = []
    results.append(("Health Check", test_health()))
    results.append(("Extract Intent", test_extract_intent()))
    results.append(("Query", test_query()))
    results.append(("Viewpoint Detail", test_viewpoint_detail()))
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{name}: {status}")
    
    all_passed = all(result[1] for result in results)
    print("\n" + "=" * 60)
    if all_passed:
        print("All tests passed! ✓")
    else:
        print("Some tests failed. Please check the output above.")
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())

