#!/usr/bin/env python3
"""
Fetch real Wikipedia sections (including history) from Wikipedia API

This script:
1. Clears existing sections in viewpoint_wiki table
2. Fetches real Wikipedia data from Wikipedia API
3. Updates sections with real data including history
"""
import sys
import json
import time
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.database import db
from psycopg2.extras import RealDictCursor

# Wikipedia API endpoints by language
WIKIPEDIA_LANG_MAP = {
    'zh': 'zh.wikipedia.org',
    'ko': 'ko.wikipedia.org', 
    'ja': 'ja.wikipedia.org',
    'ar': 'ar.wikipedia.org',
    'th': 'th.wikipedia.org',
    'ru': 'ru.wikipedia.org',
    'hi': 'hi.wikipedia.org',
    'vi': 'vi.wikipedia.org',
    'en': 'en.wikipedia.org'
}

# Default to English
WIKIPEDIA_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
WIKIPEDIA_CONTENT_API = "https://en.wikipedia.org/w/api.php"

# Rate limiting: be respectful to Wikipedia servers
REQUEST_DELAY = 0.01  # 10ms between requests (increased to avoid 403)

# User-Agent header (required by Wikipedia API)
USER_AGENT = "TourRAG/1.0 (https://github.com/your-repo; contact@example.com)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json"
}


def detect_language_from_title(title: str) -> str:
    """
    Detect language from title characters
    
    Args:
        title: Wikipedia page title
        
    Returns:
        Language code (zh, ko, ja, ar, th, ru, hi, vi, en)
    """
    # Chinese characters
    if any('\u4e00' <= c <= '\u9fff' for c in title):
        return 'zh'
    # Korean characters
    if any('\uac00' <= c <= '\ud7a3' for c in title):
        return 'ko'
    # Japanese characters (Hiragana and Katakana)
    if any('\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' for c in title):
        return 'ja'
    # Arabic characters
    if any('\u0600' <= c <= '\u06ff' for c in title):
        return 'ar'
    # Thai characters
    if any('\u0e00' <= c <= '\u0e7f' for c in title):
        return 'th'
    # Cyrillic (Russian, etc.)
    if any('\u0400' <= c <= '\u04ff' for c in title):
        return 'ru'
    # Devanagari (Hindi, etc.)
    if any('\u0900' <= c <= '\u097f' for c in title):
        return 'hi'
    # Vietnamese (check for Vietnamese-specific characters)
    vietnamese_chars = 'àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ'
    if any(c in vietnamese_chars for c in title.lower()):
        return 'vi'
    return 'en'


def fetch_wikipedia_summary(title: str, lang: str = 'en', max_retries: int = 3) -> Optional[Dict[str, Any]]:
    """
    Fetch Wikipedia page summary using REST API with language support
    
    Args:
        title: Wikipedia page title
        lang: Language code (zh, ko, ja, ar, th, ru, hi, vi, en)
        max_retries: Maximum number of retry attempts
        
    Returns:
        Dict with extract, sections info, or None if not found
    """
    # Get API URL for the language
    lang_domain = WIKIPEDIA_LANG_MAP.get(lang, 'en.wikipedia.org')
    api_url = f"https://{lang_domain}/api/rest_v1/page/summary"
    
    for attempt in range(max_retries):
        try:
            url = f"{api_url}/{quote(title)}"
            response = requests.get(url, headers=HEADERS, timeout=15)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            elif response.status_code == 403:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 1.0  # Exponential backoff
                    print(f"  HTTP 403 for {title}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  Warning: HTTP 403 (Forbidden) for {title} after {max_retries} attempts")
                    return None
            else:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 0.5
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  Warning: HTTP {response.status_code} for {title}")
                    return None
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 0.5
                print(f"  Request error for {title}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                print(f"  Error fetching summary for {title}: {e}")
                return None
        except Exception as e:
            print(f"  Unexpected error for {title}: {e}")
            return None
    
    return None


def fetch_wikipedia_sections(title: str, lang: str = 'en') -> Optional[List[Dict[str, Any]]]:
    """
    Fetch Wikipedia page sections using MediaWiki API with language support
    
    Args:
        title: Wikipedia page title
        lang: Language code (zh, ko, ja, ar, th, ru, hi, vi, en)
        
    Returns:
        List of sections with title, content, and level, or None if error
    """
    try:
        # Get API URL for the language
        lang_domain = WIKIPEDIA_LANG_MAP.get(lang, 'en.wikipedia.org')
        api_url = f"https://{lang_domain}/w/api.php"
        
        # Get section list first
        params = {
            "action": "parse",
            "page": title,
            "format": "json",
            "prop": "sections",
            "sectionprop": "toclevel|level|line|number|index"
        }
        
        response = requests.get(api_url, params=params, headers=HEADERS, timeout=15)
        
        if response.status_code != 200:
            if response.status_code == 403:
                print(f"  Warning: HTTP 403 (Forbidden) for sections of {title}")
            return None
            
        data = response.json()
        
        if "error" in data:
            return None
            
        sections_list = data.get("parse", {}).get("sections", [])
        
        if not sections_list:
            return None
        
        # Fetch content for important sections (History, etc.)
        section_data = []
        important_sections = ["History", "Background", "Overview", "Description"]
        
        for section in sections_list:
            section_title = section.get("line", "")
            section_level = section.get("toclevel", 2)
            section_index = section.get("index", "")
            
            if not section_title or not section_index:
                continue
            
            # Fetch content for important sections or all if few sections
            should_fetch_content = (
                any(keyword.lower() in section_title.lower() for keyword in important_sections) or
                len(sections_list) <= 5  # Fetch all if page has few sections
            )
            
            content = ""
            if should_fetch_content:
                # Fetch section content
                content_params = {
                    "action": "parse",
                    "page": title,
                    "format": "json",
                    "prop": "text",
                    "section": section_index,
                    "disabletoc": "1"
                }
                
                time.sleep(REQUEST_DELAY)  # Rate limiting
                
                content_response = requests.get(api_url, params=content_params, headers=HEADERS, timeout=15)
                if content_response.status_code == 200:
                    content_data = content_response.json()
                    html_content = content_data.get("parse", {}).get("text", {}).get("*", "")
                    
                    if html_content:
                        # Clean HTML tags
                        import re
                        content = re.sub(r'<[^>]+>', '', html_content)
                        content = re.sub(r'\s+', ' ', content).strip()
                        content = content[:5000]  # Limit content length
            
            # Include section even if no content (for structure)
            section_data.append({
                "title": section_title,
                "content": content,
                "level": section_level,
                "index": section_index
            })
        
        return section_data if section_data else None
        
    except Exception as e:
        print(f"  Error fetching sections for {title}: {e}")
        import traceback
        traceback.print_exc()
        return None




def get_english_wikipedia_title(wikidata_qid: str, non_english_title: str = None) -> Optional[str]:
    """
    Get English Wikipedia title from Wikidata QID or Wikipedia cross-language links
    
    Args:
        wikidata_qid: Wikidata QID (e.g., "Q12345")
        non_english_title: Original non-English title for fallback search
        
    Returns:
        English Wikipedia title or None
    """
    # First try Wikidata API
    if wikidata_qid:
        try:
            params = {
                "action": "wbgetentities",
                "ids": wikidata_qid,
                "props": "sitelinks",
                "format": "json"
            }
            
            response = requests.get(
                "https://www.wikidata.org/w/api.php",
                params=params,
                headers=HEADERS,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                entities = data.get("entities", {})
                if wikidata_qid in entities:
                    sitelinks = entities[wikidata_qid].get("sitelinks", {})
                    enwiki = sitelinks.get("enwiki", {})
                    if enwiki:
                        return enwiki.get("title")
        except Exception as e:
            pass  # Fall through to Wikipedia API
    
    # Fallback: Try Wikipedia cross-language links API
    if non_english_title:
        try:
            # Detect language and use appropriate Wikipedia API
            detected_lang = detect_language_from_title(non_english_title)
            lang_domain = WIKIPEDIA_LANG_MAP.get(detected_lang, 'en.wikipedia.org')
            api_url = f"https://{lang_domain}/w/api.php"
            
            # Use Wikipedia API to get English title via langlinks
            params = {
                "action": "query",
                "titles": non_english_title,
                "prop": "langlinks",
                "lllang": "en",
                "format": "json"
            }
            
            response = requests.get(
                api_url,
                params=params,
                headers=HEADERS,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                pages = data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    langlinks = page_data.get("langlinks", [])
                    for link in langlinks:
                        if link.get("lang") == "en":
                            return link.get("*")  # English title
        except Exception as e:
            pass
    
    return None


def fetch_wikipedia_full_content(title: str, lang: str = 'en', prefer_english: bool = True) -> Optional[Dict[str, Any]]:
    """
    Fetch full Wikipedia page content including sections with language support
    
    Args:
        title: Wikipedia page title
        lang: Language code (zh, ko, ja, ar, th, ru, hi, vi, en)
        prefer_english: If True, try English first, then fallback to original language
        
    Returns:
        Dict with extract, sections, and citations, or None if error
    """
    # First try to get summary with specified language
    summary = fetch_wikipedia_summary(title, lang=lang)
    if not summary:
        return None
    
    time.sleep(REQUEST_DELAY)
    
    # Get sections with specified language
    sections = fetch_wikipedia_sections(title, lang=lang)
    
    result = {
        "extract": summary.get("extract", ""),
        "sections": sections or [],
        "title": summary.get("title", title),
        "url": summary.get("content_urls", {}).get("desktop", {}).get("page", "")
    }
    
    # Extract citations from summary if available
    citations = []
    if summary.get("content_urls"):
        citations.append({
            "ref": "wikipedia",
            "text": "Wikipedia",
            "url": summary.get("content_urls", {}).get("desktop", {}).get("page", "")
        })
    
    result["citations"] = citations
    
    return result


def clear_wiki_sections():
    """Clear all sections in viewpoint_wiki table"""
    print("Clearing existing sections in viewpoint_wiki table...")
    
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("""
                    UPDATE viewpoint_wiki
                    SET sections = NULL,
                        last_updated = CURRENT_TIMESTAMP
                """)
                affected = cursor.rowcount
                conn.commit()
                print(f"✓ Cleared sections for {affected} records")
                return affected
    except Exception as e:
        print(f"Error clearing sections: {e}")
        import traceback
        traceback.print_exc()
        return 0


def update_wiki_sections_batch(viewpoints: List[Dict[str, Any]], batch_size: int = 10, prefer_english: bool = True):
    """
    Update Wikipedia sections for viewpoints in batches
    
    Args:
        viewpoints: List of viewpoint dicts with viewpoint_id, wikipedia_title
        batch_size: Number of requests per batch (with delays)
    """
    updated = 0
    failed = 0
    not_found = 0
    
    try:
        with db.get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                for i, vp in enumerate(viewpoints, 1):
                    viewpoint_id = vp['viewpoint_id']
                    wikipedia_title = vp['wikipedia_title']
                    wikipedia_lang = vp.get('wikipedia_lang', 'en')
                    wikidata_qid = vp.get('wikidata_qid')
                    
                    # Detect language from title or use database language
                    detected_lang = detect_language_from_title(wikipedia_title)
                    has_non_ascii = any(ord(char) > 127 for char in wikipedia_title)
                    
                    # If title has non-ASCII characters, prefer detected language over database language
                    # (database language might be incorrect)
                    if has_non_ascii and detected_lang != 'en':
                        lang_to_use = detected_lang
                    elif wikipedia_lang and wikipedia_lang in WIKIPEDIA_LANG_MAP:
                        lang_to_use = wikipedia_lang
                    else:
                        lang_to_use = detected_lang
                    
                    # Try to use English title if current title is not English
                    title_to_use = wikipedia_title
                    lang_for_fetch = lang_to_use  # Default to detected language
                    
                    if (wikipedia_lang != 'en' or has_non_ascii) and prefer_english:
                        # Try to get English title from Wikidata
                        if wikidata_qid or wikipedia_title:
                            time.sleep(REQUEST_DELAY)  # Rate limiting for Wikidata API
                            english_title = get_english_wikipedia_title(wikidata_qid, wikipedia_title)
                            if english_title:
                                title_to_use = english_title
                                lang_for_fetch = 'en'
                                print(f"[{i}/{len(viewpoints)}] Using English title: {title_to_use} (original: {wikipedia_title})")
                            else:
                                # No English title found, use original language
                                lang_for_fetch = lang_to_use
                                print(f"[{i}/{len(viewpoints)}] No English title found, using {lang_to_use} Wikipedia: {wikipedia_title}")
                        else:
                            # No Wikidata QID, use original language
                            lang_for_fetch = lang_to_use
                            print(f"[{i}/{len(viewpoints)}] No Wikidata QID, using {lang_to_use} Wikipedia: {wikipedia_title}")
                    else:
                        print(f"[{i}/{len(viewpoints)}] Fetching data for: {wikipedia_title} (lang: {lang_to_use})")
                    
                    # Fetch real Wikipedia data with appropriate language
                    # Use the determined language (either English or original language)
                    wiki_data = fetch_wikipedia_full_content(title_to_use, lang=lang_for_fetch, prefer_english=False)
                    
                    if not wiki_data:
                        print(f"  ✗ No data found for {wikipedia_title}")
                        not_found += 1
                        time.sleep(REQUEST_DELAY)
                        continue
                    
                    # Update database
                    try:
                        cursor.execute("""
                            UPDATE viewpoint_wiki
                            SET sections = %s,
                                extract_text = COALESCE(%s, extract_text),
                                citations = COALESCE(%s, citations),
                                last_updated = CURRENT_TIMESTAMP
                            WHERE viewpoint_id = %s
                        """, (
                            json.dumps(wiki_data['sections']) if wiki_data.get('sections') else None,
                            wiki_data.get('extract'),
                            json.dumps(wiki_data.get('citations', [])),
                            viewpoint_id
                        ))
                        
                        updated += 1
                        sections_count = len(wiki_data.get('sections', []))
                        print(f"  ✓ Updated with {sections_count} sections")
                        
                    except Exception as e:
                        print(f"  ✗ Error updating database: {e}")
                        failed += 1
                    
                    # Commit every batch_size records
                    if i % batch_size == 0:
                        conn.commit()
                        print(f"  Committed batch ({i}/{len(viewpoints)})")
                    
                    # Rate limiting
                    time.sleep(REQUEST_DELAY)
                
                # Final commit
                conn.commit()
        
        return updated, failed, not_found
        
    except Exception as e:
        print(f"Error in batch update: {e}")
        import traceback
        traceback.print_exc()
        return updated, failed, not_found


def main():
    """Main function to fetch real Wikipedia sections"""
    print("=" * 60)
    print("Wikipedia Sections Fetch Script")
    print("=" * 60)
    
    # Fetch viewpoints with Wikipedia titles
    print("\nFetching viewpoints with Wikipedia data...")
    print("  Executing database query...")
    try:
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    vw.viewpoint_id, 
                    vw.wikipedia_title, 
                    vw.wikipedia_lang,
                    ve.name_primary,
                    wd.wikidata_qid
                FROM viewpoint_wiki vw
                JOIN viewpoint_entity ve ON vw.viewpoint_id = ve.viewpoint_id
                LEFT JOIN viewpoint_wikidata wd ON vw.viewpoint_id = wd.viewpoint_id
                WHERE vw.wikipedia_title IS NOT NULL
                ORDER BY vw.viewpoint_id
            """)
            print("  Fetching results...")
            viewpoints = cursor.fetchall()
        
        print(f"✓ Found {len(viewpoints)} viewpoints with Wikipedia titles")
    except Exception as e:
        print(f"✗ Error fetching viewpoints: {e}")
        import traceback
        traceback.print_exc()
        return
    
    if len(viewpoints) == 0:
        print("No viewpoints with Wikipedia titles found")
        return
    
    # Fetch and update sections
    print("\nFetching real Wikipedia sections...")
    print(f"This may take a while (estimated: {len(viewpoints) * 0.2:.1f} seconds)")
    print("Please be patient and respect Wikipedia's rate limits...\n")
    
    start_time = time.time()
    updated, failed, not_found = update_wiki_sections_batch(viewpoints, batch_size=10, prefer_english=True)
    elapsed = time.time() - start_time
    
    # Summary
    print("\n" + "=" * 60)
    print("Update Summary")
    print("=" * 60)
    print(f"Total viewpoints: {len(viewpoints)}")
    print(f"Successfully updated: {updated}")
    print(f"Failed: {failed}")
    print(f"Not found: {not_found}")
    print(f"Time elapsed: {elapsed:.1f}s")
    print(f"Average: {elapsed/len(viewpoints):.2f}s per viewpoint")
    print("=" * 60)
    
    # Verify
    print("\nVerification:")
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(sections) as with_sections
            FROM viewpoint_wiki
        """)
        stats = cursor.fetchone()
        print(f"  Total wiki records: {stats['total']}")
        print(f"  Records with sections: {stats['with_sections']}")


if __name__ == "__main__":
    main()
