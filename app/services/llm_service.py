"""
LLM Understanding & Summarization Service

Uses LLM to:
1. Extract tags and evidence from encyclopedia text
2. Fuse multi-source information
3. Generate structured final results
"""
import json
from typing import List, Dict, Any, Optional
from openai import OpenAI

from app.config import settings
from app.schemas.query import (
    ViewpointCandidate,
    ViewpointResult,
    VisualTagInfo,
    Evidence,
    QueryIntent
)
from app.services.enrichment import EnrichmentService


class LLMService:
    """
    LLM Understanding & Summarization layer.
    
    LLM responsibilities (strictly limited):
    - Extract tags + evidence from encyclopedia text (weak supervision)
    - Fuse SQL results, encyclopedia info, and visual tags
    - Output strict JSON
    
    LLM MUST NOT:
    - Directly access database
    - Generate facts
    - Infer visual facts without evidence
    """
    
    def __init__(self, openai_client: Optional[OpenAI] = None):
        self.client = openai_client or OpenAI(api_key=settings.OPENAI_API_KEY)
        self.enrichment = EnrichmentService()
    
    def rank_and_fuse(
        self,
        candidates: List[ViewpointCandidate],
        query_intent: QueryIntent,
        top_k: int = 5
    ) -> List[ViewpointResult]:
        """
        Rank candidates and fuse information into final results.
        
        Args:
            candidates: Initial candidate list from retrieval
            query_intent: User query intent
            top_k: Number of final results to return
            
        Returns:
            List of final viewpoint results
        """
        results = []
        
        # Process top candidates
        for candidate in candidates[:top_k * 2]:  # Process more for better ranking
            # Enrich with external data
            wiki_data = self.enrichment.enrich_wikipedia(candidate.viewpoint_id)
            wikidata_data = self.enrichment.enrich_wikidata(candidate.viewpoint_id)
            visual_tags_data = self.enrichment.enrich_visual_tags(
                candidate.viewpoint_id,
                query_intent.season_hint
            )
            historical_summary, historical_evidence = self.enrichment.get_historical_summary(
                candidate.viewpoint_id
            )
            
            # Calculate tag overlap score
            candidate_tags = set()
            if visual_tags_data:
                for vtag in visual_tags_data:
                    candidate_tags.update(vtag.get('tags', []))
            
            query_tags_set = set(query_intent.query_tags)
            tag_overlap = len(candidate_tags & query_tags_set)
            tag_overlap_score = tag_overlap / len(query_tags_set) if query_tags_set else 0.0
            
            # Calculate season match bonus
            season_match_bonus = 0.0
            if query_intent.season_hint != "unknown":
                for vtag in visual_tags_data:
                    if vtag['season'] == query_intent.season_hint:
                        season_match_bonus = max(season_match_bonus, vtag['confidence'])
            
            # Calculate final match confidence
            match_confidence = (
                candidate.name_score * 0.4 +
                candidate.category_score * 0.2 +
                tag_overlap_score * 0.3 +
                season_match_bonus * 0.1
            )
            
            # Convert visual tags to structured format
            visual_tags = []
            for vtag_data in visual_tags_data:
                # Convert evidence dict to Evidence objects
                evidence_list = []
                evidence_dict = vtag_data.get('evidence', {})
                if isinstance(evidence_dict, dict):
                    evidence_list.append(Evidence(
                        source=evidence_dict.get('source', 'unknown'),
                        reference=evidence_dict.get('reference', ''),
                        text=evidence_dict.get('text')
                    ))
                
                visual_tags.append(VisualTagInfo(
                    season=vtag_data['season'],
                    tags=vtag_data['tags'],
                    confidence=vtag_data['confidence'],
                    evidence=evidence_list,
                    tag_source=vtag_data['tag_source']
                ))
            
            # Generate match explanation
            match_explanation = self._generate_match_explanation(
                candidate,
                query_intent,
                tag_overlap_score,
                season_match_bonus
            )
            
            result = ViewpointResult(
                viewpoint_id=candidate.viewpoint_id,
                name_primary=candidate.name_primary,
                name_variants=candidate.name_variants,
                category_norm=candidate.category_norm,
                historical_summary=historical_summary,
                historical_evidence=historical_evidence,
                visual_tags=visual_tags,
                match_confidence=match_confidence,
                match_explanation=match_explanation
            )
            
            results.append(result)
        
        # Sort by match confidence and return top_k
        results.sort(key=lambda x: x.match_confidence, reverse=True)
        return results[:top_k]
    
    def _generate_match_explanation(
        self,
        candidate: ViewpointCandidate,
        query_intent: QueryIntent,
        tag_overlap_score: float,
        season_match_bonus: float
    ) -> str:
        """
        Generate human-readable explanation of why this candidate matches.
        
        This is a simple rule-based explanation. Could be enhanced with LLM.
        """
        parts = []
        
        if candidate.name_score > 0.7:
            parts.append(f"Name matches: {candidate.name_primary}")
        
        if candidate.category_score > 0:
            parts.append(f"Category: {candidate.category_norm}")
        
        if tag_overlap_score > 0:
            matched_tags = set(candidate.category_norm.split()) if candidate.category_norm else set()
            matched_tags = matched_tags & set(query_intent.query_tags)
            if matched_tags:
                parts.append(f"Visual tags match: {', '.join(matched_tags)}")
        
        if season_match_bonus > 0.5:
            parts.append(f"Strong {query_intent.season_hint} season match")
        
        if candidate.popularity > 0.7:
            parts.append("Highly popular destination")
        
        return ". ".join(parts) if parts else "General match based on available information."
    
    def extract_tags_from_wiki_text(
        self,
        wiki_text: str,
        viewpoint_id: int
    ) -> List[Dict[str, Any]]:
        """
        Extract visual tags from Wikipedia text using weak supervision.
        
        This would use LLM to extract seasonal/visual mentions from text.
        For now, returns empty list - to be implemented.
        """
        # TODO: Implement LLM-based tag extraction from wiki text
        # This would call OpenAI to extract tags with evidence (sentence references)
        return []


# Singleton instance
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Get singleton instance of LLM service"""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service

