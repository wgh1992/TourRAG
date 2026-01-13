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
    - Name search: Use ILIKE on name_primary or name_variants
    - Category search: Filter by category_norm
    - Historical information search: Join viewpoint_wiki and search extract_text using ILIKE
    - Visual tags search: Join viewpoint_visual_tags and use JSONB @> operator to check if tags array contains specific tags
    - Season search: Filter viewpoint_visual_tags by season column
    - Combined search: Can combine name, category, history, tags, and season filters
    
    Common Query Patterns:
    - Use ST_X(geom) and ST_Y(geom) to get longitude and latitude
    - Use ST_Within(geom, ST_MakeEnvelope(...)) for bounding box queries
    - Use ILIKE for case-insensitive text matching (for names, Wikipedia text)
    - Use JSONB operators for tags:
      * @> operator: tags @> '["snow_peak"]'::jsonb (check if array contains value)
      * -> operator: sections->'history' (access JSONB object field)
      * ->> operator: sections->>'history' (get JSONB field as text)
    - For historical text search: JOIN viewpoint_wiki and use extract_text ILIKE %s
    - For visual tags search: JOIN viewpoint_visual_tags and use tags @> %s::jsonb
    - For season filter: WHERE vt.season = %s in viewpoint_visual_tags join
    - Always use parameterized queries with %s placeholders
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
5. Use ILIKE for case-insensitive text matching (for names, Wikipedia text)
6. For country filtering, join with viewpoint_commons_assets table
7. For visual tags search:
   - JOIN viewpoint_visual_tags table
   - Use tags @> %s::jsonb to check if tags array contains specific tags
   - Example: tags @> '["snow_peak"]'::jsonb
8. For season filtering:
   - JOIN viewpoint_visual_tags table
   - Use WHERE vt.season = %s
9. For historical information search:
   - JOIN viewpoint_wiki table
   - Use extract_text ILIKE %s to search in Wikipedia text
   - Example: w.extract_text ILIKE %s
10. Always include LIMIT clause
11. Order by relevance scores and popularity
12. Use DISTINCT if joining multiple tables to avoid duplicate rows

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

        # Build parameter list for LLM to understand what to use
        param_info = []
        if query_intent.name_candidates:
            param_info.append(f"Name patterns: {len(query_intent.name_candidates)} patterns (use %s for each)")
        if query_intent.query_tags:
            valid_categories = ['mountain', 'lake', 'temple', 'museum', 'park', 
                               'coast', 'cityscape', 'monument', 'bridge', 
                               'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']
            categories = [tag for tag in query_intent.query_tags if tag in valid_categories]
            if categories:
                param_info.append(f"Categories: {len(categories)} values (use %s for each)")
        if query_intent.geo_hints and query_intent.geo_hints.country:
            country_variants = normalize_country_name(query_intent.geo_hints.country)
            param_info.append(f"Country patterns: {len(country_variants)} patterns (use %s for each)")
        if query_intent.season_hint and query_intent.season_hint != 'unknown':
            param_info.append(f"Season: 1 value (use %s)")
        param_info.append(f"LIMIT: 1 value (use %s for {top_n})")
        
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
        
        user_prompt = f"""Generate a SQL query for {search_type} search with the following requirements:

{chr(10).join(search_requirements) if search_requirements else '- General search (no specific filters)'}

- Limit: {top_n}

IMPORTANT INSTRUCTIONS:
1. If visual tags are specified, JOIN viewpoint_visual_tags and use tags @> %s::jsonb to search
2. If season is specified, JOIN viewpoint_visual_tags and filter by season = %s
3. If searching for historical information or scene descriptions, JOIN viewpoint_wiki and search extract_text ILIKE %s
4. Use DISTINCT to avoid duplicate rows when joining multiple tables
5. The number of %s placeholders must match the total number of parameters
6. Return ONLY the SQL query with the correct number of %s placeholders."""

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
            
            # Extract parameters from query intent (in the order they should appear in SQL)
            params = []
            
            # Add name patterns (for ILIKE queries) - typically appear first in WHERE clauses
            if query_intent.name_candidates:
                for name in query_intent.name_candidates:
                    params.append(f"%{name}%")
            
            # Add category filters - typically in WHERE or IN clauses
            if query_intent.query_tags:
                valid_categories = ['mountain', 'lake', 'temple', 'museum', 'park', 
                                   'coast', 'cityscape', 'monument', 'bridge', 
                                   'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']
                categories = [tag for tag in query_intent.query_tags if tag in valid_categories]
                params.extend(categories)
            
            # Add visual tags (for JSONB @> operator) - need to be JSONB arrays
            if query_intent.query_tags:
                visual_tags = [tag for tag in query_intent.query_tags 
                              if tag not in ['mountain', 'lake', 'temple', 'museum', 'park', 
                                            'coast', 'cityscape', 'monument', 'bridge', 
                                            'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']]
                # Visual tags will be converted to JSONB format in SQL, but we pass them as strings
                # The LLM should generate: tags @> %s::jsonb where %s is a JSON array string
                for tag in visual_tags:
                    # Pass as JSON array string for @> operator
                    params.append(json.dumps([tag]))
            
            # Add scene hints (for Wikipedia text search) - search in extract_text
            if query_intent.scene_hints:
                for scene in query_intent.scene_hints:
                    params.append(f"%{scene}%")
            
            # Add country variants - typically in JOIN conditions
            if query_intent.geo_hints and query_intent.geo_hints.country:
                country_variants = normalize_country_name(query_intent.geo_hints.country)
                params.extend([f"%{v}%" for v in country_variants])
            
            # Add season - typically in WHERE clauses for visual_tags
            if query_intent.season_hint and query_intent.season_hint != 'unknown':
                params.append(query_intent.season_hint)
            
            # Add top_n (should be last, in LIMIT clause)
            params.append(top_n)
            
            # Count parameter placeholders in SQL
            param_count = sql.count('%s')
            
            # If parameter count doesn't match, log warning and adjust
            # The LLM should generate correct SQL, but we handle mismatches gracefully
            if len(params) != param_count:
                print(f"[SQLSearchTool] Warning: Parameter count mismatch. SQL has {param_count} placeholders, but we have {len(params)} parameters.")
                print(f"[SQLSearchTool] SQL preview: {sql[:300]}...")
                print(f"[SQLSearchTool] Expected params: {params}")
                
                # Try to pad or trim params to match (this is a workaround)
                # In production, we'd want better error handling
                if len(params) < param_count:
                    # Pad with None - this will likely cause the query to fail, but fallback will handle it
                    # We don't try to guess missing params as it's error-prone
                    missing_count = param_count - len(params)
                    print(f"[SQLSearchTool] Padding {missing_count} missing parameters with None")
                    params.extend([None] * missing_count)
                elif len(params) > param_count:
                    # Trim params (keep first param_count, but preserve top_n at the end if possible)
                    # Make sure top_n is included
                    if len(params) > 0 and params[-1] == top_n and param_count > 0:
                        # Keep top_n and trim from middle
                        params = params[:param_count-1] + [top_n]
                    else:
                        params = params[:param_count]
            
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
        
        # Execute query
        with db.get_cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()
    
    def search_with_llm_sql(
        self,
        query_intent: QueryIntent,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Search viewpoints using LLM-generated SQL query.
        
        Args:
            query_intent: Query intent from extract_query_intent
            top_n: Maximum number of results
            
        Returns:
            Dict with candidates and SQL query info
        """
        try:
            # Determine search type based on query intent
            has_name = bool(query_intent.name_candidates)
            has_category = any(tag in ['mountain', 'lake', 'temple', 'museum', 'park', 
                                      'coast', 'cityscape', 'monument', 'bridge', 
                                      'palace', 'tower', 'cave', 'waterfall', 'valley', 'island'] 
                              for tag in query_intent.query_tags)
            has_tags = bool(query_intent.query_tags)
            
            if has_name and has_category:
                search_type = "combined"
            elif has_name:
                search_type = "name"
            elif has_category:
                search_type = "category"
            elif has_tags:
                search_type = "tags"
            else:
                search_type = "general"
            
            # Generate SQL with LLM
            sql, params = self._generate_sql_with_llm(
                query_intent=query_intent,
                search_type=search_type,
                top_n=top_n
            )
            
            # Execute query
            rows = self._validate_and_execute_sql(sql, params)
            
            # Convert to candidates
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
            
            # If no results from LLM SQL, try fallback with more relaxed criteria
            if len(candidates) == 0:
                print(f"[SQLSearchTool] LLM SQL returned 0 results, trying fallback search...")
                fallback_result = self._fallback_search(query_intent, top_n)
                
                # If fallback found results, use them but note that LLM SQL didn't work
                if fallback_result.get('count', 0) > 0:
                    # Preserve original warning/suggestion if any
                    original_warning = fallback_result.get('warning', '')
                    original_suggestion = fallback_result.get('suggestion', '')
                    
                    fallback_result["warning"] = (
                        f"LLM-generated SQL query returned no results. "
                        f"Using fallback search method with relaxed criteria. "
                        f"{original_warning}"
                    ).strip()
                    if original_suggestion:
                        fallback_result["suggestion"] = original_suggestion
                    else:
                        fallback_result["suggestion"] = "The search used relaxed criteria to find results. Some criteria (like category or country filters) may not have matched exactly."
                    
                    fallback_result["llm_sql_failed"] = True
                    fallback_result["llm_sql"] = sql
                    fallback_result["llm_params"] = params
                    return fallback_result
                else:
                    # Even fallback found nothing
                    result = {
                        "candidates": [],
                        "count": 0,
                        "sql": sql,
                        "params": params,
                        "generated_by": "llm",
                        "warning": "No viewpoints found matching the query. The database may not contain viewpoints matching all the specified criteria.",
                        "suggestion": "Try searching with fewer or different criteria, or check if the database contains relevant viewpoints."
                    }
                    return result
            
            result = {
                "candidates": [c.model_dump() for c in candidates],
                "count": len(candidates),
                "sql": sql,
                "params": params,
                "generated_by": "llm"
            }
            
            return result
            
        except Exception as e:
            print(f"[SQLSearchTool] Error in LLM SQL search: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to traditional search methods
            return self._fallback_search(query_intent, top_n)
    
    def _fallback_search(
        self,
        query_intent: QueryIntent,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Fallback to traditional search methods when LLM SQL generation fails.
        Uses more relaxed criteria to find results.
        """
        # Priority 1: Try name search first (most likely to find results)
        if query_intent.name_candidates:
            print(f"[SQLSearchTool] Fallback: Trying name search for '{query_intent.name_candidates[0]}'")
            name_result = self.search_by_name(query_intent.name_candidates[0], top_n=top_n)
            if name_result.get('count', 0) > 0:
                return name_result
        
        # Priority 2: Try category search (without strict country filter if it fails)
        if query_intent.query_tags:
            valid_categories = ['mountain', 'lake', 'temple', 'museum', 'park', 
                               'coast', 'cityscape', 'monument', 'bridge', 
                               'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']
            categories = [tag for tag in query_intent.query_tags if tag in valid_categories]
            if categories:
                # First try with country filter
                country = query_intent.geo_hints.country if query_intent.geo_hints else None
                if country:
                    print(f"[SQLSearchTool] Fallback: Trying category search for '{categories[0]}' in '{country}'")
                    category_result = self.search_by_category(categories[0], country=country, top_n=top_n)
                    if category_result.get('count', 0) > 0:
                        return category_result
                
                # If country filter failed, try without country
                print(f"[SQLSearchTool] Fallback: Trying category search for '{categories[0]}' without country filter")
                category_result = self.search_by_category(categories[0], country=None, top_n=top_n)
                if category_result.get('count', 0) > 0:
                    return category_result
        
        # Priority 3: Try tags search
        if query_intent.query_tags:
            visual_tags = [tag for tag in query_intent.query_tags 
                          if tag not in ['mountain', 'lake', 'temple', 'museum', 'park', 
                                        'coast', 'cityscape', 'monument', 'bridge', 
                                        'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']]
            if visual_tags:
                season = query_intent.season_hint if query_intent.season_hint != 'unknown' else None
                print(f"[SQLSearchTool] Fallback: Trying tags search for {visual_tags}")
                tags_result = self.search_by_tags(visual_tags, season=season, top_n=top_n)
                if tags_result.get('count', 0) > 0:
                    return tags_result
        
        # Priority 4: If we have name candidates but no results, try fuzzy name search
        if query_intent.name_candidates:
            # Try searching with partial name
            for name in query_intent.name_candidates:
                if len(name) > 2:
                    partial_name = name[:len(name)//2] if len(name) > 4 else name
                    print(f"[SQLSearchTool] Fallback: Trying partial name search for '{partial_name}'")
                    name_result = self.search_by_name(partial_name, top_n=top_n)
                    if name_result.get('count', 0) > 0:
                        return name_result
        
        # Last resort: return empty result with helpful message
        return {
            "candidates": [],
            "count": 0,
            "warning": "No viewpoints found matching the search criteria. The database may not contain viewpoints matching all specified conditions.",
            "suggestion": "Try searching with fewer criteria, or check if the database contains relevant viewpoints. You can also try searching by name only."
        }
    
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
    
    def search_by_tags(
        self,
        tags: List[str],
        season: Optional[str] = None,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Search viewpoints by visual tags.
        
        Args:
            tags: List of visual tags to search for
            season: Optional season filter (spring, summer, autumn, winter)
            top_n: Maximum number of results
            
        Returns:
            Dict with candidates and SQL query info
        """
        # Map visual tags to categories if possible
        visual_to_category = {
            'snow_peak': 'mountain',
            'waterfall': 'waterfall',
        }
        
        category_list = []
        for tag in tags:
            if tag in visual_to_category:
                category_list.append(visual_to_category[tag])
        
        # Build SQL query
        conditions = []
        params = []
        
        # Category filter
        if category_list:
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
                season_filter = ""
                if season and season != 'unknown':
                    season_filter = "AND season = %s"
                    tag_params.append(season)
                
                conditions.append(f"""viewpoint_id IN (
                    SELECT DISTINCT viewpoint_id 
                    FROM viewpoint_visual_tags 
                    WHERE {' OR '.join(tag_conditions)}
                    {season_filter}
                )""")
                params.extend(tag_params)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        category_score_sql = "0.0"
        if category_list:
            placeholders = ','.join(['%s'] * len(category_list))
            category_score_sql = f"CASE WHEN e.category_norm IN ({placeholders}) THEN 1.0 ELSE 0.0 END"
        
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

