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
from fastapi.responses import FileResponse
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
        sql_tools = ['search_by_name', 'search_by_category', 'search_by_tags', 'search_popular']
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
        "historical_summary": historical_summary,
        "historical_evidence": [e.model_dump() for e in historical_evidence]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

