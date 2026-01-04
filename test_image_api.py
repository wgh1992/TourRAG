#!/usr/bin/env python3
"""
Test script for image processing with GPT-4o
"""
import requests
import json
import base64
from pathlib import Path

BASE_URL = "http://localhost:8000"

def test_image_query(image_path: str, user_text: str = None):
    """Test query with image input"""
    print("=" * 60)
    print("Testing Image Query with GPT-4o")
    print("=" * 60)
    
    # Check if image exists
    img_path = Path(image_path)
    if not img_path.exists():
        print(f"Error: Image file not found: {image_path}")
        return False
    
    # Read and encode image
    with open(img_path, "rb") as f:
        image_bytes = f.read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
    
    # Determine MIME type
    ext = img_path.suffix.lower()
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    mime_type = mime_types.get(ext, 'image/jpeg')
    
    print(f"\nImage: {image_path}")
    print(f"Size: {len(image_bytes)} bytes")
    print(f"MIME Type: {mime_type}")
    
    # Test extract_query_intent with image
    print("\n1. Testing extract_query_intent with image...")
    try:
        # Create a data URL for the image
        data_url = f"data:{mime_type};base64,{image_base64}"
        
        response = requests.post(
            f"{BASE_URL}/api/v1/extract-query-intent",
            json={
                "user_text": user_text or "What is this place?",
                "user_images": [{
                    "image_id": data_url,
                    "mime_type": mime_type
                }],
                "language": "auto"
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✓ Success!")
            print(f"\nQuery Intent:")
            print(f"  Query Tags: {result['query_intent']['query_tags']}")
            print(f"  Season Hint: {result['query_intent']['season_hint']}")
            print(f"  Name Candidates: {result['query_intent']['name_candidates']}")
            print(f"  Confidence Notes: {result['query_intent']['confidence_notes']}")
            return True
        else:
            print(f"✗ Failed: {response.status_code}")
            print(response.text)
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_image_upload(image_path: str, user_text: str = None):
    """Test query with image file upload"""
    print("\n" + "=" * 60)
    print("Testing Image Upload Query")
    print("=" * 60)
    
    img_path = Path(image_path)
    if not img_path.exists():
        print(f"Error: Image file not found: {image_path}")
        return False
    
    try:
        with open(img_path, "rb") as f:
            files = {
                "user_images": (img_path.name, f, "image/jpeg")
            }
            data = {
                "user_text": user_text or "What is this place?",
                "top_k": 5
            }
            
            response = requests.post(
                f"{BASE_URL}/api/v1/query",
                files=files,
                data=data
            )
        
        if response.status_code == 200:
            result = response.json()
            print("✓ Success!")
            print(f"\nFound {len(result['candidates'])} candidates")
            print(f"Execution time: {result['execution_time_ms']}ms")
            
            for i, candidate in enumerate(result['candidates'][:3], 1):
                print(f"\n{i}. {candidate['name_primary']}")
                print(f"   Category: {candidate['category_norm']}")
                print(f"   Confidence: {candidate['match_confidence']:.2f}")
                if candidate.get('query_tags'):
                    print(f"   Matched Tags: {candidate.get('query_tags', [])}")
            return True
        else:
            print(f"✗ Failed: {response.status_code}")
            print(response.text)
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python test_image_api.py <image_path> [user_text]")
        print("\nExample:")
        print("  python test_image_api.py test_image.jpg 'What is this place?'")
        sys.exit(1)
    
    image_path = sys.argv[1]
    user_text = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Test 1: Direct image data URL
    success1 = test_image_query(image_path, user_text)
    
    # Test 2: File upload
    success2 = test_image_upload(image_path, user_text)
    
    print("\n" + "=" * 60)
    if success1 and success2:
        print("All image tests passed! ✓")
    else:
        print("Some tests failed.")
    print("=" * 60)

