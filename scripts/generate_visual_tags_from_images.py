#!/usr/bin/env python3
"""
Generate visual tags, season info, and history/search summaries from images + history text.

This script:
1. Reads viewpoint images from exports/images/all_image (file name = viewpoint_id.png)
2. Reads viewpoint metadata and Wikipedia history from the database
3. Sends image + context to GPT-4o-mini to extract:
   - visual tags (controlled vocabulary)
   - season info + best season to visit
   - history summary + search summary
4. Writes results to:
   - viewpoint_visual_tags (for search tags)
   - viewpoint_ai_summaries (summaries + season info)
"""
import sys
import json
import base64
import time
import argparse
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.services.database import db
from app.tools.extract_query_intent import load_tag_schema


SEASONS = ["spring", "summer", "autumn", "winter", "unknown"]


def load_image_as_data_url(image_path: Path) -> Optional[str]:
    """Load image file and convert to base64 data URL."""
    if not image_path.exists() or not image_path.is_file():
        return None

    ext = image_path.suffix.lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif"
    }
    mime_type = mime_types.get(ext, "image/jpeg")

    with open(image_path, "rb") as f:
        image_bytes = f.read()
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{image_base64}"


def _build_common_fallback_tags(
    valid_visual_tags: List[str],
    valid_scene_tags: List[str],
    valid_category_tags: List[str],
    valid_country_tags: List[str],
    limit: int = 100
) -> List[str]:
    """Provide common allowed tags for prompt-only fallback."""
    preferred = [
        # Scene tags
        "exterior", "interior", "ground_level", "panoramic", "aerial",
        "sunrise", "sunset", "skyline_view", "hiking_trail",
        "close_up", "crowded", "empty", "festival", "ceremony",
        # Visual tags
        "sunny", "cloudy", "rainy", "foggy", "snowy", "night_view",
        "spring_greenery", "summer_lush", "autumn_foliage", "winter_barren",
        "cherry_blossom", "blooming_flowers", "falling_leaves",
        "snow_peak", "ice",
        # Common categories
        "mountain", "lake", "temple", "museum", "park", "coast", "cityscape",
        "monument", "bridge", "palace", "tower", "cave", "waterfall", "valley", "island",
        # Common countries (only used if present in allowed tags)
        "china", "japan", "south_korea", "india", "thailand", "vietnam", "singapore",
        "malaysia", "indonesia", "philippines", "united_states", "canada", "mexico",
        "united_kingdom", "france", "germany", "italy", "spain", "portugal", "greece",
        "australia", "new_zealand", "brazil", "argentina", "chile", "peru", "egypt",
        "south_africa", "morocco", "turkey", "saudi_arabia", "uae", "israel", "russia"
    ]
    allowed = set(valid_visual_tags + valid_scene_tags + valid_category_tags + valid_country_tags)
    ordered = [t for t in preferred if t in allowed]
    for t in valid_scene_tags + valid_visual_tags + valid_category_tags + valid_country_tags:
        if t in allowed and t not in ordered:
            ordered.append(t)
    return ordered[:limit]


def _build_context_cues() -> str:
    """Season/temperature cues for the model (not tags)."""
    return "Seasons: spring, summer, autumn, winter. Temperature: hot, warm, cool, cold."


def build_prompt(
    name: str,
    name_variants: Optional[str],
    category: str,
    category_osm: Optional[str],
    admin_area_ids: Optional[str],
    country: Optional[str],
    region: Optional[str],
    commons_caption: Optional[str],
    wikidata_qid: Optional[str],
    wikidata_sitelinks: Optional[int],
    history_text: str,
    valid_visual_tags: List[str],
    valid_scene_tags: List[str],
    valid_category_tags: List[str],
    valid_country_tags: List[str]
) -> Tuple[str, str]:
    """Build system and user prompts for the LLM."""
    system_prompt = f"""You are a visual tagging and summary tool for a tourist attraction search system.

You will receive one image and limited historical/context text.

CRITICAL CONSTRAINTS:
1. visual_tags MUST come from this controlled vocabulary:
   Visual Tags: {', '.join(valid_visual_tags)}
   Scene Tags: {', '.join(valid_scene_tags)}
   Category Tags: {', '.join(valid_category_tags)}
   Country Tags: {', '.join(valid_country_tags)}
2. season and best_season_to_visit must be one of: spring, summer, autumn, winter, unknown
3. visual_tags should include ALL tags inferred from BOTH image and history text (if any),
   but still only from the controlled vocabulary.
4. Use ONLY the provided text for history_summary and search_summary when it exists.
5. If history text is missing or insufficient, you MAY write a neutral, non-specific
   summary based on the attraction name and category (no concrete facts).
6. If the name is well-known, you may label it as "iconic" but avoid claims like dates,
   founders, events, or statistics.
7. Keep summaries short and factual. Do NOT hallucinate.
8. Return at least 10 visual_tags. If unsure, prefer common allowed tags
   from the "Common fallback tags" list below.

OUTPUT JSON FORMAT (strict):
{{
  "season": "spring|summer|autumn|winter|unknown",
  "season_confidence": 0.0-1.0,
  "best_season_to_visit": "spring|summer|autumn|winter|unknown",
  "visual_tags": ["tag1", "tag2"],
  "history_summary": "1-3 sentences",
  "search_summary": "1-2 sentences"
}}
"""

    user_prompt = f"""Attraction info:
- Name: {name}
- Name variants: {name_variants or "none"}
- Category (normalized): {category}
- Category (OSM): {category_osm or "unknown"}
- Admin area ids: {admin_area_ids or "unknown"}
- Country: {country or "unknown"}
- Region: {region or "unknown"}
- Commons caption: {commons_caption or "none"}
- Wikidata QID: {wikidata_qid or "unknown"}
- Wikidata sitelinks: {wikidata_sitelinks if wikidata_sitelinks is not None else "unknown"}

Historical context (may be empty):
{history_text[:2000]}

Common fallback tags (all allowed):
{', '.join(_build_common_fallback_tags(valid_visual_tags, valid_scene_tags, valid_category_tags, valid_country_tags))}

Context cues (not tags):
{_build_context_cues()}

Tasks:
1. Extract at least 10 visual tags from the image AND history text (use only the allowed tags).
2. Infer the most likely season in the image (or "unknown").
3. Suggest the best season to visit based on history text + visual cues (or "unknown").
4. Summarize historical context (if any) in 1-3 sentences.
5. If history text is empty, write a neutral, non-specific summary based on name/category.
6. Write a concise search summary that mixes visual + history info (1-2 sentences)."""

    return system_prompt, user_prompt


def create_summary_table_if_needed(cursor) -> None:
    """Create storage table for LLM summaries if it doesn't exist."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viewpoint_ai_summaries (
            id BIGSERIAL PRIMARY KEY,
            viewpoint_id BIGINT NOT NULL,
            history_summary TEXT,
            search_summary TEXT,
            season_info JSONB,
            visual_tags JSONB,
            llm_output JSONB,
            source VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (viewpoint_id, source)
        );
    """)
    cursor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'viewpoint_ai_summaries'
                  AND column_name = 'llm_output'
            ) THEN
                ALTER TABLE viewpoint_ai_summaries
                ADD COLUMN llm_output JSONB;
            END IF;
        END $$;
    """)


def fetch_viewpoint_context(viewpoint_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """Fetch viewpoint metadata and history text for a batch of IDs."""
    if not viewpoint_ids:
        return {}

    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT
                v.viewpoint_id,
                v.name_primary,
                v.name_variants,
                v.category_norm,
                v.category_osm,
                v.admin_area_ids,
                w.wikipedia_title,
                w.wikipedia_lang,
                w.extract_text,
                w.sections,
                wd.wikidata_qid,
                wd.claims,
                wd.sitelinks_count,
                ca.caption,
                ca.viewpoint_country,
                ca.viewpoint_region
            FROM viewpoint_entity v
            LEFT JOIN viewpoint_wiki w ON v.viewpoint_id = w.viewpoint_id
            LEFT JOIN viewpoint_wikidata wd ON v.viewpoint_id = wd.viewpoint_id
            LEFT JOIN LATERAL (
                SELECT * FROM viewpoint_commons_assets
                WHERE viewpoint_id = v.viewpoint_id
                ORDER BY downloaded_at DESC NULLS LAST
                LIMIT 1
            ) ca ON true
            WHERE v.viewpoint_id = ANY(%s)
        """, (viewpoint_ids,))

        rows = cursor.fetchall()
        return {row["viewpoint_id"]: row for row in rows}


def _format_json_brief(value: Any, max_chars: int = 1200) -> str:
    """Serialize JSON-like data with a soft size limit."""
    if value is None:
        return ""
    try:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    text = text.strip()
    if len(text) > max_chars:
        return text[:max_chars] + "...(truncated)"
    return text


def build_history_text(ctx: Dict[str, Any]) -> str:
    """Build history/context text from all related tables."""
    parts: List[str] = []

    wikipedia_title = ctx.get("wikipedia_title")
    wikipedia_lang = ctx.get("wikipedia_lang")
    if wikipedia_title or wikipedia_lang:
        parts.append(f"Wikipedia: {wikipedia_title or 'unknown'} ({wikipedia_lang or 'unknown'})")

    extract_text = ctx.get("extract_text") or ""
    if extract_text:
        parts.append(extract_text.strip())

    sections = ctx.get("sections")
    if sections:
        try:
            if isinstance(sections, str):
                sections = json.loads(sections)
            if isinstance(sections, list):
                for section in sections[:2]:
                    content = section.get("content", "")
                    if content:
                        parts.append(content.strip())
        except Exception:
            pass

    wikidata_qid = ctx.get("wikidata_qid")
    if wikidata_qid:
        parts.append(f"Wikidata QID: {wikidata_qid}")

    claims = ctx.get("claims")
    if claims:
        parts.append("Wikidata claims (partial): " + _format_json_brief(claims, max_chars=1200))

    combined = "\n\n".join([p for p in parts if p])
    combined = combined.strip()
    if len(combined) > 3000:
        combined = combined[:3000] + "...(truncated)"
    return combined


def call_llm(
    client: OpenAI,
    image_data_url: str,
    system_prompt: str,
    user_prompt: str,
    model: str
) -> Dict[str, Any]:
    """Call GPT-4o-mini with image + text input."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}}
            ]}
        ],
        response_format={"type": "json_object"},
        temperature=0.1
    )
    return json.loads(response.choices[0].message.content)


def normalize_output(
    output: Dict[str, Any],
    valid_visual_tags: List[str],
    valid_scene_tags: List[str],
    valid_category_tags: List[str],
    valid_country_tags: List[str],
    category: Optional[str],
    country: Optional[str]
) -> Dict[str, Any]:
    """Validate and normalize LLM output."""
    season = output.get("season", "unknown")
    if season not in SEASONS:
        season = "unknown"

    best_season_to_visit = output.get("best_season_to_visit", "unknown")
    if best_season_to_visit not in SEASONS:
        best_season_to_visit = "unknown"

    raw_visual_tags = output.get("visual_tags", []) or []
    raw_tags = output.get("tags", []) or []
    allowed_tags = set(valid_visual_tags + valid_scene_tags + valid_category_tags + valid_country_tags)
    combined_tags = []
    for tag in raw_visual_tags + raw_tags:
        if tag in allowed_tags and tag not in combined_tags:
            combined_tags.append(tag)
    if category and category in allowed_tags and category not in combined_tags:
        combined_tags.append(category)

    country_tag = _normalize_country_tag(country, valid_country_tags)
    if country_tag in allowed_tags and country_tag not in combined_tags:
        combined_tags.append(country_tag)

    season_confidence = output.get("season_confidence", 0.6)
    try:
        season_confidence = float(season_confidence)
    except Exception:
        season_confidence = 0.6
    season_confidence = min(max(season_confidence, 0.0), 1.0)

    history_summary = output.get("history_summary", "") or ""
    search_summary = output.get("search_summary", "") or ""
    evidence = output.get("evidence", {}) or {}

    return {
        "season": season,
        "season_confidence": season_confidence,
        "best_season_to_visit": best_season_to_visit,
        "visual_tags": combined_tags,
        "tags": combined_tags,
        "history_summary": history_summary.strip(),
        "search_summary": search_summary.strip(),
        "evidence": evidence
    }


def _normalize_country_tag(country: Optional[str], valid_country_tags: List[str]) -> str:
    """Normalize country string to a country tag; fallback to unknown_country."""
    if "unknown_country" in valid_country_tags:
        fallback = "unknown_country"
    else:
        fallback = valid_country_tags[0] if valid_country_tags else "unknown_country"

    if not country:
        return fallback

    raw = country.strip().lower()
    if not raw:
        return fallback

    normalized = re.sub(r"[^a-z0-9]+", " ", raw).strip()
    normalized = re.sub(r"\s+", " ", normalized)

    alias_map = {
        "usa": "united_states",
        "u s a": "united_states",
        "u s": "united_states",
        "united states": "united_states",
        "united states of america": "united_states",
        "america": "united_states",
        "uk": "united_kingdom",
        "u k": "united_kingdom",
        "united kingdom": "united_kingdom",
        "great britain": "united_kingdom",
        "england": "united_kingdom",
        "scotland": "united_kingdom",
        "wales": "united_kingdom",
        "south korea": "south_korea",
        "korea south": "south_korea",
        "republic of korea": "south_korea",
        "north korea": "unknown_country",
        "russia": "russia",
        "russian federation": "russia",
        "czech republic": "czechia",
        "uae": "uae",
        "united arab emirates": "uae",
        "peoples republic of china": "china",
        "people s republic of china": "china",
        "pr china": "china",
    }

    if normalized in alias_map:
        candidate = alias_map[normalized]
        if candidate in valid_country_tags:
            return candidate
        return fallback

    candidate = normalized.replace(" ", "_")
    if candidate in valid_country_tags:
        return candidate

    return fallback


def upsert_results(
    viewpoint_id: int,
    result: Dict[str, Any],
    summary_source: str,
    tag_source: str
) -> None:
    """Insert visual tags + summaries into database."""
    with db.get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            create_summary_table_if_needed(cursor)

            cursor.execute("""
                INSERT INTO viewpoint_ai_summaries (
                    viewpoint_id, history_summary, search_summary,
                    season_info, visual_tags, llm_output, source
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (viewpoint_id, source) DO UPDATE
                SET history_summary = EXCLUDED.history_summary,
                    search_summary = EXCLUDED.search_summary,
                    season_info = EXCLUDED.season_info,
                    visual_tags = EXCLUDED.visual_tags,
                    llm_output = EXCLUDED.llm_output,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                viewpoint_id,
                result["history_summary"],
                result["search_summary"],
                json.dumps({
                    "season": result["season"],
                    "best_season_to_visit": result["best_season_to_visit"],
                    "confidence": result["season_confidence"],
                    "evidence": result.get("evidence", {})
                }),
                json.dumps(result["tags"]),
                json.dumps({
                    "season": result["season"],
                    "season_confidence": result["season_confidence"],
                    "best_season_to_visit": result["best_season_to_visit"],
                    "visual_tags": result["visual_tags"],
                    "history_summary": result["history_summary"],
                    "search_summary": result["search_summary"],
                    "evidence": result.get("evidence", {})
                }),
                summary_source
            ))

            cursor.execute("""
                INSERT INTO viewpoint_visual_tags (
                    viewpoint_id, season, tags, confidence, evidence, tag_source
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (viewpoint_id, season, tag_source) DO UPDATE
                SET tags = EXCLUDED.tags,
                    confidence = EXCLUDED.confidence,
                    evidence = EXCLUDED.evidence,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                viewpoint_id,
                result["season"],
                json.dumps(result["tags"]),
                result["season_confidence"],
                json.dumps(result.get("evidence", {})),
                tag_source
            ))


def get_allowed_tag_sources() -> List[str]:
    """Read allowed tag_source values from DB check constraint."""
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT pg_get_constraintdef(c.oid) AS definition
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            WHERE t.relname = 'viewpoint_visual_tags'
              AND c.conname = 'viewpoint_visual_tags_tag_source_check'
        """)
        row = cursor.fetchone()
        if not row or not row.get("definition"):
            return []
        definition = row["definition"]
        return re.findall(r"'([^']+)'", definition)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate visual tags and summaries from images + history text"
    )
    parser.add_argument(
        "--image-dir",
        type=str,
        default="exports/images/all_image",
        help="Directory with images named {viewpoint_id}.png"
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit viewpoints processed")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for DB fetch")
    parser.add_argument("--sleep", type=float, default=0.1, help="Delay between API calls")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without API calls")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="OpenAI model")
    parser.add_argument("--source", type=str, default="gpt_4o_mini_image_history", help="Tag source name")
    args = parser.parse_args()

    image_dir = Path(args.image_dir)
    if not image_dir.exists():
        print(f"❌ Image directory not found: {image_dir}")
        return

    # Load tag schema
    tag_schema = load_tag_schema(settings.TAG_SCHEMA_VERSION)
    valid_visual_tags = list(tag_schema.get("visual_tags", {}).keys())
    valid_scene_tags = list(tag_schema.get("scene_tags", {}).keys())
    valid_category_tags = list(tag_schema.get("categories", {}).keys())
    valid_country_tags = list(tag_schema.get("countries", {}).keys())

    # Collect image files
    image_files = sorted([
        p for p in image_dir.glob("*")
        if p.suffix.lower() in [".png", ".jpg", ".jpeg", ".webp"]
        and not p.name.startswith(".")
    ])
    if args.limit:
        image_files = image_files[:args.limit]

    print("=" * 70)
    print("Generate Visual Tags from Images + History")
    print("=" * 70)
    print(f"Image dir: {image_dir}")
    print(f"Images found: {len(image_files)}")
    print(f"Dry run: {args.dry_run}")
    print(f"Model: {args.model}")
    print(f"Source: {args.source}")

    if not image_files:
        print("⚠️  No images found")
        return

    if args.dry_run:
        print("Dry run mode: no API calls will be made.")
        return

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    allowed_sources = get_allowed_tag_sources()
    tag_source = args.source
    if allowed_sources and tag_source not in allowed_sources:
        fallback = "wiki_weak_supervision" if "wiki_weak_supervision" in allowed_sources else allowed_sources[0]
        print(f"⚠️  tag_source '{tag_source}' not allowed by DB constraint, using '{fallback}'")
        tag_source = fallback

    # Process in batches
    processed = 0
    failed = 0
    start_time = time.time()

    # Map image files to viewpoint IDs
    def parse_viewpoint_id(path: Path) -> Optional[int]:
        try:
            return int(path.stem)
        except Exception:
            return None

    image_map = [(parse_viewpoint_id(p), p) for p in image_files]
    image_map = [(vid, p) for vid, p in image_map if vid is not None]

    for i in range(0, len(image_map), args.batch_size):
        batch = image_map[i:i + args.batch_size]
        batch_ids = [vid for vid, _ in batch]
        context_map = fetch_viewpoint_context(batch_ids)

        for viewpoint_id, image_path in batch:
            ctx = context_map.get(viewpoint_id)
            if not ctx:
                failed += 1
                print(f"✗ Skipped {viewpoint_id}: no DB record")
                continue

            history_text = build_history_text(ctx)
            image_data_url = load_image_as_data_url(image_path)
            if not image_data_url:
                failed += 1
                print(f"✗ Skipped {viewpoint_id}: image load failed")
                continue

            system_prompt, user_prompt = build_prompt(
                name=ctx.get("name_primary", ""),
                name_variants=_format_json_brief(ctx.get("name_variants"), max_chars=400),
                category=ctx.get("category_norm", "attraction") or "attraction",
                category_osm=ctx.get("category_osm"),
                admin_area_ids=_format_json_brief(ctx.get("admin_area_ids"), max_chars=400),
                country=ctx.get("viewpoint_country"),
                region=ctx.get("viewpoint_region"),
                commons_caption=ctx.get("caption"),
                wikidata_qid=ctx.get("wikidata_qid"),
                wikidata_sitelinks=ctx.get("sitelinks_count"),
                history_text=history_text,
                valid_visual_tags=valid_visual_tags,
                valid_scene_tags=valid_scene_tags,
                valid_category_tags=valid_category_tags,
                valid_country_tags=valid_country_tags
            )

            try:
                raw_output = call_llm(
                    client=client,
                    image_data_url=image_data_url,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=args.model
                )
                result = normalize_output(
                    output=raw_output,
                    valid_visual_tags=valid_visual_tags,
                    valid_scene_tags=valid_scene_tags,
                    valid_category_tags=valid_category_tags,
                    valid_country_tags=valid_country_tags,
                    category=ctx.get("category_norm"),
                    country=ctx.get("viewpoint_country")
                )
                upsert_results(viewpoint_id, result, args.source, tag_source)
                processed += 1
                if processed % 50 == 0:
                    elapsed = time.time() - start_time
                    rate = processed / elapsed if elapsed > 0 else 0.0
                    print(f"Progress: {processed}/{len(image_map)} ({rate:.2f}/sec)")
            except Exception as e:
                failed += 1
                print(f"✗ Failed {viewpoint_id}: {e}")

            time.sleep(args.sleep)

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Processed: {processed}")
    print(f"Failed: {failed}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
