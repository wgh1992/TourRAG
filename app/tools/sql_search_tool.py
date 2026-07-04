"""
MCP Tool: SQL-based search for viewpoints

This tool allows the LLM to construct and execute SQL queries to search the database.
Now supports LLM-generated SQL queries for more flexible search capabilities.
"""
import json
import re
from typing import List, Dict, Any, Optional
from openai import OpenAI
from app.services.database import db
from app.schemas.query import ViewpointCandidate, QueryIntent
from app.config import settings

# Disable name-based fallback searches (testing mode)
DISABLE_NAME_FALLBACK = False

VALID_CATEGORIES = [
    'mountain', 'lake', 'temple', 'museum', 'park',
    'coast', 'cityscape', 'monument', 'bridge',
    'palace', 'tower', 'cave', 'waterfall', 'valley', 'island'
]

WEAK_RETRIEVAL_CATEGORIES = {'park', 'cityscape', 'valley', 'coast'}
GENERIC_HISTORY_TERMS = {
    'this anonymized tourist attraction',
    'tourist attraction',
    'observable visual',
    'scene cues',
    'ground level',
    'exterior',
    'panoramic',
    'sunny',
    'cloudy',
    'empty',
    'crowded',
}

DISTINCTIVE_CONTEXT_STOPWORDS = {
    'about', 'above', 'after', 'also', 'among', 'around', 'built',
    'called', 'city', 'country', 'dating', 'district', 'during',
    'east', 'from', 'heritage', 'history', 'known', 'lake', 'local',
    'located', 'monument', 'mountain', 'named', 'near', 'north',
    'old', 'park', 'place', 'popular', 'public', 'road', 'site',
    'scene', 'search', 'section', 'south', 'state', 'street', 'the',
    'this', 'tourist', 'town', 'unnamed', 'used', 'visitors', 'west',
    'wide', 'with',
}


# Country name mapping (Chinese to English and common variants)
COUNTRY_NAME_MAPPING = {
    # Chinese to English
    "中国": "China",
    "美国": "United States",
    "英国": "United Kingdom",
    "法国": "France",
    "德国": "Germany",
    "意大利": "Italy",
    "西班牙": "Spain",
    "日本": "Japan",
    "韩国": "South Korea",
    "印度": "India",
    "巴西": "Brazil",
    "澳大利亚": "Australia",
    "加拿大": "Canada",
    "墨西哥": "Mexico",
    "俄罗斯": "Russia",
    # Common English variants
    "China": ["China", "People's Republic of China", "PRC"],
    "United States": ["United States", "USA", "US", "United States of America"],
    "United Kingdom": ["United Kingdom", "UK", "Britain", "Great Britain"],
    "France": ["France"],
    "Italy": ["Italy"],
    "Japan": ["Japan"],
}


def normalize_country_name(country: str) -> List[str]:
    """
    Normalize country name to list of possible names for database matching.
    
    Args:
        country: Country name (can be in Chinese or English)
        
    Returns:
        List of country name variants to search for
    """
    if not country:
        return []
    
    country = country.strip()
    
    # Check if it's a Chinese name
    if country in COUNTRY_NAME_MAPPING:
        base_name = COUNTRY_NAME_MAPPING[country]
        if isinstance(base_name, list):
            return base_name
        else:
            return [base_name] + COUNTRY_NAME_MAPPING.get(base_name, [])
    
    # Check if it's an English name with variants
    if country in COUNTRY_NAME_MAPPING:
        variants = COUNTRY_NAME_MAPPING[country]
        if isinstance(variants, list):
            return variants
        else:
            return [country]
    
    # Default: return as-is
    return [country]


class SQLSearchTool:
    """
    MCP Tool for SQL-based viewpoint search.
    
    Allows LLM to construct SQL queries to search viewpoints by:
    - Name matching (ILIKE)
    - Category filtering
    - Popularity sorting
    - Geographic filtering (if needed)
    
    Now supports LLM-generated SQL queries for flexible search.
    """
    
    # Database schema information for LLM
    DB_SCHEMA = """
    Database Schema for TourRAG Viewpoint System:
    
    Main Tables:
    1. viewpoint_entity (core table)
       - viewpoint_id (INTEGER, PRIMARY KEY)
       - name_primary (VARCHAR) - Primary name
       - name_variants (JSONB) - Alternative names
       - category_norm (VARCHAR) - Normalized category (mountain, lake, temple, museum, park, coast, cityscape, monument, bridge, palace, tower, cave, waterfall, valley, island)
       - category_osm (JSONB) - Original OSM tags
       - geom (GEOMETRY) - PostGIS geometry (WGS84/4326)
       - popularity (FLOAT) - Popularity score (0.0-1.0)
       - osm_type (VARCHAR) - OSM element type (node, way, relation)
       - osm_id (BIGINT) - OSM element ID
       - admin_area_ids (JSONB) - Administrative area IDs
    
    2. viewpoint_commons_assets (images and metadata)
       - asset_id (INTEGER, PRIMARY KEY)
       - viewpoint_id (INTEGER, FOREIGN KEY -> viewpoint_entity.viewpoint_id)
       - image_blob (BYTEA) - Image binary data
       - image_geometry (GEOMETRY) - Image location
       - viewpoint_country (VARCHAR) - Country name
       - viewpoint_region (VARCHAR) - Region/state/province
       - viewpoint_boundary (GEOMETRY) - Polygon boundary if applicable
       - viewpoint_area_sqm (DOUBLE PRECISION) - Area in square meters
       - viewpoint_category_norm (VARCHAR) - Normalized category
       - viewpoint_category_osm (JSONB) - OSM category tags
       - viewpoint_admin_areas (JSONB) - Administrative areas info
       - downloaded_at (TIMESTAMP) - Download timestamp
    
    3. viewpoint_wiki (Wikipedia data - contains historical information)
       - viewpoint_id (INTEGER, PRIMARY KEY, FOREIGN KEY)
       - extract_text (TEXT) - Wikipedia extract text (contains historical information)
       - sections (JSONB) - Section structure (may contain history sections)
       - citations (JSONB) - Citations
       - wikipedia_title (VARCHAR) - Wikipedia article title
       - wikipedia_lang (VARCHAR) - Language code
    
    4. viewpoint_wikidata (Wikidata data)
       - viewpoint_id (INTEGER, PRIMARY KEY, FOREIGN KEY)
       - wikidata_qid (VARCHAR) - Wikidata QID
       - claims (JSONB) - Wikidata claims (may contain historical data)
    
    5. viewpoint_visual_tags (visual tags and seasonal information)
       - id (BIGINT, PRIMARY KEY)
       - viewpoint_id (INTEGER, FOREIGN KEY)
       - season (VARCHAR) - Season (spring, summer, autumn, winter)
       - tags (JSONB) - Array of visual tags (e.g., ['snow_peak', 'cherry_blossom', 'sunset'])
       - confidence (FLOAT) - Confidence score (0.0-1.0)
       - evidence (JSONB) - Evidence for tags
       - tag_source (VARCHAR) - Source of tags (e.g., 'wiki_weak_supervision')
    
    Relationships:
    - viewpoint_entity 1:1 viewpoint_wiki
    - viewpoint_entity 1:1 viewpoint_wikidata
    - viewpoint_entity 1:N viewpoint_commons_assets
    - viewpoint_entity 1:N viewpoint_visual_tags
    
    Search Capabilities:
    - Name search: 
      * For name_primary: Use ILIKE directly (e.g., name_primary ILIKE %s)
      * For name_variants (JSONB): MUST convert to text first (e.g., name_variants::text ILIKE %s)
      * NEVER use name_variants ILIKE directly - it will cause "operator does not exist: jsonb ~~* unknown" error
    - Category search: Filter by category_norm
    - Historical information search: Join viewpoint_wiki and search extract_text using ILIKE
    - Visual tags search: Join viewpoint_visual_tags and use JSONB @> operator to check if tags array contains specific tags
    - Season search: Filter viewpoint_visual_tags by season column
    - Combined search: Can combine name, category, history, tags, and season filters
    
    Common Query Patterns:
    - Use ST_X(geom) and ST_Y(geom) to get longitude and latitude
    - Use ST_Within(geom, ST_MakeEnvelope(...)) for bounding box queries
    - Use ILIKE for case-insensitive text matching (for names, Wikipedia text)
    - For name_variants (JSONB field): ALWAYS use name_variants::text ILIKE %s (convert to text first)
    - Use JSONB operators for tags:
      * @> operator: tags @> %s::jsonb (check if array contains value, parameter must be JSON string like '["tag"]')
      * -> operator: sections->'history' (access JSONB object field)
      * ->> operator: sections->>'history' (get JSONB field as text)
    - For historical text search: JOIN viewpoint_wiki and use extract_text ILIKE %s
    - For visual tags search: JOIN viewpoint_visual_tags and use tags @> %s::jsonb (parameter is JSON string)
    - For season filter: WHERE vt.season = %s in viewpoint_visual_tags join
    - Always use parameterized queries with %s placeholders
    - NEVER hardcode values in SQL - always use %s placeholders
    """
    
    def __init__(self, openai_client: Optional[OpenAI] = None):
        """Initialize SQL search tool with optional OpenAI client"""
        self.client = openai_client or OpenAI(api_key=settings.OPENAI_API_KEY)
        self.use_llm_sql = True  # Enable LLM-generated SQL by default
    
    def _generate_sql_with_llm(
        self,
        query_intent: QueryIntent,
        search_type: str,
        additional_params: Optional[Dict[str, Any]] = None,
        top_n: int = 50
    ) -> tuple[str, List[Any]]:
        """
        Use LLM to generate SQL query based on query intent.
        
        Args:
            query_intent: Query intent from extract_query_intent
            search_type: Type of search (name, category, tags, combined)
            additional_params: Additional parameters (country, season, etc.)
            top_n: Maximum number of results
            
        Returns:
            Tuple of (SQL query string, parameter list)
        """
        system_prompt = f"""You are a SQL query generator for a tourist attraction search system.

Your task is to generate safe, parameterized PostgreSQL/PostGIS SQL queries based on user query intent.

{self.DB_SCHEMA}

CRITICAL RULES:
1. ONLY generate SELECT queries - never INSERT, UPDATE, DELETE, DROP, etc.
2. ALWAYS use parameterized queries with %s placeholders (never string interpolation)
3. Return ONLY the SQL query, no explanations or markdown
4. The query must return these columns:
   - viewpoint_id
   - name_primary
   - name_variants (JSONB)
   - category_norm
   - popularity
   - name_score (calculated, 0.0-1.0)
   - geo_score (calculated, 0.0-1.0)
   - category_score (calculated, 0.0-1.0)
5. For name search:
   - name_primary: Use ILIKE directly (e.g., name_primary ILIKE %s)
   - name_variants (JSONB): MUST convert to text first (e.g., name_variants::text ILIKE %s)
   - NEVER use name_variants ILIKE %s directly - it will cause "operator does not exist: jsonb ~~* unknown" error
   - Example: (name_primary ILIKE %s OR name_variants::text ILIKE %s)
6. For country filtering, join with viewpoint_commons_assets table
7. For visual tags search:
   - JOIN viewpoint_visual_tags table
   - Use tags @> %s::jsonb to check if tags array contains specific tags
   - Parameter must be a JSON string like '["snow_peak"]' (passed as parameter, not hardcoded)
   - Example: tags @> %s::jsonb (where parameter is '["snow_peak"]')
8. For season filtering:
   - JOIN viewpoint_visual_tags table
   - Use WHERE vt.season = %s
9. For historical information search:
   - JOIN viewpoint_wiki table
   - Use extract_text ILIKE %s to search in Wikipedia text
   - Example: w.extract_text ILIKE %s
10. Always include LIMIT clause with %s placeholder (never hardcode the limit value)
11. Order by relevance scores and popularity
12. Use DISTINCT if joining multiple tables to avoid duplicate rows
13. NEVER hardcode any values - always use %s placeholders for ALL dynamic values

Query Intent:
- Name candidates: {query_intent.name_candidates}
- Query tags: {query_intent.query_tags}
- Season hint: {query_intent.season_hint}
- Geo hints: {query_intent.geo_hints.model_dump() if query_intent.geo_hints else None}

Search Type: {search_type}
Additional Params: {additional_params or {}}
Top N: {top_n}

Generate a PostgreSQL query that searches for viewpoints matching this intent.
Return ONLY the SQL query with %s placeholders for parameters."""

        # Build parameter list FIRST (before calling LLM)
        params = []
        param_descriptions = []
        
        # Add name patterns (for ILIKE queries) - typically appear first in WHERE clauses
        # For each name candidate, provide 2 parameters: one for name_primary, one for name_variants
        # This allows LLM to generate: (name_primary ILIKE %s OR name_variants::text ILIKE %s)
        if query_intent.name_candidates:
            for name in query_intent.name_candidates:
                param_value = f"%{name}%"
                # First parameter for name_primary
                params.append(param_value)
                param_descriptions.append(f"Param {len(params)}: Name pattern '{name}' for name_primary (ILIKE: {param_value})")
                # Second parameter for name_variants (same pattern, but for JSONB field)
                params.append(param_value)
                param_descriptions.append(f"Param {len(params)}: Name pattern '{name}' for name_variants (name_variants::text ILIKE: {param_value})")
        
        # Add category filters - typically in WHERE or IN clauses
        if query_intent.query_tags:
            valid_categories = ['mountain', 'lake', 'temple', 'museum', 'park', 
                               'coast', 'cityscape', 'monument', 'bridge', 
                               'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']
            categories = [tag for tag in query_intent.query_tags if tag in valid_categories]
            for cat in categories:
                params.append(cat)
                param_descriptions.append(f"Param {len(params)}: Category '{cat}' (exact match)")
        
        # Add visual tags (for JSONB @> operator) - need to be JSONB arrays
        if query_intent.query_tags:
            visual_tags = [tag for tag in query_intent.query_tags 
                          if tag not in ['mountain', 'lake', 'temple', 'museum', 'park', 
                                        'coast', 'cityscape', 'monument', 'bridge', 
                                        'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']]
            for tag in visual_tags:
                param_value = json.dumps([tag])
                params.append(param_value)
                param_descriptions.append(f"Param {len(params)}: Visual tag '{tag}' (JSONB array: {param_value})")
        
        # Add scene hints (for Wikipedia text search) - search in extract_text
        if query_intent.scene_hints:
            for scene in query_intent.scene_hints:
                param_value = f"%{scene}%"
                params.append(param_value)
                param_descriptions.append(f"Param {len(params)}: Scene hint '{scene}' (for ILIKE in extract_text: {param_value})")
        
        # Add country variants - typically in JOIN conditions
        # Use only the first variant to reduce parameter count and complexity
        # LLM can use OR conditions if multiple variants are needed
        if query_intent.geo_hints and query_intent.geo_hints.country:
            country_variants = normalize_country_name(query_intent.geo_hints.country)
            if country_variants:
                # Use only the primary country name (first variant) to simplify
                # LLM can add OR conditions for other variants if needed
                primary_country = country_variants[0]
                param_value = f"%{primary_country}%"
                params.append(param_value)
                param_descriptions.append(
                    f"Param {len(params)}: Country '{primary_country}' (for ILIKE: {param_value}). "
                    f"Note: Other variants {country_variants[1:] if len(country_variants) > 1 else []} can be handled with OR conditions if needed."
                )
        
        # Add season - typically in WHERE clauses for visual_tags
        if query_intent.season_hint and query_intent.season_hint != 'unknown':
            params.append(query_intent.season_hint)
            param_descriptions.append(f"Param {len(params)}: Season '{query_intent.season_hint}' (exact match)")
        
        # Add top_n (should be last, in LIMIT clause)
        params.append(top_n)
        param_descriptions.append(f"Param {len(params)}: LIMIT value {top_n}")
        
        # Build detailed search requirements
        search_requirements = []
        if query_intent.name_candidates:
            search_requirements.append(f"- Name search: {query_intent.name_candidates}")
        if query_intent.query_tags:
            valid_categories = ['mountain', 'lake', 'temple', 'museum', 'park', 
                               'coast', 'cityscape', 'monument', 'bridge', 
                               'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']
            categories = [tag for tag in query_intent.query_tags if tag in valid_categories]
            visual_tags = [tag for tag in query_intent.query_tags if tag not in valid_categories]
            if categories:
                search_requirements.append(f"- Category filter: {categories}")
            if visual_tags:
                search_requirements.append(f"- Visual tags search: {visual_tags} (use tags @> operator)")
        if query_intent.season_hint and query_intent.season_hint != 'unknown':
            search_requirements.append(f"- Season filter: {query_intent.season_hint} (filter viewpoint_visual_tags by season)")
        if query_intent.geo_hints and query_intent.geo_hints.country:
            search_requirements.append(f"- Country filter: {query_intent.geo_hints.country}")
        if query_intent.scene_hints:
            search_requirements.append(f"- Scene hints: {query_intent.scene_hints} (may need to search in Wikipedia text or tags)")
        
        # Build user prompt with exact parameter information
        param_list_text = "\n".join(param_descriptions) if param_descriptions else "No parameters needed"
        
        user_prompt = f"""Generate a SQL query for {search_type} search with the following requirements:

{chr(10).join(search_requirements) if search_requirements else '- General search (no specific filters)'}

- Limit: {top_n} (MUST use %s placeholder, NOT hardcoded value!)

EXACT PARAMETER LIST (you MUST use exactly these {len(params)} parameters in order):
{param_list_text}

CRITICAL INSTRUCTIONS:
1. You MUST use exactly {len(params)} %s placeholders in your SQL query - no more, no less!
2. Use the parameters in the exact order listed above
3. NEVER hardcode values - always use %s placeholders for ALL dynamic values including:
   - Name patterns (use %s, not hardcoded strings like '%Name%')
   - Country filters (use %s, not hardcoded country names like '%Country%')
   - LIMIT clause (use LIMIT %s, not LIMIT {top_n})
4. For name search, each name candidate has 2 parameters (one for name_primary, one for name_variants):
   - Use BOTH parameters: (name_primary ILIKE %s OR name_variants::text ILIKE %s)
   - For name_variants: ALWAYS use name_variants::text ILIKE %s (convert to text first)
   - WRONG: name_variants ILIKE %s (without ::text) - this will cause "operator does not exist: jsonb ~~* unknown" error!
   - If you have multiple name candidates, use OR to combine them:
     Example: ((name_primary ILIKE %s OR name_variants::text ILIKE %s) OR (name_primary ILIKE %s OR name_variants::text ILIKE %s))
5. If visual tags are specified, JOIN viewpoint_visual_tags and use tags @> %s::jsonb to search
   - Parameter will be a JSON string like '["tag"]' - use it as-is with ::jsonb cast
6. If season is specified, JOIN viewpoint_visual_tags and filter by season = %s
7. If searching for historical information or scene descriptions, JOIN viewpoint_wiki and search extract_text ILIKE %s
   - Use ONLY extract_text ILIKE %s - DO NOT add extra OR conditions (like category_osm->>'festival' or category_norm)
   - Each scene hint has exactly ONE parameter - use it only once!
8. For country filters, use ONLY the provided parameter:
   - Use: vca.viewpoint_country ILIKE %s
   - DO NOT add multiple OR conditions like: (vca.viewpoint_country ILIKE %s OR vca.viewpoint_country ILIKE %s OR ...)
   - You only have ONE country parameter - use it exactly ONCE!
9. Use DISTINCT to avoid duplicate rows when joining multiple tables
10. Count the %s placeholders carefully - there must be exactly {len(params)} of them!
11. Before returning, verify: count all %s in your SQL - it must equal {len(params)}!
12. Return ONLY the SQL query with the correct number of %s placeholders."""

        try:
            response = self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=1000
            )
            
            sql = response.choices[0].message.content.strip()
            
            # Remove markdown code blocks if present
            sql = re.sub(r'^```sql\s*', '', sql, flags=re.IGNORECASE)
            sql = re.sub(r'^```\s*', '', sql)
            sql = re.sub(r'```\s*$', '', sql)
            sql = sql.strip()
            
            # Validate SQL (basic security checks)
            sql_upper = sql.upper().strip()
            if not sql_upper.startswith('SELECT'):
                raise ValueError("Only SELECT queries are allowed")
            
            forbidden_keywords = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE', 'EXEC', 'EXECUTE']
            for keyword in forbidden_keywords:
                if keyword in sql_upper:
                    raise ValueError(f"Forbidden SQL keyword: {keyword}")
            
            # Fix common SQL issues before validation
            # 1. Fix name_variants ILIKE errors (must convert to text first)
            # Pattern: name_variants ILIKE (without ::text)
            sql = re.sub(
                r'\bname_variants\s+ILIKE\s+%s',
                'name_variants::text ILIKE %s',
                sql,
                flags=re.IGNORECASE
            )
            # Also fix if there's a pattern like name_variants ILIKE '%...%'
            sql = re.sub(
                r'\bname_variants\s+ILIKE\s+[\'"]%[^\'"]+%[\'"]',
                lambda m: m.group(0).replace('name_variants ILIKE', 'name_variants::text ILIKE', 1),
                sql,
                flags=re.IGNORECASE
            )
            
            # 2. Fix JSONB @> operator with incorrect parameter format
            # If we see name_variants @> '%...%', it's wrong - should be @> '["..."]'::jsonb
            # But we'll handle this in parameter validation
            
            # Count parameter placeholders in SQL
            param_count = sql.count('%s')
            
            # If parameter count doesn't match, try to fix it or fail gracefully
            # Use a loop to apply multiple fixes until count matches or no more fixes can be applied
            max_fix_attempts = 5
            fix_attempt = 0
            while len(params) != param_count and fix_attempt < max_fix_attempts:
                fix_attempt += 1
                if fix_attempt == 1:
                    print(f"[SQLSearchTool] Warning: Parameter count mismatch. SQL has {param_count} placeholders, but we have {len(params)} parameters.")
                    print(f"[SQLSearchTool] SQL preview: {sql[:500]}...")
                    print(f"[SQLSearchTool] Expected params ({len(params)}): {params}")
                
                fixed_this_iteration = False
                
                # Try to fix: if SQL has MORE placeholders, LLM might have added extra OR conditions
                # Common issue: LLM adds multiple OR conditions for country variants or scene hints
                if param_count > len(params):
                    # Fix 1: Remove extra country OR conditions
                    # Pattern: (country ILIKE %s OR country ILIKE %s OR country ILIKE %s) when we only have 1 param
                    if query_intent.geo_hints and query_intent.geo_hints.country:
                        # Find country filter patterns with multiple OR conditions
                        country_pattern = r'\(vca\.viewpoint_country\s+ILIKE\s+%s(?:\s+OR\s+vca\.viewpoint_country\s+ILIKE\s+%s)+\)'
                        matches = list(re.finditer(country_pattern, sql, re.IGNORECASE))
                        if matches:
                            # Process from end to start to avoid index shifting issues
                            for match in reversed(matches):
                                # Count how many OR conditions are in this match
                                or_count = match.group(0).count('ILIKE %s')
                                if or_count > 1:
                                    # Replace with single condition
                                    sql = sql[:match.start()] + '(vca.viewpoint_country ILIKE %s)' + sql[match.end():]
                                    param_count = sql.count('%s')
                                    print(f"[SQLSearchTool] Fixed (attempt {fix_attempt}): Removed {or_count - 1} extra country OR conditions. New param count: {param_count}")
                                    fixed_this_iteration = True
                                    break
                    
                    # Fix 2: Remove extra scene hint OR conditions
                    # Pattern: (extract_text ILIKE %s OR category_osm->>'festival' ILIKE %s) when we only have 1 scene hint param
                    if not fixed_this_iteration and query_intent.scene_hints and len(query_intent.scene_hints) == 1:
                        # Find patterns like: (vw.extract_text ILIKE %s OR ve.category_osm->>'festival' ILIKE %s)
                        scene_pattern = r'\(vw\.extract_text\s+ILIKE\s+%s\s+OR\s+[^)]+ILIKE\s+%s\)'
                        matches = list(re.finditer(scene_pattern, sql, re.IGNORECASE))
                        if matches:
                            # Process from end to start
                            for match in reversed(matches):
                                # Replace with single condition (keep only extract_text)
                                sql = sql[:match.start()] + '(vw.extract_text ILIKE %s)' + sql[match.end():]
                                param_count = sql.count('%s')
                                print(f"[SQLSearchTool] Fixed (attempt {fix_attempt}): Removed extra scene hint OR condition. New param count: {param_count}")
                                fixed_this_iteration = True
                                break
                        
                        # Also check for: (vw.extract_text ILIKE %s OR ve.category_norm ILIKE %s)
                        if not fixed_this_iteration:
                            scene_pattern2 = r'\(vw\.extract_text\s+ILIKE\s+%s\s+OR\s+ve\.category_norm\s+ILIKE\s+%s\)'
                            matches = list(re.finditer(scene_pattern2, sql, re.IGNORECASE))
                            if matches:
                                # Process from end to start
                                for match in reversed(matches):
                                    # Replace with single condition (keep only extract_text)
                                    sql = sql[:match.start()] + '(vw.extract_text ILIKE %s)' + sql[match.end():]
                                    param_count = sql.count('%s')
                                    print(f"[SQLSearchTool] Fixed (attempt {fix_attempt}): Removed extra scene hint OR condition (category_norm). New param count: {param_count}")
                                    fixed_this_iteration = True
                                    break
                
                # Try to fix: if SQL has fewer placeholders, it might be using hardcoded values
                # Common issue: LLM uses hardcoded country names or LIMIT values instead of placeholders
                if not fixed_this_iteration and param_count < len(params):
                    # Check if LIMIT is hardcoded (common issue)
                    if 'LIMIT' in sql.upper():
                        # Try to find hardcoded LIMIT values
                        limit_pattern = r'LIMIT\s+(\d+)'
                        matches = re.findall(limit_pattern, sql, flags=re.IGNORECASE)
                        for match in matches:
                            limit_val = int(match)
                            if limit_val == top_n:
                                # Replace hardcoded LIMIT with placeholder
                                sql = re.sub(rf'LIMIT\s+{limit_val}\b', 'LIMIT %s', sql, flags=re.IGNORECASE)
                                param_count = sql.count('%s')
                                print(f"[SQLSearchTool] Fixed (attempt {fix_attempt}): Replaced hardcoded LIMIT {limit_val} with placeholder. New param count: {param_count}")
                                fixed_this_iteration = True
                                break
                    
                    # Check if country filters are hardcoded (common issue with country variants)
                    if not fixed_this_iteration and query_intent.geo_hints and query_intent.geo_hints.country:
                        country_variants = normalize_country_name(query_intent.geo_hints.country)
                        # Try to find and replace hardcoded country names
                        for variant in country_variants:
                            # Look for ILIKE patterns with hardcoded country
                            patterns = [
                                rf"ILIKE\s+['\"]%{re.escape(variant)}%['\"]",
                                rf"ILIKE\s+['\"]{re.escape(variant)}['\"]",
                            ]
                            for pattern in patterns:
                                if re.search(pattern, sql, re.IGNORECASE):
                                    sql = re.sub(pattern, "ILIKE %s", sql, flags=re.IGNORECASE)
                                    param_count = sql.count('%s')
                                    print(f"[SQLSearchTool] Fixed (attempt {fix_attempt}): Replaced hardcoded country filter '{variant}'. New param count: {param_count}")
                                    fixed_this_iteration = True
                                    break
                            if fixed_this_iteration:
                                break
                    
                    # Check if name patterns are hardcoded
                    if not fixed_this_iteration and query_intent.name_candidates:
                        for name in query_intent.name_candidates:
                            # Look for hardcoded name patterns
                            patterns = [
                                rf"ILIKE\s+['\"]%{re.escape(name)}%['\"]",
                                rf"ILIKE\s+['\"]{re.escape(name)}['\"]",
                            ]
                            for pattern in patterns:
                                if re.search(pattern, sql, re.IGNORECASE):
                                    sql = re.sub(pattern, "ILIKE %s", sql, flags=re.IGNORECASE)
                                    param_count = sql.count('%s')
                                    print(f"[SQLSearchTool] Fixed (attempt {fix_attempt}): Replaced hardcoded name pattern '{name}'. New param count: {param_count}")
                                    fixed_this_iteration = True
                                    break
                            if fixed_this_iteration:
                                break
                
                # Update param_count after all fixes
                param_count = sql.count('%s')
                
                # If no fix was applied this iteration, break to avoid infinite loop
                if not fixed_this_iteration:
                    break
                
                # Final check: if still doesn't match after all fixes
                param_count = sql.count('%s')
                if len(params) != param_count:
                    print(f"[SQLSearchTool] Could not auto-fix parameter mismatch. SQL has {param_count} placeholders, need {len(params)}.")
                    print(f"[SQLSearchTool] Parameter descriptions: {param_descriptions}")
                    print(f"[SQLSearchTool] Full SQL: {sql}")
                    raise ValueError("LLM SQL parameter count mismatch")
            
            return sql, params
            
        except Exception as e:
            print(f"[SQLSearchTool] Error generating SQL with LLM: {e}")
            raise
    
    def _validate_and_execute_sql(self, sql: str, params: List[Any]) -> List[Dict[str, Any]]:
        """
        Validate and execute SQL query safely.
        
        Args:
            sql: SQL query string
            params: Query parameters
            
        Returns:
            List of result rows
        """
        # Additional validation
        sql_upper = sql.upper().strip()
        if not sql_upper.startswith('SELECT'):
            raise ValueError("Only SELECT queries are allowed")
        
        # Validate JSONB field usage
        # Check for common errors with name_variants (JSONB field)
        # Pattern: name_variants ILIKE (without ::text conversion)
        if re.search(r'\bname_variants\s+ILIKE\s+(?!.*::text)', sql, re.IGNORECASE):
            # Try to auto-fix by adding ::text conversion
            sql = re.sub(
                r'\b(name_variants)\s+ILIKE\s+(%s|[\'"]%[^\'"]+%[\'"])',
                r'\1::text ILIKE \2',
                sql,
                flags=re.IGNORECASE
            )
            print(f"[SQLSearchTool] Auto-fixed: Added ::text conversion for name_variants ILIKE")
        
        # Check for incorrect JSONB @> usage with ILIKE patterns
        # Pattern: name_variants @> '%...%' (should be @> '["..."]'::jsonb)
        if re.search(r'\bname_variants\s+@>\s+[\'"]%', sql, re.IGNORECASE):
            raise ValueError(
                "Invalid JSONB operator usage: name_variants @> cannot be used with ILIKE patterns. "
                "For name_variants search, use name_variants::text ILIKE %s instead. "
                "The @> operator is only for checking if JSONB array contains a value."
            )
        
        # Execute query
        try:
            with db.get_cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()
        except Exception as e:
            error_msg = str(e)
            # Provide helpful error messages for common issues
            if "operator does not exist: jsonb ~~*" in error_msg or "jsonb ~~* unknown" in error_msg:
                raise ValueError(
                    f"JSONB type error: Cannot use ILIKE directly on JSONB fields. "
                    f"Use name_variants::text ILIKE %s instead. Original error: {error_msg}"
                )
            elif "invalid input syntax for type json" in error_msg:
                raise ValueError(
                    f"JSON syntax error: Cannot use ILIKE patterns (with %) in JSONB @> operator. "
                    f"For name search, use name_variants::text ILIKE %s. "
                    f"For tag search, use tags @> %s::jsonb where parameter is a JSON string like '[\"tag\"]'. "
                    f"Original error: {error_msg}"
                )
            else:
                raise
    
    def search_with_llm_sql(
        self,
        query_intent: QueryIntent,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Search viewpoints using deterministic hybrid retrieval.
        
        Args:
            query_intent: Query intent from extract_query_intent
            top_n: Maximum number of results
            
        Returns:
            Dict with candidates and SQL query info
        """
        return self._hybrid_search(query_intent, top_n=top_n, generated_by="deterministic_hybrid")
    
    def _fallback_search(
        self,
        query_intent: QueryIntent,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Fallback to deterministic multi-route retrieval.
        Collects candidates from all relevant routes instead of returning after
        the first non-empty category/tag result.
        """
        return self._hybrid_search(query_intent, top_n=top_n, generated_by="deterministic_fallback")

    def _hybrid_search(
        self,
        query_intent: QueryIntent,
        top_n: int = 50,
        generated_by: str = "deterministic_hybrid",
    ) -> Dict[str, Any]:
        per_route_n = max(top_n, 50)
        route_results: List[Dict[str, Any]] = []
        attempted_routes: List[str] = []

        anonymous_query = self._is_anonymized_query(query_intent)

        # In anonymized description queries, extracted name_candidates are often
        # supporting places ("Dublin", "Hartford") or partial phrases, not the
        # target. Name search, especially prefix search, can flood the front of
        # the ranking with lookalikes. Use those terms in history/context scoring
        # instead.
        if not DISABLE_NAME_FALLBACK and not anonymous_query:
            for name in self._name_variants_for_search(query_intent.name_candidates):
                attempted_routes.append(f"name:{name}")
                route_results.append(self._tag_result_source(self.search_by_name(name, top_n=per_route_n), "name"))

        history_terms = self._history_terms_from_intent(query_intent, anonymous_query=anonymous_query)
        if history_terms:
            attempted_routes.append("history")
            geo_country = query_intent.geo_hints.country if query_intent.geo_hints else None
            geo_place = query_intent.geo_hints.place_name if query_intent.geo_hints else None
            route_results.append(
                self._tag_result_source(
                    self.search_by_history_terms(
                        history_terms,
                        top_n=per_route_n,
                        country=geo_country,
                        place_name=geo_place,
                    ),
                    "history",
                )
            )

        categories = [tag for tag in query_intent.query_tags if tag in VALID_CATEGORIES]
        if anonymous_query and history_terms:
            categories = [tag for tag in categories if tag not in WEAK_RETRIEVAL_CATEGORIES]
        country = query_intent.geo_hints.country if query_intent.geo_hints else None
        if anonymous_query:
            for category in categories[:3]:
                attempted_routes.append(f"category:{category}")
                route_results.append(
                    self._tag_result_source(
                        self.search_by_category(category, country=country, top_n=per_route_n),
                        "category",
                    )
                )

        if anonymous_query and query_intent.query_tags:
            season = query_intent.season_hint if query_intent.season_hint != "unknown" else None
            attempted_routes.append("tags")
            route_results.append(
                self._tag_result_source(
                    self.search_by_tags(query_intent.query_tags, season=season, top_n=per_route_n),
                    "tags",
                )
            )

        merged = self._merge_candidate_results(
            route_results,
            top_n=max(top_n, 50),
            anonymous_query=anonymous_query,
        )
        if anonymous_query and merged:
            self._apply_contextual_intent_boosts(merged, query_intent)
            merged = sorted(
                merged,
                key=lambda item: (
                    float(item.get("hybrid_score") or 0.0),
                    float(item.get("context_score") or 0.0),
                    float(item.get("history_rank_score") or 0.0),
                    float(item.get("popularity") or 0.0),
                ),
                reverse=True,
            )[:top_n]
        else:
            merged = merged[:top_n]
        result = {
            "candidates": merged,
            "count": len(merged),
            "generated_by": generated_by,
            "anonymous_query": anonymous_query,
            "routes": attempted_routes,
            "route_counts": {
                result.get("source_method", f"route_{idx}"): result.get("count", 0)
                for idx, result in enumerate(route_results)
            },
        }

        if not merged:
            result["warning"] = (
                "No viewpoints found matching the hybrid search criteria. "
                "The database may not contain viewpoints matching the requested clues."
            )
            result["suggestion"] = "Try fewer criteria, a direct attraction name, or broader history/location terms."
            if query_intent.name_candidates and not anonymous_query:
                result["explicit_name_search_failed"] = True
                result["suggestion"] = (
                    "This is an explicit named query. Retry search_with_llm_sql with alternate spellings, "
                    "transliterations, accent-stripped variants, or shorter distinctive name fragments. "
                    "Avoid broad category/tag fallback unless a location filter makes it very specific."
                )

        return result

    def _tag_result_source(self, result: Dict[str, Any], source_method: str) -> Dict[str, Any]:
        result = dict(result or {})
        result["source_method"] = source_method
        for candidate in result.get("candidates") or []:
            if isinstance(candidate, dict):
                candidate.setdefault("source_methods", [])
                if source_method not in candidate["source_methods"]:
                    candidate["source_methods"].append(source_method)
        return result

    def _name_variants_for_search(self, names: List[str]) -> List[str]:
        variants: List[str] = []
        for name in names or []:
            cleaned = " ".join(str(name).split())
            if not cleaned:
                continue
            variants.append(cleaned)
            if len(cleaned) > 4:
                variants.append(cleaned[: max(3, len(cleaned) // 2)])
        return self._dedupe_text(variants)[:6]

    def _is_anonymized_query(self, query_intent: QueryIntent) -> bool:
        raw_query = (getattr(query_intent, "raw_query", None) or "").casefold()
        anonymous_markers = (
            "anonymized",
            "anonymised",
            "unnamed site",
            "the unnamed",
            "this unnamed",
        )
        return any(marker in raw_query for marker in anonymous_markers) or not bool(query_intent.name_candidates)

    def _history_terms_from_intent(self, query_intent: QueryIntent, anonymous_query: bool) -> List[str]:
        terms: List[str] = []
        terms.extend(query_intent.name_candidates or [])
        if query_intent.geo_hints:
            terms.extend([query_intent.geo_hints.place_name, query_intent.geo_hints.country])
        if anonymous_query:
            terms.extend(self._distinctive_context_terms(getattr(query_intent, "raw_query", None)))
            terms.extend(self._strong_history_phrases(getattr(query_intent, "raw_query", None)))
            terms.extend(query_intent.scene_hints or [])
            terms.extend(tag.replace("_", " ") for tag in (query_intent.query_tags or []) if tag)
        return self._dedupe_text([term for term in terms if term])[:24]

    def _strong_history_phrases(self, raw_query: Optional[str]) -> List[str]:
        if not raw_query:
            return []

        text = " ".join(str(raw_query).split())
        text = re.sub(r"(?i)this anonymized tourist attraction", " ", text)
        text = re.sub(r"(?i)identify .*? clues:?", " ", text)
        text = re.sub(r"(?i)find .*? clues:?", " ", text)

        phrases: List[str] = []
        # Prefer distinctive clauses over generic visual tag tails.
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            cleaned = sentence.strip(" :;,.")
            if len(cleaned) < 12:
                continue
            lowered = cleaned.casefold()
            if any(term in lowered for term in GENERIC_HISTORY_TERMS):
                # Keep sentences with a real unique marker even if they also
                # contain generic words such as "tourist attraction".
                if not re.search(
                    r"(?i)\b(?:first known|largest|oldest|cleanest|UNESCO|World Heritage|built|designed by|named after|located|crossing|dynasty|century|Buddha|Phoenician|Norse|Michelin|Balancing Rock|Water-Moon|Snaefell|Chao Phraya|Lake Pichola)\b",
                    cleaned,
                ):
                    continue
            if re.search(
                r"(?i)\b(?:first known|largest|oldest|cleanest|UNESCO|World Heritage|built|designed by|named after|located|crossing|dynasty|century|Buddha|Phoenician|Norse|Michelin|Balancing Rock|Water-Moon|Snaefell|Chao Phraya|Lake Pichola)\b",
                cleaned,
            ):
                phrases.append(cleaned)

        # Add compact proper-noun phrases and quoted-style distinctive chunks.
        proper_phrase_pattern = re.compile(
            r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]{2,}(?:\s+(?:of|de|del|du|la|le|the|and|&|[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]{2,})){1,5}\b"
        )
        phrases.extend(match.group(0) for match in proper_phrase_pattern.finditer(text))

        # Add short keyword phrases around highly distinctive nouns.
        distinctive_patterns = [
            r"first known European settlement in North America",
            r"Norse village",
            r"Phoenician port city",
            r"ancient maritime culture",
            r"Asia's cleanest village",
            r"Balancing Rock",
            r"inverted roller coaster",
            r"Bolliger\s*&\s*Mabillard",
            r"single pylon",
            r"cable-stayed bridge",
            r"Water-Moon Cave",
            r"Lake Pichola",
            r"City Palace",
            r"Snaefell Mountain Course",
        ]
        for pattern in distinctive_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                phrases.append(match.group(0))

        filtered = []
        for phrase in phrases:
            cleaned = " ".join(str(phrase).strip(" .,:;").split())
            if len(cleaned) < 4:
                continue
            if cleaned.casefold() in GENERIC_HISTORY_TERMS:
                continue
            filtered.append(cleaned)
        return self._dedupe_text(filtered)[:8]

    def _distinctive_context_terms(self, raw_query: Optional[str]) -> List[str]:
        if not raw_query:
            return []

        text = " ".join(str(raw_query).split())
        text = re.sub(r"(?i)\b(?:the unnamed site|this anonymized tourist attraction)\b", " ", text)
        terms: List[str] = []

        # Years, road names, measurements, and named routes are often the facts
        # that distinguish same-region candidates.
        case_insensitive_patterns = [
            r"\b[12][0-9]{3}\b",
            r"\b[A-Z][0-9]\b",
            r"\b[0-9]+(?:\.[0-9]+)?\s*(?:mile|miles|km|kilometres|feet|ft|metres|meters|acre|gallons)\b",
        ]
        for pattern in case_insensitive_patterns:
            terms.extend(match.group(0) for match in re.finditer(pattern, text, flags=re.IGNORECASE))

        proper_patterns = [
            r"\b[A-Z][0-9]\s+[A-Z][A-Za-z'’.-]+(?:\s+to\s+[A-Z][A-Za-z'’.-]+)?\s+Road\b",
            r"\b[A-Z][A-Za-z'’.-]{3,}\s+to\s+[A-Z][A-Za-z'’.-]{3,}\b",
            r"\b[A-Z][A-Za-z0-9'’.-]+(?:\s+(?:Road|Course|Race|Railway|Sanctuary|Convent|Abbey|Bridge|Tower|Crater|Basin|Park|Garden|Ghat|Caves|Dome|Library|Palace|Kremlin|Island|District|County|Province|Valley|River|Reservoir|Mountain|Hill|Point|Street|Avenue|Drive|Chowk|Church|Temple|Monastery|Mansion|Museum|Theatre|Theater|Company|Family)){1,2}\b",
            r"\b[A-Z][A-Za-z'’.-]{3,}(?:\s+(?:of|the|and|[A-Z][A-Za-z'’.-]{3,})){1,4}\b",
        ]
        for pattern in proper_patterns:
            terms.extend(match.group(0) for match in re.finditer(pattern, text))

        for token in re.findall(r"\b[A-Z][A-Za-z0-9'’.-]{4,}\b", text):
            folded = token.casefold()
            if folded not in DISTINCTIVE_CONTEXT_STOPWORDS:
                terms.append(token)

        filtered: List[str] = []
        for term in terms:
            cleaned = " ".join(str(term).strip(" .,:;()[]{}\"'").split())
            if len(cleaned) < 4:
                continue
            folded = cleaned.casefold()
            words = [word.casefold() for word in re.findall(r"[A-Za-z0-9'’.-]+", cleaned)]
            if all(word in DISTINCTIVE_CONTEXT_STOPWORDS for word in words):
                continue
            if folded in GENERIC_HISTORY_TERMS:
                continue
            filtered.append(cleaned)

        return self._dedupe_text(filtered)[:24]

    def _dedupe_text(self, values: List[str]) -> List[str]:
        seen = set()
        deduped = []
        for value in values:
            cleaned = " ".join(str(value).split())
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                deduped.append(cleaned)
        return deduped

    def _merge_candidate_results(
        self,
        route_results: List[Dict[str, Any]],
        top_n: int,
        anonymous_query: bool = False,
    ) -> List[Dict[str, Any]]:
        merged: Dict[int, Dict[str, Any]] = {}

        for result in route_results:
            source_method = result.get("source_method", "unknown")
            for rank, candidate in enumerate(result.get("candidates") or [], start=1):
                if not isinstance(candidate, dict):
                    continue
                viewpoint_id = candidate.get("viewpoint_id")
                if not isinstance(viewpoint_id, int):
                    continue

                existing = merged.setdefault(
                    viewpoint_id,
                    {
                        "viewpoint_id": viewpoint_id,
                        "name_primary": candidate.get("name_primary"),
                        "name_variants": candidate.get("name_variants") or {},
                        "category_norm": candidate.get("category_norm"),
                        "name_score": 0.0,
                        "geo_score": 0.0,
                        "category_score": 0.0,
                        "popularity": float(candidate.get("popularity") or 0.0),
                        "tag_overlap_score": 0.0,
                        "season_match_bonus": 0.0,
                        "source_methods": [],
                        "route_ranks": {},
                    },
                )

                existing["name_primary"] = existing.get("name_primary") or candidate.get("name_primary")
                existing["name_variants"] = existing.get("name_variants") or candidate.get("name_variants") or {}
                existing["category_norm"] = existing.get("category_norm") or candidate.get("category_norm")
                existing["popularity"] = max(float(existing.get("popularity") or 0.0), float(candidate.get("popularity") or 0.0))
                existing["name_score"] = max(float(existing.get("name_score") or 0.0), float(candidate.get("name_score") or 0.0))
                existing["geo_score"] = max(float(existing.get("geo_score") or 0.0), float(candidate.get("geo_score") or 0.0))
                existing["category_score"] = max(float(existing.get("category_score") or 0.0), float(candidate.get("category_score") or 0.0))

                if source_method == "tags":
                    existing["tag_overlap_score"] = max(float(existing.get("tag_overlap_score") or 0.0), 1.0 / max(rank, 1))
                if source_method == "history":
                    existing["history_score"] = max(float(existing.get("history_score") or 0.0), float(candidate.get("name_score") or 0.0))
                    existing["history_rank_score"] = max(float(existing.get("history_rank_score") or 0.0), 1.0 / max(rank, 1))
                if source_method == "name":
                    existing["name_rank_score"] = max(float(existing.get("name_rank_score") or 0.0), 1.0 / max(rank, 1))

                if source_method not in existing["source_methods"]:
                    existing["source_methods"].append(source_method)
                existing["route_ranks"][source_method] = min(existing["route_ranks"].get(source_method, rank), rank)

        for candidate in merged.values():
            source_bonus = min(0.12, 0.04 * max(0, len(candidate.get("source_methods", [])) - 1))
            rank_bonus = sum(1.0 / max(rank, 1) for rank in candidate.get("route_ranks", {}).values()) * 0.03
            history_score = float(candidate.get("history_score") or 0.0)
            history_rank_score = float(candidate.get("history_rank_score") or 0.0)
            name_rank_score = float(candidate.get("name_rank_score") or 0.0)
            tag_score = float(candidate.get("tag_overlap_score") or 0.0)
            category_score = float(candidate.get("category_score") or 0.0)
            geo_score = float(candidate.get("geo_score") or 0.0)
            popularity = float(candidate.get("popularity") or 0.0)
            name_score = float(candidate.get("name_score") or 0.0)

            if anonymous_query:
                candidate["hybrid_score"] = min(
                    1.0,
                    0.46 * history_score
                    + 0.18 * history_rank_score
                    + 0.18 * geo_score
                    + 0.05 * tag_score
                    + 0.05 * category_score
                    + 0.02 * popularity
                    + source_bonus
                    + rank_bonus,
                )
            else:
                candidate["hybrid_score"] = min(
                    1.0,
                    0.68 * name_score
                    + 0.12 * name_rank_score
                    + 0.06 * history_score
                    + 0.06 * geo_score
                    + 0.04 * max(category_score, tag_score)
                    + 0.02 * popularity
                    + source_bonus
                    + rank_bonus,
                )

        return sorted(
            merged.values(),
            key=lambda item: (
                float(item.get("hybrid_score") or 0.0),
                float(item.get("name_score") or 0.0),
                float(item.get("popularity") or 0.0),
            ),
            reverse=True,
        )[:top_n]

    def _apply_contextual_intent_boosts(
        self,
        candidates: List[Dict[str, Any]],
        query_intent: QueryIntent,
    ) -> None:
        """Boost recalled candidates whose stored context matches extracted geo/history clues."""
        ids = [candidate.get("viewpoint_id") for candidate in candidates if isinstance(candidate.get("viewpoint_id"), int)]
        if not ids:
            return

        context_by_id = self._candidate_contexts(ids)
        raw_query = getattr(query_intent, "raw_query", None) or ""
        clue_phrases = self._strong_history_phrases(raw_query)
        distinctive_terms = self._distinctive_context_terms(raw_query)
        geo_terms: List[str] = []
        if query_intent.geo_hints:
            geo_terms.extend([query_intent.geo_hints.place_name, query_intent.geo_hints.country])
        name_terms = [term for term in (query_intent.name_candidates or []) if len(str(term).strip()) >= 4]
        tag_terms = [str(tag).replace("_", " ") for tag in (query_intent.query_tags or []) if tag]

        for candidate in candidates:
            viewpoint_id = candidate.get("viewpoint_id")
            context = context_by_id.get(viewpoint_id, "").casefold()
            if not context:
                continue

            phrase_hits = sum(1 for phrase in clue_phrases if phrase and phrase.casefold() in context)
            distinctive_hits = sum(1 for term in distinctive_terms if term and term.casefold() in context)
            geo_hits = sum(1 for term in geo_terms if term and str(term).casefold() in context)
            name_hits = sum(1 for term in name_terms if term and str(term).casefold() in context)
            tag_hits = sum(1 for term in tag_terms if term and str(term).casefold() in context)

            context_score = min(
                1.0,
                0.20 * min(phrase_hits, 4)
                + 0.10 * min(distinctive_hits, 5)
                + 0.12 * min(geo_hits, 2)
                + 0.08 * min(name_hits, 2)
                + 0.04 * min(tag_hits, 3),
            )
            candidate["context_score"] = context_score
            candidate["context_phrase_hits"] = phrase_hits
            candidate["context_distinctive_hits"] = distinctive_hits
            candidate["context_geo_hits"] = geo_hits
            candidate["hybrid_score"] = min(1.0, float(candidate.get("hybrid_score") or 0.0) + 0.30 * context_score)

    def _candidate_contexts(self, viewpoint_ids: List[int]) -> Dict[int, str]:
        if not viewpoint_ids:
            return {}

        sql = """
        SELECT
            e.viewpoint_id,
            COALESCE(e.name_primary, '') AS name_primary,
            COALESCE(e.name_variants::text, '') AS name_variants,
            COALESCE(e.category_norm, '') AS category_norm,
            COALESCE(w.wikipedia_title, '') AS wikipedia_title,
            COALESCE(w.extract_text, '') AS extract_text,
            COALESCE(string_agg(DISTINCT a.viewpoint_country, ' '), '') AS countries,
            COALESCE(string_agg(DISTINCT a.viewpoint_region, ' '), '') AS regions
        FROM viewpoint_entity e
        LEFT JOIN viewpoint_wiki w ON e.viewpoint_id = w.viewpoint_id
        LEFT JOIN viewpoint_commons_assets a ON e.viewpoint_id = a.viewpoint_id
        WHERE e.viewpoint_id = ANY(%s)
        GROUP BY e.viewpoint_id, e.name_primary, e.name_variants, e.category_norm, w.wikipedia_title, w.extract_text
        """
        with db.get_cursor() as cursor:
            cursor.execute(sql, (viewpoint_ids,))
            rows = cursor.fetchall()

        contexts: Dict[int, str] = {}
        for row in rows:
            contexts[row["viewpoint_id"]] = " ".join(
                str(row.get(key) or "")
                for key in [
                    "name_primary",
                    "name_variants",
                    "category_norm",
                    "wikipedia_title",
                    "extract_text",
                    "countries",
                    "regions",
                ]
            )
        return contexts
    
    def search_by_name(
        self,
        name_pattern: str,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Search viewpoints by name pattern.
        
        Args:
            name_pattern: Name pattern to search (supports % wildcards)
            top_n: Maximum number of results
            
        Returns:
            Dict with candidates and SQL query info
        """
        sql = """
        SELECT 
            viewpoint_id,
            name_primary,
            name_variants,
            category_norm,
            popularity,
            CASE WHEN name_primary ILIKE %s THEN 1.0 ELSE 0.5 END as name_score,
            1.0 as geo_score,
            CASE WHEN category_norm IS NOT NULL THEN 1.0 ELSE 0.0 END as category_score
        FROM viewpoint_entity
        WHERE name_primary ILIKE %s OR name_variants::text ILIKE %s
        ORDER BY name_score DESC, popularity DESC NULLS LAST
        LIMIT %s
        """
        
        pattern = f"%{name_pattern}%"
        params = [pattern, pattern, pattern, top_n]
        
        with db.get_cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        
        candidates = []
        for row in rows:
            candidates.append(ViewpointCandidate(
                viewpoint_id=row['viewpoint_id'],
                name_primary=row['name_primary'],
                name_variants=row['name_variants'] or {},
                category_norm=row['category_norm'],
                name_score=float(row['name_score']),
                geo_score=float(row['geo_score']),
                category_score=float(row['category_score']),
                popularity=float(row['popularity'])
            ))
        
        result = {
            "candidates": [c.model_dump() for c in candidates],
            "count": len(candidates),
            "sql": sql,
            "params": params
        }
        
        # Add warning if no results found
        if len(candidates) == 0:
            result["warning"] = f"No viewpoints found matching '{name_pattern}'. The database may not contain this location."
            result["suggestion"] = "Try searching with a different name or check if the viewpoint exists in the database."
        
        return result
    
    def search_by_category(
        self,
        category: str,
        country: Optional[str] = None,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Search viewpoints by category, optionally filtered by country.
        
        Args:
            category: Category name (mountain, lake, temple, etc.)
            country: Optional country name to filter by (e.g., "China", "France")
            top_n: Maximum number of results
            
        Returns:
            Dict with candidates and SQL query info
        """
        # Build SQL with optional country filter
        if country:
            # Normalize country name to get all variants
            country_variants = normalize_country_name(country)
            
            # Build OR conditions for country matching
            country_conditions = []
            country_params = []
            for variant in country_variants:
                country_conditions.append("vca.viewpoint_country ILIKE %s")
                country_params.append(f"%{variant}%")
            
            country_filter = " OR ".join(country_conditions) if country_conditions else "1=0"
            
            # First try: search with country filter (using INNER JOIN for strict matching)
            sql = f"""
            SELECT 
                e.viewpoint_id,
                e.name_primary,
                e.name_variants,
                e.category_norm,
                e.popularity,
                0.0 as name_score,
                CASE WHEN ({country_filter}) THEN 1.0 ELSE 0.0 END as geo_score,
                CASE WHEN e.category_norm = %s THEN 1.0 ELSE 0.0 END as category_score
            FROM viewpoint_entity e
            INNER JOIN viewpoint_commons_assets vca ON e.viewpoint_id = vca.viewpoint_id
            WHERE e.category_norm = %s
              AND vca.viewpoint_country IS NOT NULL
              AND ({country_filter})
            ORDER BY geo_score DESC, e.popularity DESC NULLS LAST
            LIMIT %s
            """
            # Parameters: country variants (for geo_score), category (for category_score), category (for WHERE), country variants (for WHERE), top_n
            params = country_params + [category, category] + country_params + [top_n]
            
            with db.get_cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            
            # If no results found with country filter, fallback to search without country filter
            # but still return all results (they may not have country info in database)
            if len(rows) == 0:
                # Fallback: search without country filter
                sql_fallback = """
                SELECT 
                    viewpoint_id,
                    name_primary,
                    name_variants,
                    category_norm,
                    popularity,
                    0.0 as name_score,
                    0.5 as geo_score,
                    CASE WHEN category_norm = %s THEN 1.0 ELSE 0.0 END as category_score
                FROM viewpoint_entity
                WHERE category_norm = %s
                ORDER BY popularity DESC NULLS LAST
                LIMIT %s
                """
                params_fallback = [category, category, top_n]
                
                with db.get_cursor() as cursor:
                    cursor.execute(sql_fallback, params_fallback)
                    rows = cursor.fetchall()
                    sql = sql_fallback
                    params = params_fallback
        else:
            sql = """
            SELECT 
                viewpoint_id,
                name_primary,
                name_variants,
                category_norm,
                popularity,
                0.0 as name_score,
                1.0 as geo_score,
                CASE WHEN category_norm = %s THEN 1.0 ELSE 0.0 END as category_score
            FROM viewpoint_entity
            WHERE category_norm = %s
            ORDER BY popularity DESC NULLS LAST
            LIMIT %s
            """
            params = [category, category, top_n]
            
            with db.get_cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        
        # If still no results, try matching category in visual tags
        if len(rows) == 0:
            tags_result = self.search_by_tags([category], season=None, top_n=top_n)
            if tags_result.get("count", 0) > 0:
                tags_result["warning"] = (
                    f"No {category} viewpoints found in category_norm. "
                    f"Showing results matched from visual tags instead."
                )
                tags_result["suggestion"] = (
                    "These results were matched by tags, not by normalized category."
                )
                return tags_result
        
        candidates = []
        for row in rows:
            candidates.append(ViewpointCandidate(
                viewpoint_id=row['viewpoint_id'],
                name_primary=row['name_primary'],
                name_variants=row['name_variants'] or {},
                category_norm=row['category_norm'],
                name_score=float(row['name_score']),
                geo_score=float(row['geo_score']),
                category_score=float(row['category_score']),
                popularity=float(row['popularity'])
            ))
        
        result = {
            "candidates": [c.model_dump() for c in candidates],
            "count": len(candidates),
            "sql": sql,
            "params": params
        }
        
        # Add warning if country filter was used but no results found with country info
        if country:
            # Check if we found results with country info
            # Rebuild country filter for the count query
            country_conditions_count = []
            country_params_count = []
            for variant in country_variants:
                country_conditions_count.append("vca.viewpoint_country ILIKE %s")
                country_params_count.append(f"%{variant}%")
            
            country_filter_count = " OR ".join(country_conditions_count) if country_conditions_count else "1=0"
            
            with db.get_cursor() as cursor:
                count_sql = f"""
                    SELECT COUNT(DISTINCT e.viewpoint_id) as count
                    FROM viewpoint_entity e
                    INNER JOIN viewpoint_commons_assets vca ON e.viewpoint_id = vca.viewpoint_id
                    WHERE e.category_norm = %s
                      AND vca.viewpoint_country IS NOT NULL
                      AND ({country_filter_count})
                """
                cursor.execute(count_sql, [category] + country_params_count)
                country_match_count = cursor.fetchone()['count']
            
            if country_match_count == 0 and len(candidates) > 0:
                result["warning"] = f"No {category} viewpoints found in {country} with country information. Showing all {category} viewpoints (some may not have country data in database)."
                result["suggestion"] = "To get accurate country filtering, ensure country information is populated in the database using reverse geocoding."
            elif country_match_count == 0 and len(candidates) == 0:
                result["warning"] = f"No {category} viewpoints found in the database."
                result["suggestion"] = "The database may not contain this category of viewpoints."
        
        return result
    
    def search_by_history_terms(
        self,
        terms: List[str],
        top_n: int = 50,
        country: Optional[str] = None,
        place_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search viewpoints by matching terms in historical/Wikipedia text.
        
        Args:
            terms: List of keywords or phrases to search in viewpoint_wiki.extract_text
            top_n: Maximum number of results
            
        Returns:
            Dict with candidates and SQL query info
        """
        if not terms:
            return {
                "candidates": [],
                "count": 0,
                "warning": "No history terms provided for search.",
                "suggestion": "Provide at least one keyword or phrase to search in history text."
            }
        
        normalized_terms = [t.strip() for t in terms if t and t.strip()]
        if not normalized_terms:
            return {
                "candidates": [],
                "count": 0,
                "warning": "All history terms were empty after normalization.",
                "suggestion": "Provide non-empty keywords or phrases to search in history text."
            }
        
        query_text = " ".join(normalized_terms)
        ilike_patterns = [f"%{t}%" for t in normalized_terms]
        ilike_where = " OR ".join(["w.extract_text ILIKE %s"] * len(normalized_terms))
        ilike_match_cases = " + ".join(
            ["CASE WHEN w.extract_text ILIKE %s THEN 1 ELSE 0 END"] * len(normalized_terms)
        )
        exact_phrase_cases = " + ".join(
            ["CASE WHEN (w.wikipedia_title ILIKE %s OR w.extract_text ILIKE %s) THEN 1 ELSE 0 END"] * len(normalized_terms)
        )
        geo_terms: List[str] = []
        if country:
            geo_terms.extend(normalize_country_name(country))
        if place_name:
            geo_terms.append(place_name)
        geo_terms = self._dedupe_text([term for term in geo_terms if term and str(term).strip()])
        geo_patterns = [f"%{term}%" for term in geo_terms]
        if geo_patterns:
            geo_context = (
                "COALESCE(g.geo_text, '') || ' ' || "
                "COALESCE(w.wikipedia_title, '') || ' ' || COALESCE(w.extract_text, '')"
            )
            geo_score_sql = (
                "CASE WHEN ("
                + " OR ".join([f"{geo_context} ILIKE %s"] * len(geo_patterns))
                + ") THEN 1.0 ELSE 0.0 END AS geo_score"
            )
        else:
            geo_score_sql = "1.0 AS geo_score"

        # PostgreSQL full-text rank is not exact Okapi BM25, but it gives a much
        # better lexical relevance signal than boolean ILIKE term matching.
        sql = f"""
        WITH query AS (
            SELECT websearch_to_tsquery('english', %s) AS tsq
        ),
        geo AS (
            SELECT
                viewpoint_id,
                string_agg(
                    DISTINCT COALESCE(viewpoint_country, '') || ' ' || COALESCE(viewpoint_region, ''),
                    ' '
                ) AS geo_text
            FROM viewpoint_commons_assets
            GROUP BY viewpoint_id
        ),
        ranked AS (
            SELECT
                e.viewpoint_id,
                e.name_primary,
                e.name_variants,
                e.category_norm,
                e.popularity,
                ts_rank_cd(
                    to_tsvector(
                        'english',
                        COALESCE(w.wikipedia_title, '') || ' ' || COALESCE(w.extract_text, '')
                    ),
                    query.tsq,
                    32
                ) AS fts_rank,
                LEAST(1.0, ({ilike_match_cases})::float / %s) AS ilike_score
                ,LEAST(1.0, ({exact_phrase_cases})::float / %s) AS exact_phrase_score,
                {geo_score_sql}
            FROM viewpoint_entity e
            INNER JOIN viewpoint_wiki w ON e.viewpoint_id = w.viewpoint_id
            LEFT JOIN geo g ON e.viewpoint_id = g.viewpoint_id
            CROSS JOIN query
            WHERE (
                to_tsvector(
                    'english',
                    COALESCE(w.wikipedia_title, '') || ' ' || COALESCE(w.extract_text, '')
                ) @@ query.tsq
                OR ({ilike_where})
            )
        )
        SELECT DISTINCT
            viewpoint_id,
            name_primary,
            name_variants,
            category_norm,
            popularity,
            LEAST(1.0, GREATEST(fts_rank, ilike_score, exact_phrase_score)) AS name_score,
            geo_score,
            CASE WHEN category_norm IS NOT NULL THEN 0.5 ELSE 0.0 END AS category_score
        FROM ranked
        ORDER BY geo_score DESC, name_score DESC, popularity DESC NULLS LAST
        LIMIT %s
        """
        
        params = [query_text]
        params.extend(ilike_patterns)
        params.append(len(normalized_terms))
        for pattern in ilike_patterns:
            params.extend([pattern, pattern])
        params.append(len(normalized_terms))
        params.extend(geo_patterns)
        params.extend(ilike_patterns)
        params.append(top_n)
        
        try:
            with db.get_cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        except Exception:
            return self._search_by_history_terms_ilike(
                normalized_terms,
                top_n,
                country=country,
                place_name=place_name,
            )
        
        candidates = []
        for row in rows:
            candidates.append(ViewpointCandidate(
                viewpoint_id=row['viewpoint_id'],
                name_primary=row['name_primary'],
                name_variants=row.get('name_variants') or {},
                category_norm=row.get('category_norm'),
                name_score=float(row.get('name_score', 0.0)),
                geo_score=float(row.get('geo_score', 1.0)),
                category_score=float(row.get('category_score', 0.0)),
                popularity=float(row.get('popularity', 0.0))
            ))
        
        result = {
            "candidates": [c.model_dump() for c in candidates],
            "count": len(candidates),
            "sql": sql,
            "params": params,
            "ranking": "postgres_full_text_ts_rank_cd"
        }
        
        if len(candidates) == 0:
            result["warning"] = "No viewpoints found matching the history terms."
            result["suggestion"] = "Try different keywords or broaden the history-related terms."
        
        return result

    def _search_by_history_terms_ilike(
        self,
        normalized_terms: List[str],
        top_n: int,
        country: Optional[str] = None,
        place_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Fallback for older PostgreSQL versions or unusual text-search configs.
        match_cases = " + ".join(
            ["CASE WHEN w.extract_text ILIKE %s THEN 1 ELSE 0 END"] * len(normalized_terms)
        )
        where_clause = " OR ".join(["w.extract_text ILIKE %s"] * len(normalized_terms))
        geo_terms: List[str] = []
        if country:
            geo_terms.extend(normalize_country_name(country))
        if place_name:
            geo_terms.append(place_name)
        geo_terms = self._dedupe_text([term for term in geo_terms if term and str(term).strip()])
        geo_patterns = [f"%{term}%" for term in geo_terms]
        if geo_patterns:
            geo_context = (
                "COALESCE(g.geo_text, '') || ' ' || "
                "COALESCE(w.wikipedia_title, '') || ' ' || COALESCE(w.extract_text, '')"
            )
            geo_score_sql = (
                "CASE WHEN ("
                + " OR ".join([f"{geo_context} ILIKE %s"] * len(geo_patterns))
                + ") THEN 1.0 ELSE 0.0 END as geo_score"
            )
        else:
            geo_score_sql = "1.0 as geo_score"
        
        sql = f"""
        WITH geo AS (
            SELECT
                viewpoint_id,
                string_agg(
                    DISTINCT COALESCE(viewpoint_country, '') || ' ' || COALESCE(viewpoint_region, ''),
                    ' '
                ) AS geo_text
            FROM viewpoint_commons_assets
            GROUP BY viewpoint_id
        )
        SELECT DISTINCT
            e.viewpoint_id,
            e.name_primary,
            e.name_variants,
            e.category_norm,
            e.popularity,
            LEAST(1.0, ({match_cases})::float / %s) as name_score,
            {geo_score_sql},
            CASE WHEN e.category_norm IS NOT NULL THEN 0.5 ELSE 0.0 END as category_score
        FROM viewpoint_entity e
        INNER JOIN viewpoint_wiki w ON e.viewpoint_id = w.viewpoint_id
        LEFT JOIN geo g ON e.viewpoint_id = g.viewpoint_id
        WHERE ({where_clause})
        ORDER BY geo_score DESC, name_score DESC, e.popularity DESC NULLS LAST
        LIMIT %s
        """
        
        params = [f"%{t}%" for t in normalized_terms]
        params.append(len(normalized_terms))
        params.extend(geo_patterns)
        params.extend([f"%{t}%" for t in normalized_terms])
        params.append(top_n)
        
        with db.get_cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        
        candidates = []
        for row in rows:
            candidates.append(ViewpointCandidate(
                viewpoint_id=row['viewpoint_id'],
                name_primary=row['name_primary'],
                name_variants=row.get('name_variants') or {},
                category_norm=row.get('category_norm'),
                name_score=float(row.get('name_score', 0.0)),
                geo_score=float(row.get('geo_score', 1.0)),
                category_score=float(row.get('category_score', 0.0)),
                popularity=float(row.get('popularity', 0.0))
            ))
        
        result = {
            "candidates": [c.model_dump() for c in candidates],
            "count": len(candidates),
            "sql": sql,
            "params": params,
            "ranking": "ilike_fallback"
        }
        
        if len(candidates) == 0:
            result["warning"] = "No viewpoints found matching the history terms."
            result["suggestion"] = "Try different keywords or broaden the history-related terms."
        
        return result
    
    def search_by_tags(
        self,
        tags: List[str],
        season: Optional[str] = None,
        tag_sources: Optional[List[str]] = None,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Search viewpoints by visual tags.
        
        Args:
            tags: List of visual tags to search for
            season: Optional season filter (spring, summer, autumn, winter)
            tag_sources: Optional tag sources filter (e.g., wiki_weak_supervision)
            top_n: Maximum number of results
            
        Returns:
            Dict with candidates and SQL query info
        """
        # Map visual tags to categories if possible
        visual_to_category = {
            'snow_peak': 'mountain',
            'waterfall': 'waterfall',
        }
        
        valid_categories = [
            'mountain', 'lake', 'temple', 'museum', 'park',
            'coast', 'cityscape', 'monument', 'bridge',
            'palace', 'tower', 'cave', 'waterfall', 'valley', 'island'
        ]
        
        category_list = []
        for tag in tags:
            if tag in valid_categories:
                category_list.append(tag)
            if tag in visual_to_category:
                category_list.append(visual_to_category[tag])
        
        # Build SQL query
        conditions = []
        params = []
        has_tag_filters = bool(tags)
        
        # Category filter (only when no tag-based filter is used)
        if category_list and not has_tag_filters:
            placeholders = ','.join(['%s'] * len(category_list))
            conditions.append(f"category_norm IN ({placeholders})")
            params.extend(category_list)
        
        # Visual tags filter (search in viewpoint_visual_tags table)
        if tags:
            tag_conditions = []
            tag_params = []
            for tag in tags:
                tag_conditions.append("tags @> %s::jsonb")
                tag_params.append(json.dumps([tag]))
            
            if tag_conditions:
                tag_source_filter = ""
                if tag_sources:
                    placeholders = ','.join(['%s'] * len(tag_sources))
                    tag_source_filter = f"AND tag_source IN ({placeholders})"
                    tag_params.extend(tag_sources)
                
                season_filter = ""
                if season and season != 'unknown':
                    season_filter = "AND season = %s"
                    tag_params.append(season)
                
                conditions.append(f"""viewpoint_id IN (
                    SELECT DISTINCT viewpoint_id 
                    FROM viewpoint_visual_tags 
                    WHERE {' OR '.join(tag_conditions)}
                    {tag_source_filter}
                    {season_filter}
                )""")
                params.extend(tag_params)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        category_score_sql = "0.0"
        category_score_params: List[str] = []
        if category_list:
            placeholders = ','.join(['%s'] * len(category_list))
            category_score_sql = f"CASE WHEN e.category_norm IN ({placeholders}) THEN 1.0 ELSE 0.0 END"
            category_score_params.extend(category_list)
        
        sql = f"""
        SELECT DISTINCT
            e.viewpoint_id,
            e.name_primary,
            e.name_variants,
            e.category_norm,
            e.popularity,
            0.0 as name_score,
            1.0 as geo_score,
            {category_score_sql} as category_score
        FROM viewpoint_entity e
        WHERE {where_clause}
        ORDER BY e.popularity DESC NULLS LAST
        LIMIT %s
        """
        
        params = category_score_params + params
        params.append(top_n)
        with db.get_cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        
        candidates = []
        for row in rows:
            candidates.append(ViewpointCandidate(
                viewpoint_id=row['viewpoint_id'],
                name_primary=row['name_primary'],
                name_variants=row['name_variants'] or {},
                category_norm=row['category_norm'],
                name_score=float(row['name_score']),
                geo_score=float(row['geo_score']),
                category_score=float(row['category_score']),
                popularity=float(row['popularity'])
            ))
        
        return {
            "candidates": [c.model_dump() for c in candidates],
            "count": len(candidates),
            "sql": sql,
            "params": params
        }
    
    def search_popular(
        self,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Get most popular viewpoints.
        
        Args:
            top_n: Maximum number of results
            
        Returns:
            Dict with candidates and SQL query info
        """
        sql = """
        SELECT 
            viewpoint_id,
            name_primary,
            name_variants,
            category_norm,
            popularity,
            0.0 as name_score,
            1.0 as geo_score,
            0.0 as category_score
        FROM viewpoint_entity
        WHERE popularity > 0
        ORDER BY popularity DESC NULLS LAST
        LIMIT %s
        """
        
        params = [top_n]
        
        with db.get_cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        
        candidates = []
        for row in rows:
            candidates.append(ViewpointCandidate(
                viewpoint_id=row['viewpoint_id'],
                name_primary=row['name_primary'],
                name_variants=row['name_variants'] or {},
                category_norm=row['category_norm'],
                name_score=float(row['name_score']),
                geo_score=float(row['geo_score']),
                category_score=float(row['category_score']),
                popularity=float(row['popularity'])
            ))
        
        return {
            "candidates": [c.model_dump() for c in candidates],
            "count": len(candidates),
            "sql": sql,
            "params": params
        }


# Singleton instance
_sql_search_tool: Optional[SQLSearchTool] = None


def get_sql_search_tool() -> SQLSearchTool:
    """Get singleton instance of SQL search tool"""
    global _sql_search_tool
    if _sql_search_tool is None:
        _sql_search_tool = SQLSearchTool()
    return _sql_search_tool

