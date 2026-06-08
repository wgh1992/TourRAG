"""
FastMCP 3.x server for TourRAG tools.

This exposes the existing TourRAG service layer as real MCP tools while keeping
the FastAPI app unchanged for the web/API interface.
"""
import argparse
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP

from app.config import settings
from app.schemas.query import ExtractQueryIntentInput, GeoHints, QueryIntent
from app.services.agent_service import get_agent_service
from app.services.enrichment import EnrichmentService
from app.tools.extract_query_intent import get_extract_query_intent_tool
from app.tools.sql_search_tool import get_sql_search_tool


mcp = FastMCP(
    name="TourRAG",
    version=settings.APP_VERSION,
    instructions=(
        "TourRAG provides retrieval tools for tourist attraction search. "
        "Use extract_query_intent first, then search tools, then "
        "get_viewpoint_details or rank_and_explain_results."
    ),
)


def _query_intent_from_dict(data: Dict[str, Any]) -> QueryIntent:
    geo_hints_data = data.get("geo_hints") or {}
    if not isinstance(geo_hints_data, dict):
        geo_hints_data = {}

    return QueryIntent(
        name_candidates=data.get("name_candidates") or [],
        query_tags=data.get("query_tags") or [],
        season_hint=data.get("season_hint") or "unknown",
        scene_hints=data.get("scene_hints") or [],
        geo_hints=GeoHints(
            place_name=geo_hints_data.get("place_name"),
            country=geo_hints_data.get("country"),
        ),
        confidence_notes=data.get("confidence_notes") or [],
    )


@mcp.tool
async def extract_query_intent(user_text: str, language: str = "auto") -> Dict[str, Any]:
    """Extract structured TourRAG query intent from user text."""
    if language not in {"auto", "en", "zh"}:
        language = "auto"

    tool = get_extract_query_intent_tool()
    result = await tool.extract(
        ExtractQueryIntentInput(user_text=user_text, language=language)
    )
    return result.model_dump()


@mcp.tool
def search_by_category(
    category: str,
    country: Optional[str] = None,
    top_n: int = 50,
) -> Dict[str, Any]:
    """Search viewpoints by normalized category, optionally filtered by country."""
    return get_sql_search_tool().search_by_category(
        category=category,
        country=country,
        top_n=top_n,
    )


@mcp.tool
def search_by_tags(
    tags: List[str],
    season: str = "unknown",
    tag_sources: Optional[List[str]] = None,
    top_n: int = 50,
) -> Dict[str, Any]:
    """Search viewpoints by visual, scene, category, or seasonal tags."""
    return get_sql_search_tool().search_by_tags(
        tags=tags,
        season=season,
        tag_sources=tag_sources,
        top_n=top_n,
    )


@mcp.tool
def search_by_history_terms(terms: List[str], top_n: int = 50) -> Dict[str, Any]:
    """Search viewpoints by matching terms in Wikipedia/history text."""
    return get_sql_search_tool().search_by_history_terms(terms=terms, top_n=top_n)


@mcp.tool
def search_with_llm_sql(query_intent: Dict[str, Any], top_n: int = 50) -> Dict[str, Any]:
    """Search viewpoints with LLM-generated SQL from a structured query intent."""
    intent = _query_intent_from_dict(query_intent or {})
    return get_sql_search_tool().search_with_llm_sql(query_intent=intent, top_n=top_n)


@mcp.tool
def search_popular(top_n: int = 50) -> Dict[str, Any]:
    """Return the most popular viewpoints in the local database."""
    return get_sql_search_tool().search_popular(top_n=top_n)


@mcp.tool
def get_viewpoint_details(viewpoint_id: int) -> Dict[str, Any]:
    """Return entity, wiki, wikidata, visual tag, and summary details."""
    enrichment = EnrichmentService()
    wiki_data = enrichment.enrich_wikipedia(viewpoint_id)
    wikidata_data = enrichment.enrich_wikidata(viewpoint_id)
    visual_tags = enrichment.enrich_visual_tags(viewpoint_id)
    historical_summary, historical_evidence = enrichment.get_historical_summary(viewpoint_id)

    from app.services.database import db

    with db.get_cursor() as cursor:
        cursor.execute(
            """
            SELECT viewpoint_id, name_primary, name_variants,
                   category_norm, category_osm, popularity
            FROM viewpoint_entity
            WHERE viewpoint_id = %s
            """,
            (viewpoint_id,),
        )
        entity = cursor.fetchone()

    if not entity:
        return {"error": "Viewpoint not found", "viewpoint_id": viewpoint_id}

    return {
        "viewpoint_id": entity["viewpoint_id"],
        "name_primary": entity["name_primary"],
        "name_variants": entity["name_variants"],
        "category_norm": entity["category_norm"],
        "category_osm": entity["category_osm"],
        "popularity": float(entity["popularity"] or 0.0),
        "wikipedia": wiki_data,
        "wikidata": wikidata_data,
        "visual_tags": visual_tags,
        "historical_summary": historical_summary,
        "historical_evidence": [e.model_dump() for e in historical_evidence],
    }


@mcp.tool
def rank_and_explain_results(
    candidates: List[Dict[str, Any]],
    query_intent: Dict[str, Any],
    top_k: int = 5,
) -> Dict[str, Any]:
    """Rank retrieved candidates and attach explanations/evidence."""
    agent = get_agent_service()
    return agent._sync_execute_rank_and_explain(
        candidates=candidates,
        query_intent_dict=query_intent,
        top_k=top_k,
    )


@mcp.tool
async def answer_query(
    user_query: str,
    language: str = "auto",
    max_iterations: int = 5,
) -> Dict[str, Any]:
    """Run the full TourRAG agent loop and return the final answer."""
    if language not in {"auto", "en", "zh"}:
        language = "auto"
    agent = get_agent_service()
    return await agent.answer_query(
        user_query=user_query,
        language=language,
        max_iterations=max_iterations,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the TourRAG FastMCP server.")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "streamable-http", "sse"],
        default="streamable-http",
        help="FastMCP transport. Use stdio for local MCP clients.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
