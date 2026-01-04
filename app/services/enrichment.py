"""
External Enrichment Service

Enriches candidate viewpoints with local Wikipedia/Wikidata/Commons data.
"""
from typing import List, Dict, Any, Optional
from app.services.database import db
from app.schemas.query import Evidence


class EnrichmentService:
    """
    External Enrichment layer for augmenting candidates with encyclopedia data.
    
    All data sources are local mirrors:
    - Wikipedia extracts
    - Wikidata claims
    - Commons metadata
    """
    
    def enrich_wikipedia(
        self,
        viewpoint_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get Wikipedia information for a viewpoint.
        
        Returns:
            Dict with extract_text, sections, citations, or None if not found
        """
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    wikipedia_title,
                    wikipedia_lang,
                    extract_text,
                    sections,
                    citations
                FROM viewpoint_wiki
                WHERE viewpoint_id = %s
            """, (viewpoint_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    "title": row['wikipedia_title'],
                    "lang": row['wikipedia_lang'],
                    "extract": row['extract_text'],
                    "sections": row['sections'] or [],
                    "citations": row['citations'] or []
                }
        return None
    
    def enrich_wikidata(
        self,
        viewpoint_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get Wikidata information for a viewpoint.
        
        Returns:
            Dict with qid, claims, or None if not found
        """
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    wikidata_qid,
                    claims,
                    sitelinks_count
                FROM viewpoint_wikidata
                WHERE viewpoint_id = %s
            """, (viewpoint_id,))
            
            row = cursor.fetchone()
            if row:
                return {
                    "qid": row['wikidata_qid'],
                    "claims": row['claims'] or {},
                    "sitelinks_count": row['sitelinks_count']
                }
        return None
    
    def enrich_visual_tags(
        self,
        viewpoint_id: int,
        season_hint: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get visual tags for a viewpoint, optionally filtered by season.
        
        Args:
            viewpoint_id: Viewpoint ID
            season_hint: Optional season filter
            
        Returns:
            List of visual tag records
        """
        with db.get_cursor() as cursor:
            if season_hint and season_hint != "unknown":
                cursor.execute("""
                    SELECT 
                        season,
                        tags,
                        confidence,
                        evidence,
                        tag_source
                    FROM viewpoint_visual_tags
                    WHERE viewpoint_id = %s 
                        AND (season = %s OR season = 'unknown')
                    ORDER BY 
                        CASE WHEN season = %s THEN 0 ELSE 1 END,
                        confidence DESC
                """, (viewpoint_id, season_hint, season_hint))
            else:
                cursor.execute("""
                    SELECT 
                        season,
                        tags,
                        confidence,
                        evidence,
                        tag_source
                    FROM viewpoint_visual_tags
                    WHERE viewpoint_id = %s
                    ORDER BY confidence DESC
                """, (viewpoint_id,))
            
            rows = cursor.fetchall()
            return [
                {
                    "season": row['season'],
                    "tags": row['tags'] or [],
                    "confidence": float(row['confidence']),
                    "evidence": row['evidence'] or {},
                    "tag_source": row['tag_source']
                }
                for row in rows
            ]
    
    def enrich_commons_assets(
        self,
        viewpoint_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get Commons asset metadata for a viewpoint.
        
        Returns:
            List of Commons asset records
        """
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    commons_file_id,
                    commons_page,
                    caption,
                    categories,
                    depicts_wikidata,
                    timestamp,
                    hash,
                    license
                FROM viewpoint_commons_assets
                WHERE viewpoint_id = %s
                ORDER BY timestamp DESC NULLS LAST
                LIMIT %s
            """, (viewpoint_id, limit))
            
            rows = cursor.fetchall()
            return [
                {
                    "file_id": row['commons_file_id'],
                    "page": row['commons_page'],
                    "caption": row['caption'],
                    "categories": row['categories'] or [],
                    "depicts": row['depicts_wikidata'] or [],
                    "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None,
                    "hash": row['hash'],
                    "license": row['license']
                }
                for row in rows
            ]
    
    def get_historical_summary(
        self,
        viewpoint_id: int
    ) -> tuple[Optional[str], List[Evidence]]:
        """
        Get historical summary text with evidence.
        
        Returns:
            Tuple of (summary_text, evidence_list)
        """
        wiki_data = self.enrich_wikipedia(viewpoint_id)
        evidence_list = []
        
        if wiki_data and wiki_data.get('extract'):
            summary = wiki_data['extract']
            
            # Add evidence
            evidence_list.append(Evidence(
                source="wikipedia",
                reference=wiki_data.get('title', ''),
                text=summary[:200] + "..." if len(summary) > 200 else summary
            ))
            
            # Add citations if available
            for citation in wiki_data.get('citations', []):
                if isinstance(citation, dict):
                    evidence_list.append(Evidence(
                        source="wikipedia_citation",
                        reference=citation.get('ref', ''),
                        text=citation.get('text', '')
                    ))
            
            return summary, evidence_list
        
        return None, evidence_list


# Singleton instance
_enrichment_service = EnrichmentService()


def get_enrichment_service() -> EnrichmentService:
    """Get singleton instance of enrichment service"""
    return _enrichment_service

