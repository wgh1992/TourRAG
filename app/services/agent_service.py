"""
GPT-4o-mini Agent Service with Tool Calling

An agentic system where GPT-4o-mini uses tools to search and answer questions
about tourist attractions and viewpoints.
"""
import json
from typing import List, Dict, Any, Optional
from openai import OpenAI

from app.config import settings
from app.schemas.query import QueryIntent, ViewpointResult
from app.tools.extract_query_intent import get_extract_query_intent_tool
from app.tools.sql_search_tool import get_sql_search_tool
from app.services.retrieval import get_retrieval_service
from app.services.enrichment import EnrichmentService
from app.services.llm_service import get_llm_service


class AgentService:
    """
    GPT-4o-mini Agent that uses tools to search and answer questions.
    
    The agent can:
    - Extract query intent
    - Search the database
    - Get viewpoint details
    - Synthesize answers
    """
    
    def __init__(self, openai_client: Optional[OpenAI] = None):
        self.client = openai_client or OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4o-mini"
        self.extract_tool = get_extract_query_intent_tool()
        self.sql_search = get_sql_search_tool()
        self.retrieval = get_retrieval_service()
        self.enrichment = EnrichmentService()
        self.llm_service = get_llm_service()
        
        # Define SQL-based MCP tools available to the agent
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "extract_query_intent",
                    "description": "Extract structured query intent from user text. Use this first to understand what the user is looking for.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_text": {
                                "type": "string",
                                "description": "The user's search query or question"
                            },
                            "language": {
                                "type": "string",
                                "enum": ["auto", "en", "zh"],
                                "description": "Language preference for processing"
                            }
                        },
                        "required": ["user_text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_by_name",
                    "description": "Search viewpoints by name using SQL. Use this when you have a specific place name or partial name.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name_pattern": {
                                "type": "string",
                                "description": "Name pattern to search for (e.g., 'Mount Fuji', 'Fuji', 'Tokyo'). Supports partial matches."
                            },
                            "top_n": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 50
                            }
                        },
                        "required": ["name_pattern"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_by_category",
                    "description": "Search viewpoints by category using SQL. Categories: mountain, lake, temple, museum, park, coast, cityscape, monument, bridge, palace, tower, cave, waterfall, valley, island.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["mountain", "lake", "temple", "museum", "park", "coast", "cityscape", "monument", "bridge", "palace", "tower", "cave", "waterfall", "valley", "island"],
                                "description": "Category to search for"
                            },
                            "top_n": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 50
                            }
                        },
                        "required": ["category"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_by_tags",
                    "description": "Search viewpoints by visual tags using SQL. Visual tags include: snow_peak, cherry_blossom, sunset, sunrise, autumn_foliage, etc. This searches the viewpoint_visual_tags table.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of visual tags to search for (e.g., ['snow_peak', 'snowy'], ['cherry_blossom', 'blooming_flowers'])"
                            },
                            "season": {
                                "type": "string",
                                "enum": ["spring", "summer", "autumn", "winter", "unknown"],
                                "description": "Optional season filter to narrow down results",
                                "default": "unknown"
                            },
                            "top_n": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 50
                            }
                        },
                        "required": ["tags"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_popular",
                    "description": "Get the most popular viewpoints using SQL. Use this as a fallback when no specific search criteria are available.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "top_n": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 50
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_viewpoint_details",
                    "description": "Get detailed information about a specific viewpoint including Wikipedia, Wikidata, and visual tags.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "viewpoint_id": {
                                "type": "integer",
                                "description": "The ID of the viewpoint to get details for"
                            }
                        },
                        "required": ["viewpoint_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "rank_and_explain_results",
                    "description": "Rank search results and generate explanations for why they match the query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "candidates": {
                                "type": "array",
                                "description": "List of candidate viewpoints from search",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "viewpoint_id": {
                                            "type": "integer",
                                            "description": "Viewpoint ID"
                                        },
                                        "name_primary": {
                                            "type": "string",
                                            "description": "Primary name of the viewpoint"
                                        },
                                        "name_variants": {
                                            "type": "object",
                                            "description": "Alternative names"
                                        },
                                        "category_norm": {
                                            "type": "string",
                                            "description": "Normalized category"
                                        },
                                        "name_score": {
                                            "type": "number",
                                            "description": "Name matching score"
                                        },
                                        "geo_score": {
                                            "type": "number",
                                            "description": "Geographic matching score"
                                        },
                                        "category_score": {
                                            "type": "number",
                                            "description": "Category matching score"
                                        },
                                        "popularity": {
                                            "type": "number",
                                            "description": "Popularity score"
                                        }
                                    },
                                    "required": ["viewpoint_id", "name_primary"]
                                }
                            },
                            "query_intent": {
                                "type": "object",
                                "description": "The original query intent",
                                "properties": {
                                    "name_candidates": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Possible place names"
                                    },
                                    "query_tags": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Query tags"
                                    },
                                    "season_hint": {
                                        "type": "string",
                                        "enum": ["spring", "summer", "autumn", "winter", "unknown"],
                                        "description": "Season preference"
                                    },
                                    "scene_hints": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Scene-level hints"
                                    },
                                    "geo_hints": {
                                        "type": "object",
                                        "properties": {
                                            "place_name": {
                                                "type": "string",
                                                "description": "City or region name"
                                            },
                                            "country": {
                                                "type": "string",
                                                "description": "Country name"
                                            }
                                        }
                                    },
                                    "confidence_notes": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "Confidence notes"
                                    }
                                },
                                "required": ["season_hint", "geo_hints"]
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Number of top results to return",
                                "default": 5
                            }
                        },
                        "required": ["candidates", "query_intent"]
                    }
                }
            }
        ]
    
    async def answer_query(
        self,
        user_query: str,
        language: str = "auto",
        max_iterations: int = 5
    ) -> Dict[str, Any]:
        """
        Use GPT-4o-mini agent with tools to answer a user query.
        
        Args:
            user_query: The user's question or search query
            language: Language preference
            max_iterations: Maximum number of tool-calling iterations
            
        Returns:
            Dict with answer, reasoning, and tool calls
        """
        messages = [
            {
                "role": "system",
                "content": """You are a helpful assistant for a tourist attraction search system (TourRAG).

Your job is to help users find information about tourist attractions and viewpoints using SQL-based search tools.

You have access to SQL-based MCP tools:
1. extract_query_intent - Extract structured intent from user text (use this first)
2. search_by_name - Search by place name using SQL (e.g., "Mount Fuji", "Tokyo")
3. search_by_category - Search by category using SQL (mountain, lake, temple, etc.)
4. search_by_tags - Search by visual tags using SQL (snow_peak, cherry_blossom, etc.)
5. search_popular - Get popular viewpoints using SQL
6. get_viewpoint_details - Get detailed info about a specific viewpoint
7. rank_and_explain_results - Rank and explain search results

Use these SQL-based tools strategically:
1. First, extract query intent to understand what the user wants
2. Based on intent, use appropriate SQL search tools:
   - If name_candidates exist → use search_by_name
   - If query_tags include categories → use search_by_category
   - If query_tags include visual tags → use search_by_tags
   - If season_hint is provided → include it in search_by_tags
3. Get details for promising candidates (use get_viewpoint_details)
4. Rank and explain results (use rank_and_explain_results)
5. Synthesize a helpful answer

Be strategic: Use SQL tools to find relevant viewpoints, then enrich with details."""
            },
            {
                "role": "user",
                "content": user_query
            }
        ]
        
        tool_calls_log = []
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            print(f"[Agent] Iteration {iteration}/{max_iterations}")
            
            # Call GPT-4o-mini with tools
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=0.3
            )
            
            message = response.choices[0].message
            messages.append(message)
            
            # Check if the model wants to call a tool
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    print(f"[Agent] Calling tool: {function_name} with args: {function_args}")
                    
                    # Execute the tool
                    tool_result = await self._execute_tool(function_name, function_args)
                    
                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result, ensure_ascii=False)
                    })
                    
                    tool_calls_log.append({
                        "tool": function_name,
                        "arguments": function_args,
                        "result": tool_result
                    })
            else:
                # Model has finished - return the final answer
                final_answer = message.content
                print(f"[Agent] Final answer: {final_answer[:200]}...")
                
                return {
                    "answer": final_answer,
                    "tool_calls": tool_calls_log,
                    "iterations": iteration
                }
        
        # Max iterations reached
        return {
            "answer": "I've reached the maximum number of iterations. Please try rephrasing your query.",
            "tool_calls": tool_calls_log,
            "iterations": iteration,
            "error": "max_iterations_reached"
        }
    
    async def _execute_tool(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool function and return the result"""
        
        if function_name == "extract_query_intent":
            from app.schemas.query import ExtractQueryIntentInput
            input_data = ExtractQueryIntentInput(
                user_text=arguments.get("user_text"),
                language=arguments.get("language", "auto")
            )
            result = await self.extract_tool.extract(input_data)
            return result.model_dump()
        
        elif function_name == "search_by_name":
            name_pattern = arguments.get("name_pattern")
            top_n = arguments.get("top_n", 50)
            result = self.sql_search.search_by_name(name_pattern, top_n)
            return result
        
        elif function_name == "search_by_category":
            category = arguments.get("category")
            top_n = arguments.get("top_n", 50)
            result = self.sql_search.search_by_category(category, top_n)
            return result
        
        elif function_name == "search_by_tags":
            tags = arguments.get("tags", [])
            season = arguments.get("season", "unknown")
            top_n = arguments.get("top_n", 50)
            result = self.sql_search.search_by_tags(tags, season, top_n)
            return result
        
        elif function_name == "search_popular":
            top_n = arguments.get("top_n", 50)
            result = self.sql_search.search_popular(top_n)
            return result
        
        elif function_name == "get_viewpoint_details":
            viewpoint_id = arguments.get("viewpoint_id")
            wiki_data = self.enrichment.enrich_wikipedia(viewpoint_id)
            wikidata_data = self.enrichment.enrich_wikidata(viewpoint_id)
            visual_tags = self.enrichment.enrich_visual_tags(viewpoint_id)
            historical_summary, historical_evidence = self.enrichment.get_historical_summary(viewpoint_id)
            
            # Get entity info
            from app.services.database import db
            with db.get_cursor() as cursor:
                cursor.execute("""
                    SELECT viewpoint_id, name_primary, name_variants,
                           category_norm, category_osm, popularity
                    FROM viewpoint_entity
                    WHERE viewpoint_id = %s
                """, (viewpoint_id,))
                entity = cursor.fetchone()
            
            if not entity:
                return {"error": "Viewpoint not found"}
            
            return {
                "viewpoint_id": entity['viewpoint_id'],
                "name_primary": entity['name_primary'],
                "name_variants": entity['name_variants'],
                "category_norm": entity['category_norm'],
                "popularity": float(entity['popularity']),
                "wikipedia": wiki_data,
                "wikidata": wikidata_data,
                "visual_tags": visual_tags,
                "historical_summary": historical_summary,
                "historical_evidence": [e.model_dump() for e in historical_evidence]
            }
        
        elif function_name == "rank_and_explain_results":
            # This would use the LLM service to rank results
            # For now, return a simplified version
            candidates = arguments.get("candidates", [])
            query_intent_dict = arguments.get("query_intent", {})
            top_k = arguments.get("top_k", 5)
            
            from app.schemas.query import QueryIntent, GeoHints, ViewpointCandidate
            query_intent = QueryIntent(
                name_candidates=query_intent_dict.get("name_candidates", []),
                query_tags=query_intent_dict.get("query_tags", []),
                season_hint=query_intent_dict.get("season_hint", "unknown"),
                scene_hints=query_intent_dict.get("scene_hints", []),
                geo_hints=GeoHints(
                    place_name=query_intent_dict.get("geo_hints", {}).get("place_name"),
                    country=query_intent_dict.get("geo_hints", {}).get("country")
                ),
                confidence_notes=query_intent_dict.get("confidence_notes", [])
            )
            
            # Convert candidates to ViewpointCandidate objects
            candidate_objects = []
            for c in candidates:
                candidate_objects.append(ViewpointCandidate(
                    viewpoint_id=c['viewpoint_id'],
                    name_primary=c['name_primary'],
                    name_variants=c.get('name_variants', {}),
                    category_norm=c.get('category_norm'),
                    name_score=c.get('name_score', 0.0),
                    geo_score=c.get('geo_score', 0.0),
                    category_score=c.get('category_score', 0.0),
                    popularity=c.get('popularity', 0.0)
                ))
            
            # Use LLM service to rank
            results = self.llm_service.rank_and_fuse(
                candidates=candidate_objects,
                query_intent=query_intent,
                top_k=top_k
            )
            
            return {
                "results": [r.model_dump() for r in results],
                "count": len(results)
            }
        
        else:
            return {"error": f"Unknown tool: {function_name}"}


# Singleton instance
_agent_service: Optional[AgentService] = None


def get_agent_service() -> AgentService:
    """Get singleton instance of agent service"""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service

