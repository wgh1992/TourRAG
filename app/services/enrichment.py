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
                extract_text = row['extract_text']
                return {
                    "title": row['wikipedia_title'],
                    "lang": row['wikipedia_lang'],
                    "extract": extract_text,
                    "extract_text": extract_text,
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
                qid = row['wikidata_qid']
                return {
                    "qid": qid,
                    "wikidata_qid": qid,
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
        limit: int = 10,
        include_image_data: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get Commons asset metadata for a viewpoint.
        
        Args:
            viewpoint_id: Viewpoint ID
            limit: Maximum number of assets to return
            include_image_data: If True, include image binary data (use with caution for large images)
        
        Returns:
            List of Commons asset records
        """
        with db.get_cursor() as cursor:
            # Select columns based on whether image data is needed
            if include_image_data:
                cursor.execute("""
                    SELECT 
                        id,
                        commons_file_id,
                        commons_page,
                        caption,
                        categories,
                        depicts_wikidata,
                        timestamp,
                        hash,
                        license,
                        image_blob,
                        ST_AsGeoJSON(image_geometry)::jsonb as image_geometry,
                        image_exif,
                        image_width,
                        image_height,
                        image_format,
                        file_size_bytes,
                        downloaded_at
                    FROM viewpoint_commons_assets
                    WHERE viewpoint_id = %s
                    ORDER BY timestamp DESC NULLS LAST
                    LIMIT %s
                """, (viewpoint_id, limit))
            else:
                cursor.execute("""
                    SELECT 
                        id,
                        commons_file_id,
                        commons_page,
                        caption,
                        categories,
                        depicts_wikidata,
                        timestamp,
                        hash,
                        license,
                        ST_AsGeoJSON(image_geometry)::jsonb as image_geometry,
                        image_exif,
                        image_width,
                        image_height,
                        image_format,
                        file_size_bytes,
                        downloaded_at
                    FROM viewpoint_commons_assets
                    WHERE viewpoint_id = %s
                    ORDER BY timestamp DESC NULLS LAST
                    LIMIT %s
                """, (viewpoint_id, limit))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                asset = {
                    "id": row['id'],
                    "file_id": row['commons_file_id'],
                    "page": row['commons_page'],
                    "caption": row['caption'],
                    "categories": row['categories'] or [],
                    "depicts": row['depicts_wikidata'] or [],
                    "timestamp": row['timestamp'].isoformat() if row['timestamp'] else None,
                    "hash": row['hash'],
                    "license": row['license'],
                    "has_image": row.get('image_blob') is not None or row.get('downloaded_at') is not None,
                    "image_width": row.get('image_width'),
                    "image_height": row.get('image_height'),
                    "image_format": row.get('image_format'),
                    "file_size_bytes": row.get('file_size_bytes'),
                    "downloaded_at": row['downloaded_at'].isoformat() if row.get('downloaded_at') else None
                }
                
                # Add geolocation if available
                if row.get('image_geometry'):
                    geom = row['image_geometry']
                    if geom and 'coordinates' in geom:
                        # GeoJSON format: [lng, lat]
                        coords = geom['coordinates']
                        asset['geolocation'] = {
                            "longitude": coords[0],
                            "latitude": coords[1],
                            "geometry": geom
                        }
                
                # Add EXIF metadata summary (not full data to avoid large responses)
                if row.get('image_exif'):
                    exif = row['image_exif']
                    asset['exif_summary'] = {
                        "has_gps": 'gps' in exif and 'latitude' in exif.get('gps', {}),
                        "datetime": exif.get('exif', {}).get('datetime_original') or exif.get('exif', {}).get('datetime')
                    }
                
                # Include image data only if requested
                if include_image_data and row.get('image_blob'):
                    import base64
                    asset['image_data_base64'] = base64.b64encode(row['image_blob']).decode('utf-8')
                    asset['image_mime_type'] = f"image/{row.get('image_format', 'jpeg').lower()}"
                
                results.append(asset)
            
            return results
    
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

        # Fallback to AI-generated history summary if Wikipedia extract is missing
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    history_summary,
                    source,
                    updated_at
                FROM viewpoint_ai_summaries
                WHERE viewpoint_id = %s
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 1
            """, (viewpoint_id,))
            row = cursor.fetchone()
            if row and row.get('history_summary'):
                summary = row['history_summary']
                evidence_list.append(Evidence(
                    source="ai_summary",
                    reference=row.get('source') or 'viewpoint_ai_summaries',
                    text=summary[:200] + "..." if len(summary) > 200 else summary
                ))
                return summary, evidence_list

        return None, evidence_list


# Singleton instance
_enrichment_service = EnrichmentService()


def get_enrichment_service() -> EnrichmentService:
    """Get singleton instance of enrichment service"""
    return _enrichment_service

