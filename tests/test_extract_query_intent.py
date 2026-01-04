"""
Tests for extract_query_intent MCP tool
"""
import pytest
from app.tools.extract_query_intent import ExtractQueryIntentTool
from app.schemas.query import ExtractQueryIntentInput


@pytest.mark.asyncio
async def test_extract_query_intent_text_only():
    """Test extracting intent from text input"""
    tool = ExtractQueryIntentTool()
    
    input_data = ExtractQueryIntentInput(
        user_text="我想看春天的樱花，最好是日本的寺庙",
        language="zh"
    )
    
    result = await tool.extract(input_data)
    
    assert result.tag_schema_version is not None
    assert result.query_intent is not None
    assert "cherry_blossom" in result.query_intent.query_tags or "temple" in result.query_intent.query_tags
    assert result.query_intent.season_hint in ["spring", "unknown"]


@pytest.mark.asyncio
async def test_extract_query_intent_empty():
    """Test handling empty input"""
    tool = ExtractQueryIntentTool()
    
    input_data = ExtractQueryIntentInput()
    
    result = await tool.extract(input_data)
    
    assert result.query_intent.season_hint == "unknown"
    assert len(result.query_intent.confidence_notes) > 0


@pytest.mark.asyncio
async def test_tag_validation():
    """Test that extracted tags are validated against schema"""
    tool = ExtractQueryIntentTool()
    
    input_data = ExtractQueryIntentInput(
        user_text="mountain with snow in winter"
    )
    
    result = await tool.extract(input_data)
    
    # All tags should be from controlled vocabulary
    all_valid_tags = tool.tag_schema.get("categories", {}).keys()
    all_valid_tags = list(all_valid_tags) + list(tool.tag_schema.get("visual_tags", {}).keys())
    all_valid_tags = list(all_valid_tags) + list(tool.tag_schema.get("scene_tags", {}).keys())
    
    for tag in result.query_intent.query_tags:
        assert tag in all_valid_tags, f"Tag '{tag}' not in controlled vocabulary"

