"""
In-DB Retrieval Service

Fast, stable SQL-based candidate retrieval from local database.
"""
from typing import List, Dict, Any, Optional
import psycopg2.extras
from app.services.database import db
from app.schemas.query import ViewpointCandidate, QueryIntent


class RetrievalService:
    """
    In-DB Retrieval layer for candidate viewpoint generation.
    
    This service performs:
    - Name/alias matching (fuzzy)
    - Geographic filtering
    - Category filtering
    - Returns Top-N candidates with scores
    """
    
    def search(
        self,
        query_intent: QueryIntent,
        top_n: int = 50,
        geo_bbox: Optional[Dict[str, float]] = None
    ) -> tuple[List[ViewpointCandidate], List[Dict[str, Any]]]:
        """
        Search for candidate viewpoints based on query intent.
        
        Args:
            query_intent: Structured query intent
            top_n: Maximum number of candidates to return
            geo_bbox: Optional bounding box {min_lon, min_lat, max_lon, max_lat}
            
        Returns:
            Tuple of (candidates, sql_queries_log)
        """
        sql_queries_log = []
        
        # Prepare parameters for array matching
        name_patterns = [f"%{name}%" for name in query_intent.name_candidates] if query_intent.name_candidates else []
        category_list = [tag for tag in query_intent.query_tags 
                        if tag in ['mountain', 'lake', 'temple', 'museum', 'park', 
                                  'coast', 'cityscape', 'monument', 'bridge', 
                                  'palace', 'tower', 'cave', 'waterfall', 'valley', 'island']]
        
        # Build SQL query with psycopg2 parameterized queries
        conditions = []
        params = []
        
        # Name matching
        if query_intent.name_candidates:
            name_conditions = []
            for name in query_intent.name_candidates:
                pattern = f"%{name}%"
                name_conditions.append("(name_primary ILIKE %s OR name_variants::text ILIKE %s)")
                params.extend([pattern, pattern])
            
            if name_conditions:
                conditions.append(f"({' OR '.join(name_conditions)})")
        
        # Category filtering
        if category_list:
            placeholders = ','.join(['%s'] * len(category_list))
            conditions.append(f"category_norm IN ({placeholders})")
            params.extend(category_list)
        
        # Geographic filtering (bbox)
        if geo_bbox:
            conditions.append(
                "ST_Within(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            )
            params.extend([
                geo_bbox['min_lon'],
                geo_bbox['min_lat'],
                geo_bbox['max_lon'],
                geo_bbox['max_lat']
            ])
        
        # Build final query
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Build SQL - use simpler approach without ANY() for arrays
        # Instead, use OR conditions for name matching and IN for categories
        name_score_sql = "0.5"  # Default score
        if name_patterns:
            # Build OR conditions for name matching
            name_ors = " OR ".join(["name_primary ILIKE %s"] * len(name_patterns))
            name_score_sql = f"CASE WHEN ({name_ors}) THEN 1.0 ELSE 0.5 END"
            params.extend(name_patterns)
        
        category_score_sql = "0.0"  # Default score
        if category_list:
            placeholders = ','.join(['%s'] * len(category_list))
            category_score_sql = f"CASE WHEN category_norm IN ({placeholders}) THEN 1.0 ELSE 0.0 END"
            params.extend(category_list)
        
        sql = f"""
        SELECT 
            viewpoint_id,
            name_primary,
            name_variants,
            category_norm,
            popularity,
            -- Name score
            {name_score_sql} as name_score,
            -- Geo score (placeholder)
            1.0 as geo_score,
            -- Category score
            {category_score_sql} as category_score
        FROM viewpoint_entity
        WHERE {where_clause}
        ORDER BY 
            name_score DESC,
            popularity DESC,
            category_score DESC
        LIMIT %s
        """
        
        # Add limit
        params.append(top_n)
        final_params = params
        
        # Log SQL query
        sql_queries_log.append({
            "sql": sql,
            "params": params  # Exclude array params from log for readability
        })
        
        # Execute query
        with db.get_cursor() as cursor:
            cursor.execute(sql, final_params)
            rows = cursor.fetchall()
        
        # Convert to ViewpointCandidate objects
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
        
        return candidates, sql_queries_log


# Singleton instance
_retrieval_service = RetrievalService()


def get_retrieval_service() -> RetrievalService:
    """Get singleton instance of retrieval service"""
    return _retrieval_service

