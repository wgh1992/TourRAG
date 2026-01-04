"""
TourRAG Main FastAPI Application

Main entry point for the viewpoint RAG system.
"""
import time
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/")
async def root():
    """Root endpoint"""
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
    user_text: Optional[str] = None,
    user_images: Optional[List[UploadFile]] = File(None),
    language: str = "auto",
    top_k: int = 5
):
    """
    Main query endpoint for viewpoint search and recommendation.
    
    Process flow:
    1. Extract query intent (MCP tool)
    2. In-DB retrieval (SQL)
    3. External enrichment (local encyclopedia)
    4. LLM fusion and ranking
    5. Return structured JSON results
    """
    start_time = time.time()
    
    # Step 1: Extract query intent
    # Convert uploaded images to UserImageInput format
    image_inputs = []
    if user_images:
        import tempfile
        import os
        
        temp_files = []
        for img_file in user_images:
            # Save uploaded file temporarily and encode to base64
            try:
                # Read image content
                image_content = await img_file.read()
                
                # Encode to base64
                import base64
                image_base64 = base64.b64encode(image_content).decode('utf-8')
                
                # Create data URL
                mime_type = img_file.content_type or 'image/jpeg'
                data_url = f"data:{mime_type};base64,{image_base64}"
                
                image_inputs.append(UserImageInput(
                    image_id=data_url,  # Pass base64 data URL directly
                    mime_type=mime_type
                ))
            except Exception as e:
                print(f"Error processing image {img_file.filename}: {e}")
                continue
    
    intent_input = ExtractQueryIntentInput(
        user_text=user_text,
        user_images=image_inputs if image_inputs else None,
        language=language
    )
    
    extract_tool = get_extract_query_intent_tool()
    intent_result = await extract_tool.extract(intent_input)
    query_intent = intent_result.query_intent
    
    tool_calls_log = [{
        "tool": "extract_query_intent",
        "input": intent_input.model_dump(),
        "output": intent_result.model_dump()
    }]
    
    # Step 2: In-DB Retrieval
    retrieval_service = get_retrieval_service()
    candidates, sql_queries_log = retrieval_service.search(
        query_intent=query_intent,
        top_n=50  # Retrieve more candidates for better ranking
    )
    
    if not candidates:
        # No candidates found
        execution_time = int((time.time() - start_time) * 1000)
        return QueryResponse(
            query_intent=query_intent,
            candidates=[],
            sql_queries=sql_queries_log,
            tool_calls=tool_calls_log,
            execution_time_ms=execution_time,
            tag_schema_version=intent_result.tag_schema_version
        )
    
    # Step 3 & 4: Enrichment and LLM Fusion
    llm_service = get_llm_service()
    final_results = llm_service.rank_and_fuse(
        candidates=candidates,
        query_intent=query_intent,
        top_k=top_k
    )
    
    execution_time = int((time.time() - start_time) * 1000)
    
    # Log query (optional - could be async)
    try:
        with db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO query_log (
                    user_text, user_images, query_intent, 
                    sql_queries, tool_calls, results, execution_time_ms
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                user_text,
                [img.model_dump() for img in image_inputs] if image_inputs else [],
                query_intent.model_dump(),
                sql_queries_log,
                tool_calls_log,
                [r.model_dump() for r in final_results],
                execution_time
            ))
    except Exception as e:
        # Log error but don't fail the request
        print(f"Failed to log query: {e}")
    
    return QueryResponse(
        query_intent=query_intent,
        candidates=final_results,
        sql_queries=sql_queries_log,
        tool_calls=tool_calls_log,
        execution_time_ms=execution_time,
        tag_schema_version=intent_result.tag_schema_version
    )


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

