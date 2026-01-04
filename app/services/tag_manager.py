"""
Tag Schema Version Manager

Manages tag taxonomy versions and validation.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from app.config import settings


class TagManager:
    """
    Manages tag schema versions and provides validation utilities.
    """
    
    def __init__(self, version: Optional[str] = None):
        self.version = version or settings.TAG_SCHEMA_VERSION
        self.schema = self._load_schema(self.version)
    
    def _load_schema(self, version: str) -> Dict[str, Any]:
        """Load tag schema from JSON file"""
        schema_path = Path(__file__).parent.parent.parent / "config" / "tags" / f"tag_schema_{version}.json"
        
        if not schema_path.exists():
            raise FileNotFoundError(f"Tag schema {version} not found at {schema_path}")
        
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def get_all_tags(self) -> List[str]:
        """Get all valid tags from the schema"""
        tags = []
        tags.extend(self.schema.get("categories", {}).keys())
        tags.extend(self.schema.get("visual_tags", {}).keys())
        tags.extend(self.schema.get("scene_tags", {}).keys())
        return tags
    
    def get_categories(self) -> List[str]:
        """Get all category tags"""
        return list(self.schema.get("categories", {}).keys())
    
    def get_visual_tags(self) -> List[str]:
        """Get all visual tags"""
        return list(self.schema.get("visual_tags", {}).keys())
    
    def get_scene_tags(self) -> List[str]:
        """Get all scene tags"""
        return list(self.schema.get("scene_tags", {}).keys())
    
    def validate_tags(self, tags: List[str]) -> tuple[List[str], List[str]]:
        """
        Validate tags against schema.
        
        Returns:
            Tuple of (valid_tags, invalid_tags)
        """
        all_valid_tags = set(self.get_all_tags())
        valid = []
        invalid = []
        
        for tag in tags:
            if tag in all_valid_tags:
                valid.append(tag)
            else:
                invalid.append(tag)
        
        return valid, invalid
    
    def get_tag_description(self, tag: str) -> Optional[str]:
        """Get description for a tag"""
        for tag_type in ["categories", "visual_tags", "scene_tags"]:
            if tag in self.schema.get(tag_type, {}):
                return self.schema[tag_type][tag]
        return None
    
    def get_schema_info(self) -> Dict[str, Any]:
        """Get schema metadata"""
        return {
            "version": self.version,
            "total_tags": len(self.get_all_tags()),
            "categories_count": len(self.get_categories()),
            "visual_tags_count": len(self.get_visual_tags()),
            "scene_tags_count": len(self.get_scene_tags())
        }


# Singleton instance
_tag_manager: Optional[TagManager] = None


def get_tag_manager(version: Optional[str] = None) -> TagManager:
    """Get singleton instance of tag manager"""
    global _tag_manager
    if _tag_manager is None or (version and _tag_manager.version != version):
        _tag_manager = TagManager(version)
    return _tag_manager

