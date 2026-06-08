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
    
    def __init__(self, openai_client: Optional[OpenAI] = None, perfect_match_top_k: int = 5):
        self.client = openai_client or OpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = "gpt-4o-mini"
        self.extract_tool = get_extract_query_intent_tool()
        self.sql_search = get_sql_search_tool()
        self.retrieval = get_retrieval_service()
        self.enrichment = EnrichmentService()
        self.llm_service = get_llm_service()
        self.perfect_match_top_k = perfect_match_top_k  # Check top K candidates for perfect match
        
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
                    "name": "search_by_category",
                    "description": "Search viewpoints by category using SQL. Categories: mountain, lake, temple, museum, park, coast, cityscape, monument, bridge, palace, tower, cave, waterfall, valley, island. If the query intent includes a country (geo_hints.country), ALWAYS use the country parameter to filter results.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["mountain", "lake", "temple", "museum", "park", "coast", "cityscape", "monument", "bridge", "palace", "tower", "cave", "waterfall", "valley", "island"],
                                "description": "Category to search for"
                            },
                            "country": {
                                "type": "string",
                                "description": "Optional country name to filter results (e.g., 'China', 'France', 'United States'). Use this when the user query mentions a specific country or location. Common country names: China, United States, France, Italy, Japan, etc."
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
                    "description": "Search viewpoints by tags using SQL. Tags may include category tags, visual tags, and scene tags. This searches the viewpoint_visual_tags table.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of tags to search for (e.g., ['snow_peak', 'snowy'], ['cityscape', 'panoramic'])"
                            },
                            "season": {
                                "type": "string",
                                "enum": ["spring", "summer", "autumn", "winter", "unknown"],
                                "description": "Optional season filter to narrow down results",
                                "default": "unknown"
                            },
                            "tag_sources": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional tag sources to filter (e.g., ['wiki_weak_supervision', 'gpt_4o_mini_image_history'])"
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
                    "name": "search_by_history_terms",
                    "description": "Search viewpoints by matching keywords in historical/Wikipedia text. Use this when the query asks for history, legends, heritage, or when you need related results based on narrative terms.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "terms": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of keywords or phrases to search in history text (free text, not restricted to tag vocabulary)"
                            },
                            "top_n": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 50
                            }
                        },
                        "required": ["terms"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_with_llm_sql",
                    "description": "Search viewpoints using LLM-generated SQL query. This is a flexible search method that uses AI to generate optimized SQL queries based on query intent. Use this for complex queries that combine multiple criteria (name, category, tags, country, season). The LLM will generate the most appropriate SQL query automatically.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query_intent": {
                                "type": "object",
                                "description": "Query intent object from extract_query_intent. Should include name_candidates, query_tags, season_hint, and geo_hints.",
                                "properties": {
                                    "name_candidates": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "List of place names to search for"
                                    },
                                    "query_tags": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "List of category or visual tags"
                                    },
                                    "season_hint": {
                                        "type": "string",
                                        "enum": ["spring", "summer", "autumn", "winter", "unknown"],
                                        "description": "Season preference"
                                    },
                                    "geo_hints": {
                                        "type": "object",
                                        "properties": {
                                            "place_name": {"type": "string"},
                                            "country": {"type": "string"}
                                        }
                                    }
                                }
                            },
                            "top_n": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 50
                            }
                        },
                        "required": ["query_intent"]
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
    
    def _get_msg_attr(self, msg: Any, attr: str, default: Any = None) -> Any:
        """
        Safely get attribute from message, handling both dict and Pydantic objects.
        
        Args:
            msg: Message object (dict or Pydantic model)
            attr: Attribute name to get
            default: Default value if attribute doesn't exist
            
        Returns:
            Attribute value or default
        """
        if isinstance(msg, dict):
            return msg.get(attr, default)
        else:
            # Pydantic model or other object
            return getattr(msg, attr, default)
    
    def _evaluate_search_quality(self, tool_calls_log: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluate the quality of search results to determine if we should continue searching.
        
        Returns:
            Dict with 'should_continue' (bool) and 'reason' (str)
        """
        # Get all search results
        search_results = []
        for tc in tool_calls_log:
            tool_name = tc.get("tool")
            result = tc.get("result", {})
            
            # Check search tools
            if tool_name in ["search_with_llm_sql", "search_by_category", 
                            "search_by_tags", "search_by_history_terms"]:
                if isinstance(result, dict):
                    candidates = result.get("candidates", [])
                    count = result.get("count", 0)
                    if count > 0 and candidates:
                        search_results.append({
                            "count": count,
                            "candidates": candidates[:5]  # Top 5
                        })
            
            # Also check rank_and_explain_results - it contains candidates with scores
            elif tool_name == "rank_and_explain_results":
                if isinstance(result, dict):
                    # rank_and_explain_results returns both "results" and "candidates"
                    candidates = result.get("candidates", [])  # Original candidates with scores
                    if not candidates:
                        # Fallback to "results" if candidates not available
                        results = result.get("results", [])
                        # Convert ViewpointResult to candidate format (if needed)
                        candidates = [{"viewpoint_id": r.get("viewpoint_id"), 
                                      "name_score": 1.0 if r.get("match_confidence", 0) > 0.9 else 0.5,
                                      "geo_score": 1.0,
                                      "category_score": 1.0} 
                                     for r in results[:5]]
                    
                    if candidates:
                        search_results.append({
                            "count": len(candidates),
                            "candidates": candidates[:5]  # Top 5
                        })
        
        if not search_results:
            return {
                "should_continue": True,
                "quality": "poor",
                "reason": "No search results found yet"
            }
        
        # Check if we have high-quality matches
        best_result = max(search_results, key=lambda x: x["count"])
        candidates = best_result.get("candidates", [])
        
        if not candidates:
            return {
                "should_continue": True,
                "quality": "poor",
                "reason": "Search returned count > 0 but no candidates"
            }
        
        # Evaluate top candidates
        top_candidate = candidates[0] if candidates else {}
        name_score = top_candidate.get("name_score", 0.0)
        geo_score = top_candidate.get("geo_score", 0.0)
        category_score = top_candidate.get("category_score", 0.0)
        
        # High quality indicators:
        # 1. Perfect match (name_score = 1.0 in top K candidates) - can stop immediately
        # 2. Very high match (name_score > 0.8) - can stop with 1 method
        # 3. High match (name_score > 0.5) - need 2+ methods
        # 4. Multiple candidates with good scores
        
        # Check top K candidates for perfect match (name_score >= 1.0)
        top_k_candidates = candidates[:self.perfect_match_top_k]
        has_perfect_match = any(c.get("name_score", 0.0) >= 1.0 for c in top_k_candidates)
        perfect_match_candidate = next((c for c in top_k_candidates if c.get("name_score", 0.0) >= 1.0), None)
        perfect_match_score = perfect_match_candidate.get("name_score", 0.0) if perfect_match_candidate else 0.0
        
        has_very_high_match = name_score > 0.8
        has_high_name_match = name_score > 0.5
        has_multiple_good_candidates = len([c for c in candidates[:3] 
                                           if c.get("name_score", 0) > 0.3 or 
                                              c.get("geo_score", 0) > 0.5]) >= 2
        
        # Count search methods tried
        search_methods_tried = len(set(tc.get("tool") for tc in tool_calls_log 
                                       if tc.get("tool") in ["search_with_llm_sql", 
                                                             "search_by_category", "search_by_tags", 
                                                             "search_by_history_terms"]))
        
        # Perfect match - stop immediately regardless of methods tried
        # Perfect match means name_score >= 1.0 in top K candidates
        if has_perfect_match:
            return {
                "should_continue": False,
                "quality": "perfect",
                "reason": f"Found perfect match (name_score={perfect_match_score:.2f}) in top {self.perfect_match_top_k} candidates - no need to continue"
            }
        
        # Very high match - can stop with just 1 method
        if has_very_high_match:
            return {
                "should_continue": False,
                "quality": "very_high",
                "reason": f"Found very high-quality match (name_score={name_score:.2f}) - confident result"
            }
        
        # High match - need at least 2 methods for confidence
        if has_high_name_match and search_methods_tried >= 2:
            return {
                "should_continue": False,
                "quality": "high",
                "reason": f"Found high-quality match (name_score={name_score:.2f}) with {search_methods_tried} search methods"
            }
        
        # Multiple good candidates - need at least 2 methods
        if has_multiple_good_candidates and search_methods_tried >= 2:
            return {
                "should_continue": False,
                "quality": "good",
                "reason": f"Found multiple good candidates with {search_methods_tried} search methods"
            }
        
        # If we have some results but low scores, continue to find better
        if name_score < 0.3 and geo_score < 0.3:
            return {
                "should_continue": True,
                "quality": "low",
                "reason": f"Results have low match scores (name={name_score:.2f}, geo={geo_score:.2f})"
            }
        
        # If we have high match but only 1 method, try one more to be sure
        if has_high_name_match and search_methods_tried < 2:
            return {
                "should_continue": True,
                "quality": "moderate",
                "reason": f"Found good match (name_score={name_score:.2f}) but only tried {search_methods_tried} method(s) - try one more to verify"
            }
        
        # If we have moderate results and tried multiple methods, can stop
        if search_methods_tried >= 2:
            return {
                "should_continue": False,
                "quality": "moderate",
                "reason": f"Found moderate results (name_score={name_score:.2f}) with {search_methods_tried} search methods"
            }
        
        # Default: continue if we haven't tried enough methods
        return {
            "should_continue": True,
            "quality": "moderate",
            "reason": f"Only tried {search_methods_tried} search method(s) with moderate results (name_score={name_score:.2f}) - should explore more"
        }
    
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
                "content": f"""You are a helpful assistant for a tourist attraction search system (TourRAG).

Your job is to help users find information about tourist attractions and viewpoints using SQL-based search tools.

You have access to SQL-based MCP tools:
1. extract_query_intent - Extract structured intent from user text (use this first)
2. search_with_llm_sql - **RECOMMENDED**: Search using LLM-generated SQL (handles name, category, country, season, and tags automatically)
3. search_by_category - Search by category using SQL (mountain, lake, temple, etc.)
4. search_by_tags - Search by visual tags using SQL (snow_peak, cherry_blossom, etc.)
5. search_by_history_terms - Search by historical/Wikipedia text using keywords
6. search_popular - Get popular viewpoints using SQL (ONLY use as fallback if user explicitly asks for popular places)
7. get_viewpoint_details - Get detailed info about a specific viewpoint
8. rank_and_explain_results - Rank and explain search results

IMPORTANT: You have {max_iterations} iterations to find the best answer. Use them wisely!

Iterative Search Strategy:
1. **First iteration**: Extract query intent and try search_with_llm_sql (it handles names, categories, countries, and tags automatically)
2. **Subsequent iterations**: If results are not ideal, try alternative search strategies:
   - If search_with_llm_sql returned 0 results → try search_by_category with country filter
   - If category search failed → try search_by_history_terms with keywords from the query
   - If you found some candidates but they don't match well → try rank_and_explain_results to re-evaluate
   - Try different name variations in search_with_llm_sql (it will handle name matching)
   - Try broader category searches, then narrow down
   - Try searching by related terms or synonyms using search_by_history_terms
3. **Quality Check**: After each search, evaluate:
   - Did I find results? (check "count" field)
   - Do the results match the query intent? (check names, categories, locations)
   - Are the match scores high? (name_score > 0.5 indicates good match)
   - Should I try a different search strategy?
4. **When to stop IMMEDIATELY**: You MUST stop and provide the final answer if:
   - Search result contains "_stop_signal": true - this means PERFECT or VERY HIGH match found, STOP NOW!
   - Search result "_note" says "PERFECT MATCH FOUND" or "VERY HIGH MATCH FOUND" - STOP immediately!
   - You found a PERFECT match (name_score = 1.0) - this means exact name match, no need to continue!
   - You found a VERY HIGH match (name_score > 0.8) - this is highly confident, stop now!
   - The system tells you "Quality check: Found perfect/very high match" - STOP immediately!
   - **CRITICAL**: When you see _stop_signal in tool results, DO NOT call any more search tools - just get_viewpoint_details if needed, then provide final answer!
5. **When to stop after verification**: You can stop if:
   - You found high-quality matches (name_score > 0.5) with multiple search methods (2+)
   - You have multiple good candidates and tried at least 2 different search methods
   - You're confident the results match the query well
6. **When to continue**: Keep searching ONLY if:
   - No results found (count = 0)
   - Low match scores (name_score < 0.3)
   - The system explicitly tells you to continue searching
   - Results don't seem to match the query intent well

Use these SQL-based tools strategically:
1. First, extract query intent to understand what the user wants
2. **PREFERRED**: Use search_with_llm_sql for ALL queries. This tool uses AI to generate optimized SQL queries automatically and handles:
   - Name matching (name_candidates)
   - Category filtering
   - Country filtering (geo_hints.country)
   - Season filtering
   - Visual tags
   - Combined criteria
3. For specialized searches, use specific tools:
   - If only categories → use search_by_category
     **CRITICAL: If geo_hints.country is present in query_intent, ALWAYS pass the country parameter to search_by_category**
   - If only visual tags → use search_by_tags
   - If searching for historical/legendary information → use search_by_history_terms
4. IMPORTANT: If search_with_llm_sql returns 0 results (check the "count" field), try alternative strategies:
   - Try search_by_category if a category is mentioned
   - Try search_by_history_terms with keywords from the query
   - Try different name variations in search_with_llm_sql (it handles name matching automatically)
   - DO NOT immediately give up - use your remaining iterations to explore
5. IMPORTANT: When user query mentions a country (e.g., "纪念中国" means "commemorating China"), you MUST use the country parameter in search_by_category to filter results by that country.
6. If the user asks about history/legends/heritage or you need related results, use search_by_history_terms with keyword terms
7. Get details for promising candidates (use get_viewpoint_details)
8. Rank and explain results (use rank_and_explain_results) - this can help you find better matches
9. Synthesize a helpful answer only when you're confident you've found the best match

CRITICAL RULES:
- Never use search_popular as a fallback when a specific location search returns no results
- Always check the "count" field in search results. If count is 0, try alternative search strategies before giving up
- ALWAYS use the country parameter when geo_hints.country is present in query_intent
- Use ALL available iterations to explore different search strategies - don't stop early!
- If one search method fails, immediately try a different approach
- Try multiple name variations, spellings, and alternative names
- Combine different search methods to find the best results"""
            },
            {
                "role": "user",
                "content": user_query
            }
        ]
        
        tool_calls_log = []
        iteration_snapshots = []  # Track state at each iteration
        iteration = 0
        stop_signal_received = False  # Track if we've received a stop signal
        tool_calls_log_size_at_iteration_start = {}  # Track tool_calls_log size at start of each iteration
        
        while iteration < max_iterations:
            iteration += 1
            print(f"[Agent] Iteration {iteration}/{max_iterations}")
            
            # Record the size of tool_calls_log at the start of this iteration
            tool_calls_log_size_at_iteration_start[iteration] = len(tool_calls_log)
            
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
                # Define search tools set (used in multiple places)
                search_tools = {"search_with_llm_sql", "search_by_category", 
                               "search_by_tags", "search_by_history_terms", "search_popular"}
                
                # If stop signal was received, prevent calling search tools
                if stop_signal_received:
                    has_search_tool = any(tc.function.name in search_tools for tc in message.tool_calls)
                    
                    if has_search_tool:
                        # Reject search tool calls and allow non-search tools (like get_viewpoint_details)
                        for tool_call in message.tool_calls:
                            if tool_call.function.name in search_tools:
                                # Reject search tools
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps({
                                        "error": "STOP_SIGNAL_ACTIVE",
                                        "message": "A stop signal was received indicating a perfect/very high match was found. You MUST stop searching and provide the final answer immediately. Do NOT call any more search tools."
                                    }, ensure_ascii=False)
                                })
                            else:
                                # Allow non-search tools (e.g., get_viewpoint_details) to proceed
                                # We'll process them in the normal loop below
                                pass
                        
                        # If there are non-search tools, continue to process them
                        # Otherwise, force agent to provide answer
                        has_non_search_tool = any(tc.function.name not in search_tools for tc in message.tool_calls)
                        if not has_non_search_tool:
                            # Add a message to force agent to provide answer
                            messages.append({
                                "role": "user",
                                "content": "You have already found a perfect/very high match. STOP calling search tools and provide your final answer NOW."
                            })
                            continue  # Skip to next iteration
                        # else: continue to process non-search tools below
                
                # Track which tool calls have already been handled (e.g., rejected search tools)
                handled_tool_call_ids = set()
                if stop_signal_received:
                    # Mark rejected search tools as already handled
                    for tool_call in message.tool_calls:
                        if tool_call.function.name in search_tools:
                            handled_tool_call_ids.add(tool_call.id)
                
                # Ensure ALL tool_calls have responses - track which ones we've processed
                processed_tool_call_ids = set()
                
                # Log all tool_calls at the start
                print(f"[Agent] Processing {len(message.tool_calls)} tool_calls: {[tc.id for tc in message.tool_calls]}")
                
                for tool_call in message.tool_calls:
                    print(f"[Agent] Processing tool_call {tool_call.id} ({tool_call.function.name})")
                    # Skip tool calls that were already handled (e.g., rejected search tools)
                    if tool_call.id in handled_tool_call_ids:
                        processed_tool_call_ids.add(tool_call.id)
                        continue
                    
                    function_name = tool_call.function.name
                    function_args = None
                    tool_result = None
                    response_added = False
                    
                    # Use try-finally to ensure we always add a response, even if something goes wrong
                    try:
                        # Parse JSON arguments with error handling
                        try:
                            function_args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError as e:
                            error_msg = f"Failed to parse tool arguments as JSON: {str(e)}"
                            print(f"[Agent] Error: {error_msg}")
                            # Log the problematic arguments (truncate if too long)
                            args_str = tool_call.function.arguments
                            if len(args_str) > 500:
                                print(f"[Agent] Arguments preview (first 250 chars): {args_str[:250]}...")
                                print(f"[Agent] Arguments preview (last 250 chars): ...{args_str[-250:]}")
                            else:
                                print(f"[Agent] Arguments: {args_str}")
                            
                            # Return error to LLM so it can retry
                            tool_result = {
                                "error": error_msg,
                                "message": "The tool call arguments were invalid JSON. Please retry with properly formatted JSON."
                            }
                            # Add tool result to messages immediately
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(tool_result, ensure_ascii=False)
                            })
                            processed_tool_call_ids.add(tool_call.id)
                            response_added = True
                            continue
                        
                        print(f"[Agent] Calling tool: {function_name} with args: {function_args}")
                        
                        # Execute the tool with error handling
                        try:
                            tool_result = await self._execute_tool(function_name, function_args)
                        except Exception as e:
                            # If tool execution fails, return error response
                            error_msg = f"Tool execution failed: {str(e)}"
                            print(f"[Agent] Error: {error_msg}")
                            tool_result = {
                                "error": error_msg,
                                "message": f"An error occurred while executing {function_name}. Please try a different approach."
                            }
                        
                        # Check search result quality and add signals
                        if isinstance(tool_result, dict):
                            result_count = tool_result.get("count", 0)
                            candidates = tool_result.get("candidates", [])
                            
                            # Check for perfect match in search results (check top K candidates)
                            if result_count > 0 and candidates:
                                top_k_candidates = candidates[:self.perfect_match_top_k]
                                # Check if any candidate in top K has perfect match (name_score >= 1.0)
                                perfect_match_candidate = next((c for c in top_k_candidates if c.get("name_score", 0.0) >= 1.0), None)
                                
                                if perfect_match_candidate:
                                    # Perfect match found in top K - add strong stop signal
                                    perfect_score = perfect_match_candidate.get("name_score", 0.0)
                                    tool_result["_stop_signal"] = True
                                    tool_result["_note"] = f"PERFECT MATCH FOUND (name_score={perfect_score:.2f}) in top {self.perfect_match_top_k} candidates! You should STOP searching and provide the final answer immediately. No need to continue searching."
                                else:
                                    # Check top candidate for very high match
                                    top_candidate = candidates[0]
                                    name_score = top_candidate.get("name_score", 0.0)
                                    
                                    # Very high match - add stop signal
                                    if name_score > 0.8:
                                        tool_result["_stop_signal"] = True
                                        tool_result["_note"] = f"VERY HIGH MATCH FOUND (name_score={name_score:.2f})! You should STOP searching and provide the final answer. This is highly confident."
                            
                            # No results - suggest alternatives
                            elif result_count == 0 and iteration < max_iterations:
                                # Add a helpful hint for the agent
                                search_type = function_name
                                suggestions = []
                                
                                if search_type == "search_with_llm_sql":
                                    suggestions = [
                                        "Try search_with_llm_sql again with different name variations from query_intent",
                                        "Try search_by_category with country filter",
                                        "Try search_by_history_terms with related keywords",
                                        "Try broader search criteria or remove some filters"
                                    ]
                                elif search_type == "search_by_category":
                                    suggestions = [
                                        "Try removing the country filter to search globally",
                                        "Try search_with_llm_sql with name_candidates from query_intent",
                                        "Try search_by_history_terms with keywords",
                                        "Try a different category"
                                    ]
                                
                                if suggestions:
                                    tool_result["_suggestions"] = suggestions
                                    tool_result["_note"] = f"No results found. You have {max_iterations - iteration} more iterations. Consider trying alternative search strategies."
                        
                        # Ensure we have a valid tool_result (should never be None at this point)
                        if tool_result is None:
                            tool_result = {
                                "error": "Unknown error",
                                "message": f"Tool {function_name} returned no result. Please try again."
                            }
                        
                        # Add tool result to messages - CRITICAL: Every tool_call MUST have a response
                        # Use try-except to ensure we always add a response, even if serialization fails
                        try:
                            response_content = json.dumps(tool_result, ensure_ascii=False)
                            response_msg = {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": response_content
                            }
                            messages.append(response_msg)
                            processed_tool_call_ids.add(tool_call.id)
                            response_added = True
                            
                            # Verify the response was actually added to messages
                            # Check the last few messages to ensure our response is there
                            response_found = False
                            for msg in messages[-5:]:  # Check last 5 messages
                                if (self._get_msg_attr(msg, "role") == "tool" and 
                                    self._get_msg_attr(msg, "tool_call_id") == tool_call.id):
                                    response_found = True
                                    break
                            
                            if not response_found:
                                print(f"[Agent] WARNING: Response for {tool_call.id} was not found in messages after append!")
                                # Try to add it again
                                messages.append(response_msg)
                                print(f"[Agent] Re-added response for {tool_call.id}")
                            
                            print(f"[Agent] Successfully added response for tool_call {tool_call.id}")
                        except Exception as e:
                            # If serialization fails, add an error response instead
                            print(f"[Agent] ERROR: Failed to serialize tool result for {tool_call.id}: {str(e)}")
                            try:
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps({
                                        "error": "Serialization error",
                                        "message": f"Failed to serialize tool result: {str(e)}"
                                    }, ensure_ascii=False)
                                })
                                processed_tool_call_ids.add(tool_call.id)
                                response_added = True
                            except Exception as e2:
                                # Last resort: add a simple error message
                                print(f"[Agent] CRITICAL ERROR: Failed to add error response for {tool_call.id}: {str(e2)}")
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": '{"error": "Critical serialization error", "message": "Tool result could not be serialized"}'
                                })
                                processed_tool_call_ids.add(tool_call.id)
                                response_added = True
                        
                        # Log tool call (this should not affect response message addition)
                        try:
                            tool_calls_log.append({
                                "tool": function_name,
                                "arguments": function_args,
                                "result": tool_result
                            })
                        except Exception as e:
                            # Log error but don't fail - response message already added
                            print(f"[Agent] WARNING: Failed to log tool call: {str(e)}")
                        
                        # Check for stop signal in tool result
                        if isinstance(tool_result, dict) and tool_result.get("_stop_signal"):
                            # Perfect or very high match found - set stop signal flag
                            stop_signal_received = True
                            stop_note = tool_result.get("_note", "Perfect match found - stop searching")
                            messages.append({
                                "role": "assistant",
                                "content": f"STOP SIGNAL RECEIVED: {stop_note}. You MUST stop searching now and provide the final answer immediately. Do NOT call any more search tools."
                            })
                            # Force agent to provide final answer in next iteration
                            messages.append({
                                "role": "user",
                                "content": "You have found a PERFECT or VERY HIGH match. You MUST provide your final answer NOW. Do not call any more tools - just provide the answer based on the information you already have."
                            })
                    except Exception as e:
                        # If any unexpected error occurs, ensure we still add a response
                        print(f"[Agent] UNEXPECTED ERROR processing tool_call {tool_call.id}: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        if not response_added:
                            try:
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps({
                                        "error": "Unexpected error",
                                        "message": f"An unexpected error occurred: {str(e)}"
                                    }, ensure_ascii=False)
                                })
                                processed_tool_call_ids.add(tool_call.id)
                                response_added = True
                            except Exception as e2:
                                print(f"[Agent] FATAL: Could not add error response for {tool_call.id}: {str(e2)}")
                    finally:
                        # Final safety check: ensure response was added
                        # Verify the response exists in messages before marking as processed
                        response_exists = False
                        for msg in messages:
                            if (self._get_msg_attr(msg, "role") == "tool" and 
                                self._get_msg_attr(msg, "tool_call_id") == tool_call.id):
                                response_exists = True
                                break
                        
                        if not response_exists:
                            print(f"[Agent] FINALLY: Response for {tool_call.id} not found in messages, adding safety response")
                            try:
                                safety_response = {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": json.dumps({
                                        "error": "Processing incomplete",
                                        "message": "Tool call processing did not complete successfully."
                                    }, ensure_ascii=False)
                                }
                                messages.append(safety_response)
                                processed_tool_call_ids.add(tool_call.id)
                                response_added = True
                                
                                # Verify it was actually added
                                response_verified = False
                                for msg in messages[-3:]:  # Check last 3 messages
                                    if (self._get_msg_attr(msg, "role") == "tool" and 
                                        self._get_msg_attr(msg, "tool_call_id") == tool_call.id):
                                        response_verified = True
                                        break
                                
                                if not response_verified:
                                    print(f"[Agent] FATAL: Safety response for {tool_call.id} was not added to messages!")
                                    # Try one more time with a simpler message
                                    try:
                                        messages.append({
                                            "role": "tool",
                                            "tool_call_id": tool_call.id,
                                            "content": '{"error": "Critical error", "message": "Tool call failed"}'
                                        })
                                    except Exception as e3:
                                        print(f"[Agent] FATAL: Could not add any response for {tool_call.id}: {str(e3)}")
                                        raise RuntimeError(f"Failed to add response for tool_call_id {tool_call.id}")
                                else:
                                    print(f"[Agent] FINALLY: Successfully added safety response for {tool_call.id}")
                            except Exception as e:
                                print(f"[Agent] FATAL: Could not add final safety response for {tool_call.id}: {str(e)}")
                                # Last resort: raise an error to prevent API call with missing response
                                raise RuntimeError(f"Failed to add response for tool_call_id {tool_call.id}: {str(e)}")
                        elif not response_added:
                            # Response exists but wasn't marked as added - mark it now
                            processed_tool_call_ids.add(tool_call.id)
                            response_added = True
                            print(f"[Agent] FINALLY: Found existing response for {tool_call.id}, marked as processed")
                
                # CRITICAL: Verify that ALL tool_calls have been processed and have responses
                all_tool_call_ids = {tc.id for tc in message.tool_calls}
                missing_responses = all_tool_call_ids - processed_tool_call_ids - handled_tool_call_ids
                print(f"[Agent] Verification: all_tool_call_ids={all_tool_call_ids}, processed={processed_tool_call_ids}, handled={handled_tool_call_ids}, missing={missing_responses}")
                if missing_responses:
                    # This should never happen, but if it does, add error responses for missing tool_calls
                    print(f"[Agent] WARNING: Some tool_calls did not get responses: {missing_responses}")
                    print(f"[Agent] All tool_call_ids: {all_tool_call_ids}")
                    print(f"[Agent] Processed tool_call_ids: {processed_tool_call_ids}")
                    print(f"[Agent] Handled tool_call_ids: {handled_tool_call_ids}")
                    for tool_call_id in missing_responses:
                        try:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": json.dumps({
                                    "error": "INTERNAL_ERROR",
                                    "message": "Tool call was not properly processed. Please retry."
                                }, ensure_ascii=False)
                            })
                            print(f"[Agent] Added error response for missing tool_call_id: {tool_call_id}")
                        except Exception as e:
                            print(f"[Agent] CRITICAL: Failed to add error response for {tool_call_id}: {str(e)}")
                            # Last resort: try to add a simple string response
                            try:
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "content": '{"error": "INTERNAL_ERROR", "message": "Tool call processing failed"}'
                                })
                            except Exception as e2:
                                print(f"[Agent] FATAL: Could not add any response for {tool_call_id}: {str(e2)}")
                
                # FINAL VERIFICATION: Before calling OpenAI API, verify all tool_call_ids have responses in messages
                # This is a critical check to prevent API errors
                tool_call_ids_in_messages = set()
                for msg in messages:
                    if (self._get_msg_attr(msg, "role") == "tool" and 
                        self._get_msg_attr(msg, "tool_call_id") is not None):
                        tool_call_ids_in_messages.add(self._get_msg_attr(msg, "tool_call_id"))
                
                # Check if all tool_call_ids from the last assistant message have responses
                last_assistant_msg = None
                for msg in reversed(messages):
                    if (self._get_msg_attr(msg, "role") == "assistant" and 
                        self._get_msg_attr(msg, "tool_calls") is not None):
                        last_assistant_msg = msg
                        break
                
                if last_assistant_msg:
                    tool_calls = self._get_msg_attr(last_assistant_msg, "tool_calls", [])
                    # Handle both list of dicts and list of objects
                    if tool_calls:
                        if isinstance(tool_calls[0], dict):
                            required_tool_call_ids = {tc["id"] for tc in tool_calls}
                        else:
                            required_tool_call_ids = {getattr(tc, "id", None) for tc in tool_calls if hasattr(tc, "id")}
                    else:
                        required_tool_call_ids = set()
                    missing_in_messages = required_tool_call_ids - tool_call_ids_in_messages
                    if missing_in_messages:
                        print(f"[Agent] CRITICAL: Found tool_call_ids without responses in messages: {missing_in_messages}")
                        print(f"[Agent] Required tool_call_ids: {required_tool_call_ids}")
                        print(f"[Agent] Tool_call_ids in messages: {tool_call_ids_in_messages}")
                        # Add missing responses immediately
                        for tool_call_id in missing_in_messages:
                            try:
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "content": json.dumps({
                                        "error": "MISSING_RESPONSE",
                                        "message": "Tool call response was not properly added. This is an internal error."
                                    }, ensure_ascii=False)
                                })
                                print(f"[Agent] Added missing response for tool_call_id: {tool_call_id}")
                            except Exception as e:
                                print(f"[Agent] FATAL: Could not add missing response for {tool_call_id}: {str(e)}")
                                # This is a critical error - we cannot proceed without all responses
                                raise RuntimeError(f"Failed to add response for tool_call_id {tool_call_id}: {str(e)}")
                
                # Save snapshot of current state at this iteration
                # Only include tool calls from this iteration (not cumulative)
                start_idx = tool_calls_log_size_at_iteration_start.get(iteration, 0)
                current_iteration_tool_calls = tool_calls_log[start_idx:].copy()
                
                iteration_snapshots.append({
                    "iteration": iteration,
                    "tool_calls": current_iteration_tool_calls  # Only current iteration's tool calls
                })
                
                # Evaluate search quality to decide if we should continue
                if iteration < max_iterations:
                    quality_eval = self._evaluate_search_quality(tool_calls_log)
                    should_continue = quality_eval.get("should_continue", True)
                    quality = quality_eval.get("quality", "unknown")
                    reason = quality_eval.get("reason", "")
                    
                    if not should_continue:
                        # High quality results found - strongly encourage agent to finalize
                        if quality in ["perfect", "very_high"]:
                            # Perfect or very high match found - force immediate stop
                            print(f"[Agent] Quality check: {reason} - Found perfect/very high match, forcing immediate stop")
                            messages.append({
                                "role": "assistant",
                                "content": f"Quality check: {reason}. You have found EXCELLENT results! "
                                          f"You MUST STOP searching and provide the final answer NOW. "
                                          f"Do NOT call any more search tools."
                            })
                            # Force agent to provide final answer immediately - skip to next iteration
                            messages.append({
                                "role": "user",
                                "content": "You have found a PERFECT or VERY HIGH match. You MUST provide your final answer immediately. Do not call any more tools - just provide the answer based on the information you already have."
                            })
                            # Continue to next iteration to get final answer (will break if agent provides answer)
                            continue
                        else:
                            messages.append({
                                "role": "assistant",
                                "content": f"Quality check: {reason}. You have found good results. "
                                          f"You can proceed to get_viewpoint_details and provide the final answer, "
                                          f"or use rank_and_explain_results to refine if needed."
                            })
                    else:
                        # Need to continue searching
                        if quality == "poor":
                            messages.append({
                                "role": "assistant",
                                "content": f"Quality check: {reason}. You have {max_iterations - iteration} more iterations. "
                                          f"Try different strategies:\n"
                                          f"- Different name variations or spellings\n"
                                          f"- Alternative search methods (search_by_category, search_by_history_terms)\n"
                                          f"- Broader search criteria\n"
                                          f"- Partial name matches"
                            })
                        elif quality == "low":
                            messages.append({
                                "role": "assistant",
                                "content": f"Quality check: {reason}. You have {max_iterations - iteration} more iterations. "
                                          f"Try to find better matches:\n"
                                          f"- Try alternative search methods\n"
                                          f"- Use different name variations\n"
                                          f"- Try broader or different search criteria"
                            })
                        elif quality == "moderate":
                            messages.append({
                                "role": "assistant",
                                "content": f"Quality check: {reason}. You have {max_iterations - iteration} more iterations. "
                                          f"Consider:\n"
                                          f"- Trying one more alternative search method\n"
                                          f"- Using rank_and_explain_results to evaluate current candidates\n"
                                          f"- Getting more details on promising candidates"
                            })
            else:
                # Model wants to return final answer
                final_answer = message.content
                
                # Check if we found a good match - if so, stop immediately
                quality_eval = self._evaluate_search_quality(tool_calls_log)
                should_continue = quality_eval.get("should_continue", True)
                quality = quality_eval.get("quality", "unknown")
                reason = quality_eval.get("reason", "")
                
                # If agent provides final answer and we found a good match, stop immediately
                # This ensures agent stops as soon as it thinks it found the target
                if not should_continue or quality in ["perfect", "very_high", "high", "good"]:
                    # Good match found and agent provided answer - stop immediately
                    print(f"[Agent] Agent provided final answer with quality: {quality} - {reason} - Stopping immediately")
                    # Save final snapshot before breaking (this iteration found the answer)
                    start_idx = tool_calls_log_size_at_iteration_start.get(iteration, 0)
                    current_iteration_tool_calls = tool_calls_log[start_idx:].copy()
                    
                    iteration_snapshots.append({
                        "iteration": iteration,
                        "tool_calls": current_iteration_tool_calls,
                        "final": True
                    })
                    # Accept the answer and break immediately
                    return {
                        "answer": final_answer,
                        "tool_calls": tool_calls_log,
                        "iterations": iteration,
                        "iteration_snapshots": iteration_snapshots
                    }
                
                # Evaluate if we should accept this answer or continue
                if iteration < max_iterations:
                    # If quality is perfect or very high, accept immediately and stop
                    if not should_continue and quality in ["perfect", "very_high"]:
                        # Perfect or very high match found - accept answer immediately and break loop
                        print(f"[Agent] Quality check: {reason} - Accepting answer immediately and stopping")
                        # Save final snapshot before breaking (this iteration found the answer)
                        start_idx = tool_calls_log_size_at_iteration_start.get(iteration, 0)
                        current_iteration_tool_calls = tool_calls_log[start_idx:].copy()
                        
                        iteration_snapshots.append({
                            "iteration": iteration,
                            "tool_calls": current_iteration_tool_calls,
                            "final": True
                        })
                        # Don't add any messages, just accept the answer and break
                        # Break out of the while loop to stop iterations
                        break
                    elif should_continue and quality in ["poor", "low"]:
                        # Results are not good enough - encourage agent to continue searching
                        messages.append({
                            "role": "assistant",
                            "content": final_answer
                        })
                        messages.append({
                            "role": "user",
                            "content": f"Quality check: {reason}. You have {max_iterations - iteration} more iterations. "
                                      f"Please continue searching with different strategies:\n"
                                      f"1. Try alternative name spellings or variations\n"
                                      f"2. Try search_by_category if a category is mentioned\n"
                                      f"3. Try search_by_history_terms with keywords from the query\n"
                                      f"4. Try broader search criteria\n"
                                      f"5. Check if you're using the country parameter correctly\n"
                                      f"Don't give up - continue searching to find better results!"
                        })
                        continue  # Continue to next iteration
                    elif should_continue and quality == "moderate" and iteration < max_iterations - 1:
                        # Moderate results - suggest one more iteration to verify, but allow stopping
                        messages.append({
                            "role": "assistant",
                            "content": final_answer
                        })
                        messages.append({
                            "role": "user",
                            "content": f"Quality check: {reason}. You have {max_iterations - iteration} more iterations. "
                                      f"If you're confident with current results, you can proceed with the answer. "
                                      f"Otherwise, consider trying one more search method or using rank_and_explain_results "
                                      f"to verify these are the best matches."
                        })
                        continue  # Continue to next iteration
                    # else: quality is "high" or "good" or "perfect" or "very_high" - accept the answer and stop
                
                # Final answer - save and return
                print(f"[Agent] Final answer: {final_answer[:200]}...")
                
                # Save final snapshot
                # Only include tool calls from this iteration
                start_idx = tool_calls_log_size_at_iteration_start.get(iteration, 0)
                current_iteration_tool_calls = tool_calls_log[start_idx:].copy()
                
                iteration_snapshots.append({
                    "iteration": iteration,
                    "tool_calls": current_iteration_tool_calls,
                    "final": True
                })
                
                return {
                    "answer": final_answer,
                    "tool_calls": tool_calls_log,
                    "iterations": iteration,
                    "iteration_snapshots": iteration_snapshots
                }
        
        # Max iterations reached
        # Save final snapshot
        # Only include tool calls from this iteration
        start_idx = tool_calls_log_size_at_iteration_start.get(iteration, 0)
        current_iteration_tool_calls = tool_calls_log[start_idx:].copy()
        
        iteration_snapshots.append({
            "iteration": iteration,
            "tool_calls": current_iteration_tool_calls,
            "final": True,
            "max_iterations_reached": True
        })
        
        return {
            "answer": "I've reached the maximum number of iterations. Please try rephrasing your query.",
            "tool_calls": tool_calls_log,
            "iterations": iteration,
            "error": "max_iterations_reached",
            "iteration_snapshots": iteration_snapshots
        }
    
    def _sync_execute_rank_and_explain(
        self,
        candidates: List[Dict[str, Any]],
        query_intent_dict: Dict[str, Any],
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """Rank candidates and return explanations using the shared LLM service."""
        if query_intent_dict is None:
            query_intent_dict = {}
        if not isinstance(query_intent_dict, dict):
            query_intent_dict = {}

        from app.schemas.query import QueryIntent, GeoHints, ViewpointCandidate
        geo_hints_dict = query_intent_dict.get("geo_hints", {})
        if not isinstance(geo_hints_dict, dict):
            geo_hints_dict = {}

        query_intent = QueryIntent(
            name_candidates=query_intent_dict.get("name_candidates", []),
            query_tags=query_intent_dict.get("query_tags", []),
            season_hint=query_intent_dict.get("season_hint", "unknown"),
            scene_hints=query_intent_dict.get("scene_hints", []),
            geo_hints=GeoHints(
                place_name=geo_hints_dict.get("place_name"),
                country=geo_hints_dict.get("country"),
            ),
            confidence_notes=query_intent_dict.get("confidence_notes", []),
        )

        candidate_objects = []
        for c in candidates:
            candidate_objects.append(ViewpointCandidate(
                viewpoint_id=c["viewpoint_id"],
                name_primary=c["name_primary"],
                name_variants=c.get("name_variants", {}),
                category_norm=c.get("category_norm"),
                name_score=c.get("name_score", 0.0),
                geo_score=c.get("geo_score", 0.0),
                category_score=c.get("category_score", 0.0),
                popularity=c.get("popularity", 0.0),
            ))

        top_k_candidates = candidate_objects[:self.perfect_match_top_k] if candidate_objects else []
        perfect_match_candidate = next((c for c in top_k_candidates if c.name_score >= 1.0), None)
        has_perfect_match = perfect_match_candidate is not None
        perfect_match_score = perfect_match_candidate.name_score if perfect_match_candidate else 0.0

        top_candidate = candidate_objects[0] if candidate_objects else None
        has_very_high_match = top_candidate and top_candidate.name_score > 0.8

        results = self.llm_service.rank_and_fuse(
            candidates=candidate_objects,
            query_intent=query_intent,
            top_k=top_k,
        )

        result_dict = {
            "results": [r.model_dump() for r in results],
            "count": len(results),
            "candidates": [c.model_dump() for c in candidate_objects[:top_k]],
        }

        if has_perfect_match:
            result_dict["_stop_signal"] = True
            result_dict["_note"] = (
                f"PERFECT MATCH FOUND in ranked results "
                f"(name_score={perfect_match_score:.2f}) in top "
                f"{self.perfect_match_top_k} candidates! You should STOP "
                f"searching and provide the final answer immediately."
            )
        elif has_very_high_match:
            result_dict["_stop_signal"] = True
            result_dict["_note"] = (
                f"VERY HIGH MATCH FOUND in ranked results "
                f"(name_score={top_candidate.name_score:.2f})! You should "
                f"STOP searching and provide the final answer."
            )

        return result_dict

    async def _execute_tool(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool function and return the result"""
        
        if function_name == "extract_query_intent":
            from app.schemas.query import ExtractQueryIntentInput
            # Validate and normalize language parameter
            # Only 'zh', 'en', 'auto' are supported, fallback to 'auto' for others
            language = arguments.get("language", "auto")
            if language not in ["zh", "en", "auto"]:
                print(f"[Agent] Unsupported language '{language}', falling back to 'auto'")
                language = "auto"
            input_data = ExtractQueryIntentInput(
                user_text=arguments.get("user_text"),
                language=language
            )
            result = await self.extract_tool.extract(input_data)
            return result.model_dump()
        
        elif function_name == "search_by_category":
            category = arguments.get("category")
            country = arguments.get("country")  # Support country filter
            top_n = arguments.get("top_n", 50)
            result = self.sql_search.search_by_category(category, country=country, top_n=top_n)
            return result
        
        elif function_name == "search_by_tags":
            tags = arguments.get("tags", [])
            season = arguments.get("season", "unknown")
            tag_sources = arguments.get("tag_sources")
            top_n = arguments.get("top_n", 50)
            result = self.sql_search.search_by_tags(tags, season, tag_sources, top_n)
            return result
        
        elif function_name == "search_by_history_terms":
            terms = arguments.get("terms", [])
            top_n = arguments.get("top_n", 50)
            result = self.sql_search.search_by_history_terms(terms, top_n)
            return result
        
        elif function_name == "search_with_llm_sql":
            from app.schemas.query import QueryIntent, GeoHints
            query_intent_dict = arguments.get("query_intent", {})
            top_n = arguments.get("top_n", 50)
            
            # Convert dict to QueryIntent object
            geo_hints_dict = query_intent_dict.get("geo_hints", {})
            geo_hints = GeoHints(
                place_name=geo_hints_dict.get("place_name"),
                country=geo_hints_dict.get("country")
            ) if geo_hints_dict else None
            
            query_intent = QueryIntent(
                name_candidates=query_intent_dict.get("name_candidates", []),
                query_tags=query_intent_dict.get("query_tags", []),
                season_hint=query_intent_dict.get("season_hint", "unknown"),
                scene_hints=query_intent_dict.get("scene_hints", []),
                geo_hints=geo_hints,
                confidence_notes=query_intent_dict.get("confidence_notes", [])
            )
            
            result = self.sql_search.search_with_llm_sql(query_intent, top_n)
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
            return self._sync_execute_rank_and_explain(
                candidates=arguments.get("candidates", []),
                query_intent_dict=arguments.get("query_intent", {}),
                top_k=arguments.get("top_k", 5),
            )
        
        else:
            return {"error": f"Unknown tool: {function_name}"}


# Singleton instance
_agent_service: Optional[AgentService] = None


def get_agent_service(perfect_match_top_k: int = 5) -> AgentService:
    """
    Get singleton instance of agent service.
    
    Args:
        perfect_match_top_k: Number of top candidates to check for perfect match (default: 5)
    
    Returns:
        AgentService instance
    """
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService(perfect_match_top_k=perfect_match_top_k)
    return _agent_service

