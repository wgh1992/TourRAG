"""
MCP Tool: extract_query_intent

This is the ONLY tool that allows LLM to directly understand user input.
It converts free-form user input into normalized, structured query intent.
"""
import json
import base64
from typing import Dict, Any, Optional, List
from pathlib import Path

from openai import OpenAI

from app.schemas.query import (
    ExtractQueryIntentInput,
    ExtractQueryIntentOutput,
    QueryIntent,
    GeoHints,
    UserImageInput
)
from app.config import settings


# Load tag schema
def load_tag_schema(version: str = "v1.0.0") -> Dict[str, Any]:
    """Load tag schema definition from JSON file"""
    schema_path = Path(__file__).parent.parent.parent / "config" / "tags" / f"tag_schema_{version}.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


class ExtractQueryIntentTool:
    """
    MCP Tool for extracting structured query intent from user input.
    
    This tool MUST:
    - Extract candidate place names
    - Map descriptions to controlled tags
    - Infer a season hint if possible
    
    This tool MUST NOT:
    - Identify a specific viewpoint
    - Fetch data
    - Generate factual knowledge
    """
    
    def __init__(self, openai_client: Optional[OpenAI] = None):
        self.client = openai_client or OpenAI(api_key=settings.OPENAI_API_KEY)
        self.tag_schema_version = settings.TAG_SCHEMA_VERSION
        self.tag_schema = load_tag_schema(self.tag_schema_version)
        # Force use of GPT-4o for vision capabilities
        self.model = "gpt-4o"
    
    def _build_system_prompt(self) -> str:
        """Build system prompt with strict constraints"""
        categories = list(self.tag_schema.get("categories", {}).keys())
        visual_tags = list(self.tag_schema.get("visual_tags", {}).keys())
        scene_tags = list(self.tag_schema.get("scene_tags", {}).keys())
        
        return f"""You are a query intent extraction tool for a viewpoint/tourist attraction RAG system.

Your ONLY job is to extract structured query intent from user input (text and optional images).

CRITICAL CONSTRAINTS:
1. query_tags MUST come from the controlled vocabulary below. NEVER generate free-text tags.
2. If uncertain about season, set season_hint = "unknown" and explain in confidence_notes.
3. You ONLY extract intent - you do NOT identify specific viewpoints, fetch data, or generate facts.

CONTROLLED TAG VOCABULARY:
- Categories: {', '.join(categories)}
- Visual Tags: {', '.join(visual_tags)}
- Scene Tags: {', '.join(scene_tags)}

OUTPUT FORMAT:
You must output valid JSON matching this exact schema:
{{
  "query_intent": {{
    "name_candidates": ["string"],
    "query_tags": ["string"],  // MUST be from controlled vocabulary
    "season_hint": "spring|summer|autumn|winter|unknown",
    "scene_hints": ["string"],
    "geo_hints": {{
      "place_name": "string|null",
      "country": "string|null"
    }},
    "confidence_notes": ["string"]
  }},
  "tag_schema_version": "{self.tag_schema_version}"
}}

Remember: query_tags must ONLY contain values from the controlled vocabulary listed above."""
    
    async def extract(
        self,
        input_data: ExtractQueryIntentInput
    ) -> ExtractQueryIntentOutput:
        """
        Extract structured query intent from user input.
        
        Args:
            input_data: User input (text and optional images)
            
        Returns:
            Structured query intent with controlled tags
        """
        system_prompt = self._build_system_prompt()
        
        # Build user message with image support
        content_parts = []
        
        # Check if we have any input
        has_text = bool(input_data.user_text)
        has_images = bool(input_data.user_images)
        
        if not has_text and not has_images:
            # Empty input - return default intent
            return ExtractQueryIntentOutput(
                query_intent=QueryIntent(
                    name_candidates=[],
                    query_tags=[],
                    season_hint="unknown",
                    scene_hints=[],
                    geo_hints=GeoHints(place_name=None, country=None),
                    confidence_notes=["No user input provided"]
                ),
                tag_schema_version=self.tag_schema_version
            )
        
        # Add text if provided
        if has_text:
            content_parts.append({
                "type": "text",
                "text": input_data.user_text
            })
        else:
            # If only images, add a prompt
            content_parts.append({
                "type": "text",
                "text": "Analyze this image and extract query intent for a viewpoint/tourist attraction search system. Identify visual features, season, scene type, and any place names you can recognize."
            })
        
        # Add images if provided
        if has_images:
            for img in input_data.user_images:
                # Load image data from image_id (assumes it's a file path or base64)
                image_data = self._load_image_data(img.image_id)
                if image_data:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": image_data
                        }
                    })
        
        # Build messages for GPT-4o vision API
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_parts}
        ]
        
        # Call OpenAI API with GPT-4o (vision-capable model)
        response = self.client.chat.completions.create(
            model=self.model,  # Use GPT-4o for vision
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1  # Low temperature for consistent extraction
        )
        
        # Parse response
        result_json = json.loads(response.choices[0].message.content)
        
        # Validate and construct output
        query_intent_dict = result_json.get("query_intent", {})
        
        # Validate tags against schema
        query_tags = query_intent_dict.get("query_tags", [])
        valid_tags = (
            list(self.tag_schema.get("categories", {}).keys()) +
            list(self.tag_schema.get("visual_tags", {}).keys()) +
            list(self.tag_schema.get("scene_tags", {}).keys())
        )
        
        # Filter out invalid tags
        validated_tags = [tag for tag in query_tags if tag in valid_tags]
        if len(validated_tags) < len(query_tags):
            confidence_notes = query_intent_dict.get("confidence_notes", [])
            confidence_notes.append(
                f"Some tags were filtered out as they were not in the controlled vocabulary"
            )
            query_intent_dict["confidence_notes"] = confidence_notes
        query_intent_dict["query_tags"] = validated_tags
        
        # Construct output
        query_intent = QueryIntent(
            name_candidates=query_intent_dict.get("name_candidates", []),
            query_tags=validated_tags,
            season_hint=query_intent_dict.get("season_hint", "unknown"),
            scene_hints=query_intent_dict.get("scene_hints", []),
            geo_hints=GeoHints(
                place_name=query_intent_dict.get("geo_hints", {}).get("place_name"),
                country=query_intent_dict.get("geo_hints", {}).get("country")
            ),
            confidence_notes=query_intent_dict.get("confidence_notes", [])
        )
        
        return ExtractQueryIntentOutput(
            query_intent=query_intent,
            tag_schema_version=result_json.get("tag_schema_version", self.tag_schema_version)
        )
    
    def _load_image_data(self, image_id: str) -> Optional[str]:
        """
        Load image data and convert to base64 data URL.
        
        Args:
            image_id: Image identifier (can be file path, base64 string, or URL)
            
        Returns:
            Base64 data URL string or None if image cannot be loaded
        """
        try:
            # If it's already a data URL or HTTP URL, return as is
            if image_id.startswith("data:") or image_id.startswith("http://") or image_id.startswith("https://"):
                return image_id
            
            # If it's a file path, read and encode
            image_path = Path(image_id)
            if image_path.exists() and image_path.is_file():
                with open(image_path, "rb") as f:
                    image_bytes = f.read()
                    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                    
                    # Determine MIME type from extension
                    ext = image_path.suffix.lower()
                    mime_types = {
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.png': 'image/png',
                        '.gif': 'image/gif',
                        '.webp': 'image/webp'
                    }
                    mime_type = mime_types.get(ext, 'image/jpeg')
                    
                    return f"data:{mime_type};base64,{image_base64}"
            
            # If it's already base64, wrap it
            if len(image_id) > 100:  # Likely base64 string
                return f"data:image/jpeg;base64,{image_id}"
            
            return None
        except Exception as e:
            print(f"Error loading image {image_id}: {e}")
            return None


# Singleton instance
_extract_tool_instance: Optional[ExtractQueryIntentTool] = None


def get_extract_query_intent_tool() -> ExtractQueryIntentTool:
    """Get singleton instance of extract_query_intent tool"""
    global _extract_tool_instance
    if _extract_tool_instance is None:
        _extract_tool_instance = ExtractQueryIntentTool()
    return _extract_tool_instance

