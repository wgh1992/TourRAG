"""
MCP Tool: SQL-based search for viewpoints

This tool allows the LLM to construct and execute SQL queries to search the database.
"""
import json
from typing import List, Dict, Any, Optional
from app.services.database import db
from app.schemas.query import ViewpointCandidate


class SQLSearchTool:
    """
    MCP Tool for SQL-based viewpoint search.
    
    Allows LLM to construct SQL queries to search viewpoints by:
    - Name matching (ILIKE)
    - Category filtering
    - Popularity sorting
    - Geographic filtering (if needed)
    """
    
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
        
        return {
            "candidates": [c.model_dump() for c in candidates],
            "count": len(candidates),
            "sql": sql,
            "params": params
        }
    
    def search_by_category(
        self,
        category: str,
        top_n: int = 50
    ) -> Dict[str, Any]:
        """
        Search viewpoints by category.
        
        Args:
            category: Category name (mountain, lake, temple, etc.)
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
        
        return {
            "candidates": [c.model_dump() for c in candidates],
            "count": len(candidates),
            "sql": sql,
            "params": params
        }
    
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

