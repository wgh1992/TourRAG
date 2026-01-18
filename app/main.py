"""
TourRAG Main FastAPI Application

Main entry point for the viewpoint RAG system.
"""
import time
import os
import json
from pathlib import Path
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from psycopg2.extras import Json

from app.config import settings
from app.schemas.query import (
    ExtractQueryIntentInput,
    ExtractQueryIntentOutput,
    QueryResponse,
    UserImageInput
)
from app.tools.extract_query_intent import get_extract_query_intent_tool
from app.services.retrieval import get_retrieval_service
from app.services.llm_service import get_llm_service
from app.services.database import db

# Initialize FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="景点多模态 RAG 系统 - 全本地、Tag 驱动"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Local image directory (exports/images/all_image)
LOCAL_IMAGE_DIR = Path(__file__).parent.parent / "exports" / "images" / "all_image"
LOCAL_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _find_local_images(viewpoint_id: int) -> List[Path]:
    if not LOCAL_IMAGE_DIR.exists():
        return []

    matches: List[Path] = []
    for ext in LOCAL_IMAGE_EXTS:
        direct = LOCAL_IMAGE_DIR / f"{viewpoint_id}{ext}"
        if direct.exists():
            matches.append(direct)
        matches.extend(sorted(LOCAL_IMAGE_DIR.glob(f"{viewpoint_id}_*{ext}")))
        matches.extend(sorted(LOCAL_IMAGE_DIR.glob(f"{viewpoint_id}-*{ext}")))

    seen = set()
    unique_matches = []
    for path in matches:
        if path.name not in seen:
            seen.add(path.name)
            unique_matches.append(path)
    return unique_matches


@app.get("/")
async def root():
    """Root endpoint - serve UI"""
    static_file = Path(__file__).parent.parent / "static" / "index.html"
    if static_file.exists():
        return FileResponse(str(static_file))
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        with db.get_cursor() as cursor:
            cursor.execute("SELECT 1")
        
        return {
            "status": "healthy",
            "database": "connected"
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)}")


@app.post("/api/v1/extract-query-intent", response_model=ExtractQueryIntentOutput)
async def extract_query_intent(
    input_data: ExtractQueryIntentInput
):
    """
    MCP Tool endpoint: Extract structured query intent from user input.
    
    This is the ONLY tool that allows LLM to directly understand user input.
    """
    tool = get_extract_query_intent_tool()
    result = await tool.extract(input_data)
    return result


@app.post("/api/v1/query", response_model=QueryResponse)
async def query_viewpoints(
    user_text: Optional[str] = Form(None),
    user_images: Optional[List[UploadFile]] = File(None),
    language: str = Form("auto"),
    top_k: int = Form(5),
    # Also accept as query parameters for backward compatibility
    user_text_query: Optional[str] = Query(None, alias="user_text")
):
    """
    Main query endpoint for viewpoint search and recommendation.
    
    Uses GPT-4o-mini agent with SQL-based MCP tools for search.
    
    Process flow:
    1. Agent extracts query intent using extract_query_intent MCP tool
    2. Agent uses SQL-based MCP tools to search (search_by_name, search_by_category, search_by_tags)
    3. Agent gets details and ranks results
    4. Agent synthesizes final answer
    5. Return structured JSON results
    
    All searches are performed using MCP tools - no direct database access.
    
    Accepts form data: user_text, language, top_k, user_images
    """
    start_time = time.time()
    
    # Get user_text from form or query parameter
    final_user_text = user_text or user_text_query
    
    # Require user_text for agent search
    if not final_user_text or not final_user_text.strip():
        raise HTTPException(
            status_code=400,
            detail="user_text is required for agent-based search. Please provide a search query."
        )
    
    # Always use agent-based search with MCP tools
    from app.services.agent_service import get_agent_service
    
    print(f"[Query] Using agent-based MCP tool search for: '{final_user_text}'")
    agent = get_agent_service()
    
    # Build query text (include image info if present)
    query_text = final_user_text
    if user_images:
        query_text += " [with images]"
    
    # Use agent to answer the query
    agent_result = await agent.answer_query(
        user_query=query_text,
        language=language
    )
    
    # Extract query intent and results from agent's tool calls
    query_intent = None
    all_candidates = []  # Collect candidates from SQL searches
    final_results = []
    tool_calls_log = agent_result.get('tool_calls', [])
    sql_queries_log = []
    tag_schema_version = 'v1.0.0'
    
    # Process tool calls
    for tool_call in tool_calls_log:
        tool_name = tool_call.get('tool')
        result = tool_call.get('result', {})
        
        if tool_name == 'extract_query_intent':
            if 'query_intent' in result:
                from app.schemas.query import QueryIntent, GeoHints
                intent_dict = result['query_intent']
                query_intent = QueryIntent(
                    name_candidates=intent_dict.get('name_candidates', []),
                    query_tags=intent_dict.get('query_tags', []),
                    season_hint=intent_dict.get('season_hint', 'unknown'),
                    scene_hints=intent_dict.get('scene_hints', []),
                    geo_hints=GeoHints(
                        place_name=intent_dict.get('geo_hints', {}).get('place_name'),
                        country=intent_dict.get('geo_hints', {}).get('country')
                    ),
                    confidence_notes=intent_dict.get('confidence_notes', [])
                )
                tag_schema_version = result.get('tag_schema_version', 'v1.0.0')
        
        # Collect SQL queries and candidates from SQL search tools
        sql_tools = [
            'search_by_name',
            'search_by_category',
            'search_by_tags',
            'search_by_history_terms',
            'search_popular',
            'search_with_llm_sql'
        ]
        if tool_name in sql_tools:
            if 'sql' in result:
                sql_queries_log.append({
                    "sql": result.get('sql'),
                    "params": result.get('params', [])
                })
            # Collect candidates from SQL search
            if 'candidates' in result:
                all_candidates.extend(result['candidates'])
        
        if tool_name == 'rank_and_explain_results':
            results_data = result.get('results', [])
            from app.schemas.query import ViewpointResult, VisualTagInfo, Evidence
            for r in results_data:
                # Convert visual tags
                visual_tags = []
                for vt in r.get('visual_tags', []):
                    evidence_list = [Evidence(**e) if isinstance(e, dict) else e 
                                    for e in vt.get('evidence', [])]
                    visual_tags.append(VisualTagInfo(
                        season=vt['season'],
                        tags=vt['tags'],
                        confidence=vt['confidence'],
                        evidence=evidence_list,
                        tag_source=vt['tag_source']
                    ))
                
                final_results.append(ViewpointResult(
                    viewpoint_id=r['viewpoint_id'],
                    name_primary=r['name_primary'],
                    name_variants=r.get('name_variants', {}),
                    category_norm=r.get('category_norm'),
                    historical_summary=r.get('historical_summary'),
                    historical_evidence=[Evidence(**e) if isinstance(e, dict) else e 
                                        for e in r.get('historical_evidence', [])],
                    visual_tags=visual_tags,
                    match_confidence=r.get('match_confidence', 0.0),
                    match_explanation=r.get('match_explanation', '')
                ))
    
    # If no ranked results but we have candidates, use LLM service to rank them
    if not final_results and all_candidates and query_intent:
        print(f"[Query] Ranking {len(all_candidates)} candidates from SQL searches")
        from app.schemas.query import ViewpointCandidate
        candidate_objects = []
        for c in all_candidates:
            candidate_objects.append(ViewpointCandidate(**c))
        
        llm_service = get_llm_service()
        final_results = llm_service.rank_and_fuse(
            candidates=candidate_objects,
            query_intent=query_intent,
            top_k=top_k
        )
    
    # Ensure we have query intent (extract if agent didn't provide it)
    if not query_intent:
        print(f"[Query] Agent didn't extract intent, extracting directly")
        intent_input = ExtractQueryIntentInput(
            user_text=final_user_text,
            user_images=None,
            language=language
        )
        extract_tool = get_extract_query_intent_tool()
        intent_result = await extract_tool.extract(intent_input)
        query_intent = intent_result.query_intent
        tag_schema_version = intent_result.tag_schema_version
        
        # Add to tool calls log
        tool_calls_log.insert(0, {
            "tool": "extract_query_intent",
            "input": intent_input.model_dump(),
            "output": intent_result.model_dump()
        })
    
    # If still no results, run server-side fallback using query intent
    if not final_results and query_intent:
        from app.tools.sql_search_tool import get_sql_search_tool
        
        sql_tool = get_sql_search_tool()
        fallback_candidates = []
        fallback_sql_logs = []
        
        # 1) Try name search if we have a name candidate
        if query_intent.name_candidates:
            name_result = sql_tool.search_by_name(query_intent.name_candidates[0], top_n=50)
            if name_result.get("sql"):
                fallback_sql_logs.append({
                    "sql": name_result.get("sql"),
                    "params": name_result.get("params", [])
                })
            fallback_candidates.extend(name_result.get("candidates", []))
        
        # 2) Try tag-based search using known tag sources
        if not fallback_candidates and query_intent.query_tags:
            tag_sources = ["wiki_weak_supervision", "gpt_4o_mini_image_history"]
            tags_result = sql_tool.search_by_tags(
                query_intent.query_tags,
                season=query_intent.season_hint,
                tag_sources=tag_sources,
                top_n=50
            )
            if tags_result.get("sql"):
                fallback_sql_logs.append({
                    "sql": tags_result.get("sql"),
                    "params": tags_result.get("params", [])
                })
            fallback_candidates.extend(tags_result.get("candidates", []))
        
        # 3) Try history text search using scene hints or name candidates
        if not fallback_candidates:
            history_terms = query_intent.scene_hints or query_intent.name_candidates
            if history_terms:
                history_result = sql_tool.search_by_history_terms(history_terms, top_n=50)
                if history_result.get("sql"):
                    fallback_sql_logs.append({
                        "sql": history_result.get("sql"),
                        "params": history_result.get("params", [])
                    })
                fallback_candidates.extend(history_result.get("candidates", []))
        
        # Deduplicate by viewpoint_id
        if fallback_candidates:
            seen_ids = set()
            unique_candidates = []
            for c in fallback_candidates:
                vid = c.get("viewpoint_id")
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)
                unique_candidates.append(c)
            
            sql_queries_log.extend(fallback_sql_logs)
            
            from app.schemas.query import ViewpointCandidate
            candidate_objects = [ViewpointCandidate(**c) for c in unique_candidates]
            
            llm_service = get_llm_service()
            final_results = llm_service.rank_and_fuse(
                candidates=candidate_objects,
                query_intent=query_intent,
                top_k=top_k
            )
    
    # If no results from agent, return empty results with intent
    if not final_results:
        print(f"[Query] No results from agent search")
    
    execution_time = int((time.time() - start_time) * 1000)
    
    print(f"[Query] Agent MCP tool search completed: {len(final_results)} results in {execution_time}ms")
    
    # Log query (optional - could be async)
    try:
        with db.get_cursor() as cursor:
            # Convert dicts to Json objects for JSONB columns
            user_images_json = Json([])  # Images not processed in agent mode
            query_intent_json = Json(query_intent.model_dump())
            sql_queries_json = Json(sql_queries_log)
            tool_calls_json = Json(tool_calls_log)
            results_json = Json([r.model_dump() for r in final_results])
            
            cursor.execute("""
                INSERT INTO query_log (
                    user_text, user_images, query_intent, 
                    sql_queries, tool_calls, results, execution_time_ms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                final_user_text or "",
                user_images_json,
                query_intent_json,
                sql_queries_json,
                tool_calls_json,
                results_json,
                execution_time
            ))
    except Exception as e:
        # Log error but don't fail the request
        print(f"Failed to log query: {e}")
    
    return QueryResponse(
        query_intent=query_intent,
        candidates=final_results[:top_k],
        sql_queries=sql_queries_log,
        tool_calls=tool_calls_log,
        execution_time_ms=execution_time,
        tag_schema_version=tag_schema_version
    )


@app.post("/api/v1/agent/query")
async def agent_query(
    user_query: str,
    language: str = "auto"
):
    """
    Agent-based query endpoint using GPT-4o-mini with tool calling.
    
    The agent will:
    1. Understand the query using extract_query_intent tool
    2. Search the database using search_viewpoints tool
    3. Get details using get_viewpoint_details tool if needed
    4. Rank and explain results
    5. Synthesize a natural language answer
    """
    from app.services.agent_service import get_agent_service
    
    agent = get_agent_service()
    result = await agent.answer_query(
        user_query=user_query,
        language=language
    )
    
    return result


@app.get("/api/v1/viewpoint/{viewpoint_id}")
async def get_viewpoint_detail(viewpoint_id: int):
    """
    Get detailed information about a specific viewpoint.
    """
    from app.services.enrichment import get_enrichment_service
    
    enrichment = get_enrichment_service()
    
    # Get all enrichment data
    wiki_data = enrichment.enrich_wikipedia(viewpoint_id)
    wikidata_data = enrichment.enrich_wikidata(viewpoint_id)
    visual_tags = enrichment.enrich_visual_tags(viewpoint_id)
    commons_assets = enrichment.enrich_commons_assets(viewpoint_id)
    historical_summary, historical_evidence = enrichment.get_historical_summary(viewpoint_id)
    
    # Get entity info
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT 
                viewpoint_id, name_primary, name_variants,
                category_norm, category_osm, geom, popularity
            FROM viewpoint_entity
            WHERE viewpoint_id = %s
        """, (viewpoint_id,))
        entity = cursor.fetchone()
    
    if not entity:
        raise HTTPException(status_code=404, detail="Viewpoint not found")
    
    local_images = _find_local_images(viewpoint_id)
    return {
        "viewpoint_id": entity['viewpoint_id'],
        "name_primary": entity['name_primary'],
        "name_variants": entity['name_variants'],
        "category_norm": entity['category_norm'],
        "category_osm": entity['category_osm'],
        "popularity": float(entity['popularity']),
        "wikipedia": wiki_data,
        "wikidata": wikidata_data,
        "visual_tags": visual_tags,
        "commons_assets": commons_assets,
        "local_images": [
            {
                "filename": path.name,
                "url": f"/api/v1/viewpoint/{viewpoint_id}/local-image/{path.name}"
            }
            for path in local_images
        ],
        "historical_summary": historical_summary,
        "historical_evidence": [e.model_dump() for e in historical_evidence]
    }


@app.get("/api/v1/viewpoints/map")
async def get_viewpoints_for_map(
    limit: Optional[int] = Query(None, description="Limit number of viewpoints to return"),
    min_popularity: Optional[float] = Query(None, description="Minimum popularity score")
):
    """
    Get all viewpoints with coordinates for map display (optimized for performance).
    
    Returns minimal data: only id, lat, lng, and name for fast rendering.
    """
    with db.get_cursor() as cursor:
        query = """
            SELECT 
                v.viewpoint_id,
                v.name_primary,
                ST_Y(v.geom::geometry) as latitude,
                ST_X(v.geom::geometry) as longitude
            FROM viewpoint_entity v
            WHERE v.geom IS NOT NULL
        """
        
        params = []
        if min_popularity is not None:
            query += " AND v.popularity >= %s"
            params.append(min_popularity)
        
        query += " ORDER BY v.viewpoint_id"
        
        if limit:
            query += " LIMIT %s"
            params.append(limit)
        
        cursor.execute(query, params)
        viewpoints = cursor.fetchall()
    
    # Return minimal data for fast rendering
    return {
        "viewpoints": [
            {
                "id": v['viewpoint_id'],
                "n": v['name_primary'] or 'Unnamed',
                "lat": float(v['latitude']),
                "lng": float(v['longitude'])
            }
            for v in viewpoints
        ],
        "total": len(viewpoints)
    }


@app.get("/api/v1/image/{asset_id}")
async def get_image(asset_id: int):
    """
    Get image data for a specific Commons asset.
    
    Returns the image binary data with appropriate content type.
    """
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT 
                image_blob,
                image_format,
                image_width,
                image_height
            FROM viewpoint_commons_assets
            WHERE id = %s AND image_blob IS NOT NULL
        """, (asset_id,))
        
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Image not found")
        
        image_blob = result['image_blob']
        image_format = result['image_format'] or 'jpeg'
        
        # Determine content type
        content_types = {
            'jpeg': 'image/jpeg',
            'jpg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        content_type = content_types.get(image_format.lower(), 'image/jpeg')
        
        return Response(
            content=bytes(image_blob),
            media_type=content_type
        )


@app.get("/api/v1/viewpoint/{viewpoint_id}/images")
async def get_viewpoint_images(
    viewpoint_id: int,
    include_data: bool = Query(False, description="Include base64 image data in response")
):
    """
    Get all images for a specific viewpoint.
    
    By default, returns metadata only. Set include_data=true to include base64-encoded image data.
    """
    from app.services.enrichment import get_enrichment_service
    
    enrichment = get_enrichment_service()
    assets = enrichment.enrich_commons_assets(
        viewpoint_id=viewpoint_id,
        limit=50,
        include_image_data=include_data
    )
    
    return {
        "viewpoint_id": viewpoint_id,
        "images": assets,
        "count": len(assets)
    }


@app.get("/api/v1/viewpoint/{viewpoint_id}/local-images")
async def get_viewpoint_local_images(viewpoint_id: int):
    """
    Get local image files for a viewpoint from exports/images/all_image.
    """
    local_images = _find_local_images(viewpoint_id)
    return {
        "viewpoint_id": viewpoint_id,
        "images": [
            {
                "filename": path.name,
                "url": f"/api/v1/viewpoint/{viewpoint_id}/local-image/{path.name}"
            }
            for path in local_images
        ],
        "count": len(local_images)
    }


@app.get("/api/v1/viewpoint/{viewpoint_id}/local-image/{filename}")
async def get_viewpoint_local_image(viewpoint_id: int, filename: str):
    """
    Serve a local image file for a specific viewpoint.
    """
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    local_images = _find_local_images(viewpoint_id)
    image_map = {path.name: path for path in local_images}
    image_path = image_map.get(filename)
    if not image_path or not image_path.exists():
        raise HTTPException(status_code=404, detail="Local image not found")

    return FileResponse(str(image_path))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

