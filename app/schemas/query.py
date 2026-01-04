"""
Query intent schemas for MCP Tool: extract_query_intent
"""
from typing import Optional, List, Literal
from pydantic import BaseModel, Field


class UserImageInput(BaseModel):
    """User-provided image reference"""
    image_id: str = Field(..., description="Image identifier/reference")
    mime_type: Optional[str] = Field(None, description="MIME type of the image")


class ExtractQueryIntentInput(BaseModel):
    """Input schema for extract_query_intent MCP tool"""
    user_text: Optional[str] = Field(
        None,
        description="Raw user text describing a place, features, or preferences."
    )
    user_images: Optional[List[UserImageInput]] = Field(
        default_factory=list,
        description="Optional user-provided images for intent understanding."
    )
    language: Literal["zh", "en", "auto"] = Field(
        default="auto",
        description="Language preference for processing"
    )


class GeoHints(BaseModel):
    """Geographic hints extracted from user input"""
    place_name: Optional[str] = Field(None, description="City or region name")
    country: Optional[str] = Field(None, description="Country name")


class QueryIntent(BaseModel):
    """Structured query intent extracted from user input"""
    name_candidates: List[str] = Field(
        default_factory=list,
        description="Possible place names or aliases mentioned or implied."
    )
    query_tags: List[str] = Field(
        default_factory=list,
        description="Normalized tags mapped to the controlled tag taxonomy."
    )
    season_hint: Literal["spring", "summer", "autumn", "winter", "unknown"] = Field(
        ...,
        description="Inferred season preference"
    )
    scene_hints: List[str] = Field(
        default_factory=list,
        description="Optional scene-level hints such as sunrise or night_view."
    )
    geo_hints: GeoHints = Field(
        ...,
        description="Geographic location hints"
    )
    confidence_notes: List[str] = Field(
        default_factory=list,
        description="Notes explaining ambiguity or uncertainty."
    )


class ExtractQueryIntentOutput(BaseModel):
    """Output schema for extract_query_intent MCP tool"""
    query_intent: QueryIntent = Field(..., description="Structured query intent")
    tag_schema_version: str = Field(..., description="Version of the controlled tag taxonomy used")


class ViewpointCandidate(BaseModel):
    """Single viewpoint candidate result"""
    viewpoint_id: int
    name_primary: str
    name_variants: dict
    category_norm: Optional[str]
    name_score: float
    geo_score: float
    category_score: float
    popularity: float
    tag_overlap_score: Optional[float] = None
    season_match_bonus: Optional[float] = None


class Evidence(BaseModel):
    """Evidence source for information"""
    source: str  # "wikipedia", "wikidata", "commons", etc.
    reference: str  # File ID, sentence hash, QID, etc.
    text: Optional[str] = None  # Relevant text excerpt


class VisualTagInfo(BaseModel):
    """Visual tag information with evidence"""
    season: str
    tags: List[str]
    confidence: float
    evidence: List[Evidence]
    tag_source: str


class ViewpointResult(BaseModel):
    """Final viewpoint result with all information"""
    viewpoint_id: int
    name_primary: str
    name_variants: dict
    category_norm: Optional[str]
    historical_summary: Optional[str] = None
    historical_evidence: List[Evidence] = Field(default_factory=list)
    visual_tags: List[VisualTagInfo] = Field(default_factory=list)
    match_confidence: float
    match_explanation: str


class QueryResponse(BaseModel):
    """Final response schema"""
    query_intent: QueryIntent
    candidates: List[ViewpointResult] = Field(..., description="Top-K viewpoint results")
    sql_queries: List[dict] = Field(default_factory=list, description="SQL queries executed")
    tool_calls: List[dict] = Field(default_factory=list, description="Tool calls made")
    execution_time_ms: int
    tag_schema_version: str

