#!/usr/bin/env python3
"""
Generate a larger, typed evaluation set from exported TourRAG data.

The output keeps the original test runner columns:
viewpoint_base_name,image_path,history_summary,season_info

It also adds metadata columns:
query_text,query_type,target_name,tags

Existing runners can keep using history_summary, while updated runners can
prefer query_text for more diverse query formulations.
"""
import argparse
import csv
import html
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "exports" / "20260119_111347"
DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "datasets" / "test_set_expanded_500.csv"
ANONYMOUS_ATTRACTION = "this anonymized tourist attraction"
DEFAULT_TYPE_WEIGHTS = {
    "history_description": 0.36,
    "search_description": 0.36,
    "name_query": 0.18,
    "visual_tag_query": 0.07,
    "season_visual_query": 0.03,
}
HARD_SEMANTIC_TYPE_WEIGHTS = {
    "history_description": 0.45,
    "search_description": 0.45,
    "name_query": 0.0,
    "visual_tag_query": 0.07,
    "season_visual_query": 0.03,
}
DEFAULT_ANONYMOUS_RATIO = 0.75
DEFAULT_ANONYMOUS_TARGET_RATIO = 0.60
HARD_SEMANTIC_ANONYMOUS_TARGET_RATIO = 0.95
MAX_DESCRIPTION_CHARS = 2600
MAX_WIKI_DETAIL_CHARS = 1800
MAX_ANONYMOUS_QUERY_CHARS = 1150
NAME_FRAGMENT_PATTERNS = [
    re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ0-9'’.\- ]{5,}"),
    re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]{2,}"),
]
UNIQUE_CLUE_PATTERNS = [
    re.compile(r"\b(?:located|situated|capital|district|county|province|region|state|city|river|valley|island|coast)\b", re.I),
    re.compile(r"\b(?:century|colonial|ancient|archaeological|civilization|dynasty|fort|castle|temple|monastery|palace|war|expedition)\b", re.I),
    re.compile(r"\b(?:UNESCO|World Heritage|nickname|known for|renowned for|dating back|built|founded|named after)\b", re.I),
    re.compile(r"\b(?:India|China|Japan|Taiwan|France|Germany|United States|Norway|Spain|Italy|Lithuania|Turkey|Armenia|Iran)\b", re.I),
]
GENERIC_ANONYMOUS_CLUES = [
    "beautiful scenery",
    "bustling cityscape",
    "cityscape setting",
    "historical significance",
    "natural beauty",
    "natural landscapes",
    "popular spot for visitors",
    "scenic views",
    "surrounding landscape",
    "tourist attraction",
    "traditional and modern architecture",
]
SKIPPED_WIKI_SECTION_TITLES = {
    "references",
    "external links",
    "see also",
    "notes",
    "further reading",
    "bibliography",
}
OFFTOPIC_WIKI_PATTERNS = [
    re.compile(r"\b(?:is|are)\s+(?:a\s+)?(?:genus|species|subspecies|family)\b", re.I),
    re.compile(r"\bare\s+snakes\s+in\s+the\s+family\b", re.I),
    re.compile(r"\bis\s+a\s+venomous\s+snake\b", re.I),
    re.compile(r"\bmay\s+refer\s+to\b", re.I),
    re.compile(r"\bcan\s+refer\s+to\b", re.I),
    re.compile(r"\bis\s+the\s+name\s+of\b", re.I),
]
HARD_SEMANTIC_REJECT_PATTERNS = [
    re.compile(r"\b(?:planet|moons?|zodiac|revolve around the Sun|chief deity of ancient Roman religion)\b", re.I),
    re.compile(r"\b(?:is|are)\s+the\s+(?:German|English|French|Spanish|Italian)\s+(?:language\s+)?word\s+for\b", re.I),
    re.compile(r"\bgenerally refers to the historical town or city centre\b", re.I),
    re.compile(r"\brefers to various old town halls\b", re.I),
    re.compile(r"\b(?:trackless wooden chute|bobsled ride|toboggan-like cars|versions? built)\b", re.I),
    re.compile(r"\b(?:is|are)\s+(?:a\s+)?(?:genus|species|subspecies|family)\b", re.I),
    re.compile(r"\b(?:may|can)\s+refer\s+to\b", re.I),
    re.compile(r"\brefers\s+to\s+various\b", re.I),
    re.compile(r"\b(?:various|different|several)\s+locations\b", re.I),
    re.compile(r"\bassociated\s+with\s+various\b", re.I),
    re.compile(r"\bencompasses\s+various\b", re.I),
    re.compile(r"\bpart\s+of\s+various\b", re.I),
    re.compile(r"\bunknown region\b", re.I),
    re.compile(r"\bhistorical context is limited\b", re.I),
    re.compile(r"\bno specific details\b", re.I),
    re.compile(r"\b(?:is|are)\s+a\s+municipality\b", re.I),
    re.compile(r"\b(?:is|are)\s+a\s+(?:small\s+)?(?:town|village|city)\b", re.I),
    re.compile(r"\b(?:municipality|village|town)\s+in\s+the\s+district\b", re.I),
    re.compile(r"\bcommunity development block\b", re.I),
    re.compile(r"\bmunicipal administration\b", re.I),
    re.compile(r"\b(?:has|with)\s+(?:about\s+)?[\d,]+\s+inhabitants\b", re.I),
    re.compile(r"\bpopulation census\b", re.I),
    re.compile(r"\bpopulation\s+(?:is|of|by sex)\b", re.I),
    re.compile(r"\bprofessional\s+(?:ice hockey|football|basketball|baseball|soccer)\s+team\b", re.I),
    re.compile(r"\bsports teams? (?:are|is) called\b", re.I),
    re.compile(r"\bcurrently play in\b", re.I),
    re.compile(r"\b(?:arsenal|armou?ry)\s+(?:is|are)\s+a\s+place\s+where\b", re.I),
    re.compile(r"\bplace where arms and ammunition\b", re.I),
    re.compile(r"\bfacility for (?:the )?(?:production|maintenance|storage).{0,80}arms and ammunition\b", re.I),
]
HARD_SEMANTIC_REJECT_TARGETS = {
    "altstadt",
    "jupiter",
}
VISUAL_ANCHOR_PATTERNS = [
    re.compile(r"\b(?:unesco|national register|world heritage|grade i listed|listed building)\b", re.I),
    re.compile(r"\b(?:constructed|built|opened|completed|established|dating|dates back|century|dynasty|war)\b", re.I),
    re.compile(r"\b(?:located|set|positioned|stands|lies|near|within)\s+(?:in|on|at|within|near)?\s*[A-Z][A-Za-z'’.-]+", re.I),
    re.compile(r"\b(?:river|lake|mountain|valley|coast|island|peninsula|district|province|region|county|state|park|fort|castle|temple|museum|bridge)\b", re.I),
    re.compile(r"\b\d{3,4}\b"),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:m|km|mi|ft|feet|metres|meters|kilometres|kilometers|miles)\b", re.I),
]
GENERIC_VISUAL_REJECT_PATTERNS = [
    re.compile(r"\bthe unnamed site is a tourist attraction recognized for its (?:natural beauty|unique geological formations|scenic waterfalls|unique .{0,30} displays)\b", re.I),
    re.compile(r"\b(?:picturesque|scenic) (?:attraction|falls attraction).{0,120}\b(?:ideal for|great destination|outdoor enthusiasts)\b", re.I),
    re.compile(r"\bthe site lies in a urban setting, offering a panoramic view of nearby area\b", re.I),
    re.compile(r"\boffering a panoramic view of nearby area\b", re.I),
]
PARAPHRASE_REPLACEMENTS = [
    (r"\bis located in\b", "sits in"),
    (r"\bis located on\b", "stands on"),
    (r"\blocated in\b", "set within"),
    (r"\blocated on\b", "positioned on"),
    (r"\bis situated in\b", "lies in"),
    (r"\bsituated in\b", "found in"),
    (r"\bknown for\b", "recognized for"),
    (r"\bis known as\b", "is often described as"),
    (r"\bis known for\b", "is recognized for"),
    (r"\bis famous for\b", "is noted for"),
    (r"\bfamous for\b", "noted for"),
    (r"\boffers\b", "provides"),
    (r"\bfeatures\b", "contains"),
    (r"\bfeaturing\b", "with"),
    (r"\bvisitors can\b", "travellers may"),
    (r"\battracts many visitors\b", "draws steady visitor interest"),
    (r"\bpopular tourist destination\b", "well-used visitor destination"),
    (r"\bpopular destination\b", "frequent visitor stop"),
    (r"\bpopular attraction\b", "well-known visitor site"),
    (r"\bpanoramic views\b", "wide views"),
    (r"\bstunning views\b", "striking views"),
    (r"\bscenic views\b", "broad landscape views"),
    (r"\bscenic viewpoint\b", "overlook"),
    (r"\bhiking trails\b", "walking routes"),
    (r"\bhiking opportunities\b", "walking-route access"),
    (r"\bhistorical significance\b", "historical importance"),
    (r"\brich history\b", "layered past"),
    (r"\bancient\b", "old"),
    (r"\bhistoric\b", "heritage"),
    (r"\bfortification\b", "defensive work"),
    (r"\bfortress\b", "fortified site"),
    (r"\bmonastery\b", "religious complex"),
    (r"\btemple\b", "religious site"),
    (r"\bcastle\b", "fortified residence"),
    (r"\bwaterfall\b", "falls"),
    (r"\bvalley\b", "lowland corridor"),
    (r"\briver\b", "waterway"),
    (r"\bcityscape\b", "urban setting"),
    (r"\barchitecture\b", "built form"),
    (r"\bwas built\b", "was constructed"),
    (r"\bbuilt in\b", "constructed in"),
    (r"\bwas founded\b", "was established"),
    (r"\bfounded in\b", "established in"),
    (r"\bdates from\b", "originates in"),
    (r"\bdates back to\b", "goes back to"),
    (r"\bthe surrounding\b", "nearby"),
]
PROTECTED_PARAPHRASE_PHRASES = {
    "Coast Guard": "__PROTECTED_COAST_GUARD__",
}
REFERENCE_NOISE_PATTERNS = [
    re.compile(r"\[[0-9,\s]+\]"),
    re.compile(r"\^\s*[a-z]\s+[a-z]\s+", re.I),
    re.compile(r"\bArticle title unknown\b", re.I),
    re.compile(r"\bRetrieved\s+\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\b"),
    re.compile(r"\b(?:Press|Publishing|Journal|Magazine|ISBN)\b.*\b\d{4}\b", re.I),
    re.compile(r"引用错误"),
    re.compile(r"\[[^\]]*编辑[^\]]*\]"),
]
GENERIC_ALIAS_TOKENS = {
    "abbey",
    "arch",
    "arcade",
    "bridge",
    "cave",
    "caves",
    "canal",
    "castle",
    "city",
    "district",
    "falls",
    "fort",
    "garden",
    "hall",
    "historic",
    "house",
    "island",
    "lake",
    "memorial",
    "monument",
    "mount",
    "museum",
    "north",
    "park",
    "palace",
    "plaza",
    "road",
    "route",
    "saint",
    "south",
    "square",
    "street",
    "temple",
    "tower",
    "trail",
    "valley",
    "viewpoint",
    "west",
}


def read_csv_by_id(path: Path, key: str = "viewpoint_id") -> Dict[str, Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return {row[key]: row for row in csv.DictReader(f) if row.get(key)}


def read_visual_tags(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            viewpoint_id = row.get("viewpoint_id")
            if not viewpoint_id:
                continue
            tags = parse_json(row.get("tags"), default=[])
            grouped[viewpoint_id].append(
                {
                    "season": row.get("season") or "unknown",
                    "tags": tags if isinstance(tags, list) else [],
                    "confidence": safe_float(row.get("confidence"), 0.0),
                    "tag_source": row.get("tag_source") or "",
                }
            )
    return grouped


def parse_json(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def safe_float(raw: Optional[str], default: float) -> float:
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def clean_text(text: Optional[str]) -> str:
    cleaned = html.unescape(text or "")
    cleaned = re.sub(r"\[[^\]]*编辑[^\]]*\]", ". ", cleaned)
    cleaned = re.sub(r"\[[0-9,\s]+\]", "", cleaned)
    cleaned = re.sub(r"\s+\^\s+[a-z]\s+[a-z]\s+", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"引用错误：[^。.!?]*", " ", cleaned)
    return " ".join(cleaned.strip().split())


def normalize_for_dedupe(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def split_sentences(text: str) -> List[str]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    cleaned = re.sub(r"\[[^\]]*edit[^\]]*\]", ". ", cleaned, flags=re.I)
    cleaned = re.sub(r"\.mw-parser-output\s+\.[^ ]+\{[^}]+\}", " ", cleaned)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip(" ;") for part in parts if part.strip(" ;")]


def informative_sentence(sentence: str) -> bool:
    folded = sentence.casefold()
    weak_phrases = [
        "specific historical details are not provided",
        "categorized as a tourist attraction",
        "notable tourist attraction",
        "retrieved ",
        "references edit",
        "external links edit",
        "mw-parser-output",
        "reflist",
        "cite error",
        "invoked but never defined",
        "article title unknown",
        "retrieved ",
    ]
    if len(sentence) < 25 or any(phrase in folded for phrase in weak_phrases):
        return False
    return not any(pattern.search(sentence) for pattern in REFERENCE_NOISE_PATTERNS)


def combine_sentences(*texts: str, max_chars: int = MAX_DESCRIPTION_CHARS) -> str:
    sentences: List[str] = []
    seen = set()
    for text in texts:
        for sentence in split_sentences(text):
            if not informative_sentence(sentence):
                continue
            key = normalize_for_dedupe(sentence)
            if not key or key in seen:
                continue
            seen.add(key)
            sentences.append(sentence)

    combined: List[str] = []
    total = 0
    for sentence in sentences:
        projected = total + len(sentence) + (1 if combined else 0)
        if combined and projected > max_chars:
            break
        combined.append(sentence)
        total = projected
    return " ".join(combined)


def paraphrase_text(text: str) -> str:
    paraphrased = clean_text(text)
    for phrase, placeholder in PROTECTED_PARAPHRASE_PHRASES.items():
        paraphrased = re.sub(re.escape(phrase), placeholder, paraphrased, flags=re.IGNORECASE)
    for pattern, replacement in PARAPHRASE_REPLACEMENTS:
        paraphrased = re.sub(pattern, replacement, paraphrased, flags=re.IGNORECASE)

    paraphrased = re.sub(
        r"\bThis anonymized tourist attraction is\b",
        "The unnamed site is",
        paraphrased,
        flags=re.IGNORECASE,
    )
    paraphrased = re.sub(
        r"\bThis anonymized tourist attraction are\b",
        "The unnamed site includes",
        paraphrased,
        flags=re.IGNORECASE,
    )
    paraphrased = re.sub(
        r"\bThe unnamed site includes located\b",
        "The unnamed site is located",
        paraphrased,
        flags=re.IGNORECASE,
    )
    paraphrased = re.sub(
        r"\bThis anonymized tourist attraction has\b",
        "The unnamed site has",
        paraphrased,
        flags=re.IGNORECASE,
    )
    paraphrased = re.sub(
        r"\bthis anonymized tourist attraction's\b",
        "the unnamed site's",
        paraphrased,
        flags=re.IGNORECASE,
    )
    paraphrased = re.sub(
        r"\bthis anonymized tourist attraction\b",
        "the unnamed site",
        paraphrased,
        flags=re.IGNORECASE,
    )
    paraphrased = re.sub(
        r"\bthe unnamed site(?:\s+the unnamed site)+\b",
        "the unnamed site",
        paraphrased,
        flags=re.IGNORECASE,
    )
    paraphrased = re.sub(
        r"\bthe unnamed site of the unnamed site\b",
        "the local site",
        paraphrased,
        flags=re.IGNORECASE,
    )
    paraphrased = re.sub(
        r"\bthe unnamed site's\s+the unnamed site\b",
        "the unnamed site's",
        paraphrased,
        flags=re.IGNORECASE,
    )
    for phrase, placeholder in PROTECTED_PARAPHRASE_PHRASES.items():
        paraphrased = paraphrased.replace(placeholder, phrase)
    return clean_text(paraphrased)


def compress_anonymous_text(text: str, max_chars: int = MAX_ANONYMOUS_QUERY_CHARS) -> str:
    sentences = split_sentences(paraphrase_text(text))
    if not sentences:
        return paraphrase_text(text)[:max_chars].strip()

    selected: List[str] = []
    total = 0
    priority_terms = re.compile(
        r"\b(?:located|set within|sits in|stands on|constructed|established|century|"
        r"dynasty|war|national register|unesco|river|lake|island|mountain|valley|"
        r"coast|temple|fort|castle|monastery|museum|tower|waterfall|viewpoint|"
        r"historic|heritage|ancient|old|built)\b",
        re.I,
    )
    ordered = sorted(
        enumerate(sentences),
        key=lambda item: (
            0 if priority_terms.search(item[1]) else 1,
            item[0],
        ),
    )
    for _, sentence in ordered:
        projected = total + len(sentence) + (1 if selected else 0)
        if selected and projected > max_chars:
            continue
        selected.append(sentence)
        total = projected
        if total >= max_chars * 0.85:
            break

    selected.sort(key=lambda sentence: sentences.index(sentence))
    return clean_text(" ".join(selected))


def wiki_detail_text(wiki: Dict[str, str], max_chars: int = MAX_WIKI_DETAIL_CHARS) -> str:
    """Extract useful prose from wiki extract and sections, skipping reference cruft."""
    if not wiki:
        return ""

    extract = clean_text(wiki.get("extract_text"))
    if any(pattern.search(extract[:300]) for pattern in OFFTOPIC_WIKI_PATTERNS):
        return ""

    texts: List[str] = [extract]
    sections = parse_json(wiki.get("sections"), default=[])
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            title = clean_text(re.sub(r"\[[^\]]*edit[^\]]*\]", "", str(section.get("title") or ""))).casefold()
            if not title or title in SKIPPED_WIKI_SECTION_TITLES:
                continue
            content = clean_text(section.get("content"))
            if content:
                texts.append(content)

    return combine_sentences(*texts, max_chars=max_chars)


def visual_tags_from_summary(summary: Dict[str, str]) -> List[str]:
    tags = parse_json(summary.get("visual_tags"), default=[])
    if not isinstance(tags, list):
        return []
    ignored = {"unknown_country", "attraction"}
    return [str(tag) for tag in tags if str(tag) not in ignored]


def merge_tags(*tag_groups: Iterable[str], limit: int = 10) -> List[str]:
    merged: List[str] = []
    ignored = {"unknown_country", "attraction"}
    for tags in tag_groups:
        for tag in tags:
            tag = clean_text(str(tag))
            if not tag or tag in ignored or tag in merged:
                continue
            merged.append(tag)
            if len(merged) >= limit:
                return merged
    return merged


def feature_sentences(
    tags: List[str],
    season: str,
    category_norm: str,
    category_osm: str,
) -> str:
    sentences: List[str] = []
    category = clean_text(category_norm)
    if category and category != "attraction":
        sentences.append(f"The normalized place category is {category}.")
    elif category_osm:
        category_data = parse_json(category_osm, default={})
        if isinstance(category_data, dict):
            category_pairs = [f"{key}={value}" for key, value in category_data.items() if value and value != "attraction"]
            if category_pairs:
                sentences.append("OSM category clues include " + ", ".join(category_pairs[:3]) + ".")
    if tags:
        sentences.append("Observable visual or scene cues include " + ", ".join(tags[:10]) + ".")
    if season and season != "unknown":
        sentences.append(f"Season metadata suggests {season}.")
    return " ".join(sentences)


def feature_rich_description(
    *,
    target_name: str,
    primary_summary: str,
    secondary_summary: str,
    tags: List[str],
    season: str,
    category_norm: str,
    category_osm: str,
    anonymous: bool,
    query_label: str,
) -> str:
    feature_text = feature_sentences(tags, season, category_norm, category_osm)
    body = combine_sentences(primary_summary, secondary_summary, feature_text)
    if not body:
        body = combine_sentences(feature_text)

    if anonymous:
        return clean_text(f"{query_label}: {compress_anonymous_text(body)}")

    named_body = ensure_direct_name(body, target_name)
    return clean_text(f"{query_label}: {named_body}")


def name_aliases(entity: Dict[str, str], wiki: Dict[str, str]) -> List[str]:
    aliases = [clean_text(entity.get("name_primary")), clean_text(wiki.get("wikipedia_title"))]
    variants = parse_json(entity.get("name_variants"), default={})
    if isinstance(variants, dict):
        aliases.extend(clean_text(str(value)) for value in variants.values())
    elif isinstance(variants, list):
        aliases.extend(clean_text(str(value)) for value in variants)

    expanded: List[str] = []
    for alias in aliases:
        expanded.append(alias)
        for separator in ["/", "|", ";", " - ", " – ", " — "]:
            expanded.extend(part.strip() for part in alias.split(separator))
        for token in re.findall(r"[A-Z][A-Za-z0-9'â€™.-]{4,}", alias):
            if token.casefold() not in GENERIC_ALIAS_TOKENS:
                expanded.append(token)
        for pattern in NAME_FRAGMENT_PATTERNS:
            expanded.extend(match.group(0).strip() for match in pattern.finditer(alias))

    cleaned: List[str] = []
    for alias in expanded:
        alias = clean_text(alias.strip(" ,.;:()[]{}\"'"))
        min_length = 2 if re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", alias) else 3
        if alias.casefold() in GENERIC_ALIAS_TOKENS:
            continue
        if len(alias) >= min_length and alias.casefold() not in {item.casefold() for item in cleaned}:
            cleaned.append(alias)
    return sorted(cleaned, key=len, reverse=True)


def anonymize_text(text: str, aliases: Iterable[str]) -> str:
    anonymized = clean_text(text)
    for alias in aliases:
        if not alias:
            continue
        escaped_alias = re.escape(alias)
        pattern = (
            rf"(?<!\w){escaped_alias}(?!\w)"
            if re.match(r"^\w", alias) and re.search(r"\w$", alias)
            else escaped_alias
        )
        anonymized = re.sub(
            pattern,
            ANONYMOUS_ATTRACTION,
            anonymized,
            flags=re.IGNORECASE,
        )
        if re.match(r"^\w", alias) and re.search(r"\w$", alias) and not alias.casefold().endswith("s"):
            anonymized = re.sub(
                rf"(?<!\w){re.escape(alias)}s(?!\w)",
                ANONYMOUS_ATTRACTION,
                anonymized,
                flags=re.IGNORECASE,
            )
    anonymized = re.sub(
        rf"({re.escape(ANONYMOUS_ATTRACTION)})(?:,\s*also known as\s+\1)+",
        ANONYMOUS_ATTRACTION,
        anonymized,
        flags=re.IGNORECASE,
    )
    anonymized = re.sub(
        r"\balso known as\s+[^,.]+",
        "also known by another local name",
        anonymized,
        flags=re.IGNORECASE,
    )
    anonymized = re.sub(
        r"\(\s*also known by another local name\s*\)",
        "",
        anonymized,
        flags=re.IGNORECASE,
    )
    anonymized = re.sub(r"\([A-Z][A-Za-z0-9'â€™.\- ]{3,40}\)", "", anonymized)
    anonymized = re.sub(
        rf"{re.escape(ANONYMOUS_ATTRACTION)},\s+is\b",
        f"{ANONYMOUS_ATTRACTION} is",
        anonymized,
        flags=re.IGNORECASE,
    )
    anonymized = re.sub(
        rf"{re.escape(ANONYMOUS_ATTRACTION)},\s+(?:or|known as)\s+{re.escape(ANONYMOUS_ATTRACTION)}\s+is\b",
        f"{ANONYMOUS_ATTRACTION} is",
        anonymized,
        flags=re.IGNORECASE,
    )
    anonymized = re.sub(
        rf"{re.escape(ANONYMOUS_ATTRACTION)},\s+known as\s+{re.escape(ANONYMOUS_ATTRACTION)}",
        ANONYMOUS_ATTRACTION,
        anonymized,
        flags=re.IGNORECASE,
    )
    anonymized = re.sub(
        rf"\bThe\s+{re.escape(ANONYMOUS_ATTRACTION)}\b",
        ANONYMOUS_ATTRACTION.capitalize(),
        anonymized,
        flags=re.IGNORECASE,
    )
    anonymized = re.sub(
        rf"\bAn?\s+{re.escape(ANONYMOUS_ATTRACTION)}\b",
        ANONYMOUS_ATTRACTION.capitalize(),
        anonymized,
        flags=re.IGNORECASE,
    )
    anonymized = anonymized.replace(f"'{ANONYMOUS_ATTRACTION}'", ANONYMOUS_ATTRACTION)
    anonymized = re.sub(r"\bthe unnamed site(?:\s+the unnamed site)+\b", "the unnamed site", anonymized, flags=re.I)
    anonymized = re.sub(r"\bthe unnamed site House\b", "the heritage house", anonymized, flags=re.I)
    anonymized = re.sub(r"\bthe unnamed site of the unnamed site\b", "the local museum", anonymized, flags=re.I)
    anonymized = anonymized.replace("  ", " ").strip()
    return anonymized[:1].upper() + anonymized[1:] if anonymized else anonymized


def ensure_direct_name(text: str, target_name: str) -> str:
    if not target_name or target_name.casefold() in text.casefold():
        return text
    return f"{target_name} is described as follows: {text}"


def has_unique_geo_history_clues(text: str) -> bool:
    cleaned = clean_text(text)
    if len(cleaned) < 60:
        return False
    folded = cleaned.casefold()
    weak_phrases = [
        "specific historical details are not provided",
        "categorized as a tourist attraction",
        "notable tourist attraction",
    ]
    if any(phrase in folded for phrase in weak_phrases):
        return False
    matched_patterns = sum(1 for pattern in UNIQUE_CLUE_PATTERNS if pattern.search(cleaned))
    proper_tokens = [
        match.group(0)
        for match in re.finditer(r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]{3,}(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’.-]{3,})?\b", cleaned)
    ]
    generic_proper_tokens = {
        "This",
        "This anonymized",
        "This anonymized tourist",
        "Anonymized tourist",
        "The",
        "There",
        "Known",
        "World War",
    }
    has_place_like_token = any(token not in generic_proper_tokens for token in proper_tokens)
    has_year_or_century = bool(re.search(r"\b(?:\d{3,4}|[1-9]\d?(?:st|nd|rd|th)\s+century)\b", cleaned, re.I))
    has_named_non_latin = bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff\u0400-\u04ff\uac00-\ud7af]{2,}", cleaned))

    if any(generic in folded for generic in GENERIC_ANONYMOUS_CLUES) and not (
        has_year_or_century or has_named_non_latin or has_place_like_token
    ):
        return False

    return matched_patterns >= 2 and (has_place_like_token or has_year_or_century or has_named_non_latin)


def has_leaked_subject_name(text: str) -> bool:
    cleaned = clean_text(text)
    cleaned = re.sub(
        r"^(?:Identify|Find)\b[^:]{0,160}:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not cleaned or cleaned.casefold().startswith(ANONYMOUS_ATTRACTION):
        return False
    if ANONYMOUS_ATTRACTION in cleaned.casefold():
        return bool(re.match(r"^[A-Z][A-Za-z0-9'â€™.\- ]{3,80},?\s+(?:or|also known|is|was)\b", cleaned))
    return bool(
        re.match(
            r"^([A-ZÀ-ÖØ-Þ\u0400-\u04ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af][^,.]{2,80})(?:,\s+or\s+[^,.]{2,80},)?\s+(?:is|was|are|were)\b",
            cleaned,
        )
    )


def query_leaks_target_name(row: Dict[str, str]) -> bool:
    """Detect direct target-name leakage after anonymization."""
    text = clean_text(row.get("query_text") or row.get("history_summary") or "")
    target_name = clean_text(row.get("target_name") or "")
    if not text:
        return False

    text_folded = text.casefold()
    aliases = [target_name] if target_name else []
    aliases.extend(parse_json(row.get("_target_aliases"), default=[]))

    for alias in aliases:
        alias = clean_text(str(alias))
        if not alias:
            continue
        folded_alias = alias.casefold()
        if len(folded_alias) >= 2 and folded_alias in text_folded:
            return True

        parts = [
            part.strip()
            for part in re.split(r"[,/()|;]+", alias)
            if part.strip()
        ]
        for part in parts:
            folded = part.casefold()
            if folded in GENERIC_ALIAS_TOKENS:
                continue
            if re.search(r"[\u3040-\u30ff\u3400-\u9fff\u0400-\u04ff\uac00-\ud7af]{2,}", part):
                if folded in text_folded:
                    return True
            elif len(folded) >= 5 and re.search(rf"\b{re.escape(folded)}\b", text_folded):
                return True
    return False


def has_visual_specific_anchor(query: str) -> bool:
    """Require visual rows to include concrete clues beyond generic scenery."""
    if any(pattern.search(query) for pattern in GENERIC_VISUAL_REJECT_PATTERNS):
        return False
    anchor_hits = sum(1 for pattern in VISUAL_ANCHOR_PATTERNS if pattern.search(query))
    return anchor_hits >= 1


def is_hard_semantic_candidate(row: Dict[str, str]) -> bool:
    """Keep hard-set rows focused on identifiable tourist attractions."""
    if row.get("is_anonymized_name") != "1":
        return False
    if row.get("anonymous_clue_type") == "generic_history":
        return False
    if query_leaks_target_name(row):
        return False

    query = clean_text(row.get("query_text") or row.get("history_summary") or "")
    target_name = clean_text(row.get("target_name") or "")
    folded_query = query.casefold()
    folded_target = target_name.casefold()
    if folded_target in HARD_SEMANTIC_REJECT_TARGETS:
        return False
    if any(pattern.search(query) for pattern in HARD_SEMANTIC_REJECT_PATTERNS):
        return False
    if row.get("anonymous_clue_type") in {"visual", "season_visual"} and not has_visual_specific_anchor(query):
        return False
    if has_leaked_subject_name(query):
        return False

    # Keep rows descriptive enough for text retrieval. Strong geo/history clues
    # are prioritized by row_detail_score and sampling quotas, but not required
    # here because the export has fewer than 1000 strictly geo/history rows.
    minimum_length = 760 if row.get("anonymous_clue_type") in {"visual", "season_visual"} else 620
    if len(query) < minimum_length:
        return False
    if len(re.findall(r"\b(?:the unnamed site|this anonymized tourist attraction)\b", folded_query)) > 18:
        return False

    return True


def is_hard_semantic_fallback_candidate(row: Dict[str, str]) -> bool:
    """Broader hard-set pool used only to fill large 1000-row benchmarks."""
    if row.get("is_anonymized_name") != "1":
        return False
    if row.get("anonymous_clue_type") == "generic_history":
        return False
    if query_leaks_target_name(row):
        return False

    query = clean_text(row.get("query_text") or row.get("history_summary") or "")
    target_name = clean_text(row.get("target_name") or "")
    if target_name.casefold() in HARD_SEMANTIC_REJECT_TARGETS:
        return False
    if any(pattern.search(query) for pattern in HARD_SEMANTIC_REJECT_PATTERNS):
        return False
    if row.get("anonymous_clue_type") in {"visual", "season_visual"} and not has_visual_specific_anchor(query):
        return False
    if ANONYMOUS_ATTRACTION not in query.casefold() and "the unnamed site" not in query.casefold():
        return False
    return len(query) >= 600


def anonymous_text_clue_type(text: str) -> str:
    if has_leaked_subject_name(text):
        return "generic_history"
    return "geo_history" if has_unique_geo_history_clues(text) else "generic_history"


def row_detail_score(row: Dict[str, str]) -> float:
    """Prefer rows that are specific enough to be useful retrieval tests."""
    query = row.get("query_text") or row.get("history_summary") or ""
    tags = parse_json(row.get("tags"), default=[])
    if not isinstance(tags, list):
        tags = []

    score = min(len(query), MAX_DESCRIPTION_CHARS) / 100.0
    score += min(len(tags), 10) * 1.5
    if row.get("anonymous_clue_type") == "geo_history":
        score += 18.0
    elif row.get("anonymous_clue_type") in {"visual", "season_visual"}:
        score += 4.0
    if row.get("is_anonymized_name") == "1":
        score += 8.0
    if row.get("query_type") == "name_query" and row.get("is_anonymized_name") != "1":
        score -= 8.0
    if has_unique_geo_history_clues(query):
        score += 8.0
    return score


def anonymous_geo_history_query(history_summary: str, search_summary: str, tags: List[str]) -> tuple[str, str]:
    for summary in [history_summary, search_summary]:
        if has_unique_geo_history_clues(summary) and not has_leaked_subject_name(summary):
            return (
                "Identify this anonymized tourist attraction from these geographic "
                f"or historical clues: {summary}",
                "geo_history",
            )

    cue_text = ", ".join(tags[:5]) if tags else "the available non-name clues"
    return f"Identify this anonymized tourist attraction using non-name clues: {cue_text}.", "visual"


def best_tag_record(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return max(records, key=lambda r: r.get("confidence", 0.0), default={})


def useful_tags(records: Iterable[Dict[str, Any]], limit: int = 5) -> List[str]:
    ignored = {"unknown_country", "attraction"}
    tags: List[str] = []
    for record in sorted(records, key=lambda r: r.get("confidence", 0.0), reverse=True):
        for tag in record.get("tags") or []:
            if tag not in ignored and tag not in tags:
                tags.append(tag)
            if len(tags) >= limit:
                return tags
    return tags


def should_anonymize_name(rng: random.Random, anonymous_ratio: float) -> bool:
    return rng.random() < anonymous_ratio


def build_rows(
    export_dir: Path,
    anonymous_ratio: float = DEFAULT_ANONYMOUS_RATIO,
    seed: int = 42,
    anonymous_requires_strong_clue: bool = True,
) -> List[Dict[str, str]]:
    anonymous_ratio = min(1.0, max(0.0, anonymous_ratio))
    rng = random.Random(seed)
    summaries = read_csv_by_id(export_dir / "viewpoint_ai_summaries.csv")
    wiki_rows = read_csv_by_id(export_dir / "viewpoint_wiki.csv")
    entities = read_csv_by_id(export_dir / "viewpoint_entity.csv")
    visual_tags = read_visual_tags(export_dir / "viewpoint_visual_tags.csv")

    rows: List[Dict[str, str]] = []
    for viewpoint_id, summary in summaries.items():
        entity = entities.get(viewpoint_id)
        if not entity:
            continue

        target_name = clean_text(entity.get("name_primary"))
        wiki = wiki_rows.get(viewpoint_id, {})
        aliases = name_aliases(entity, wiki)
        direct_history_summary = clean_text(summary.get("history_summary"))
        direct_search_summary = clean_text(summary.get("search_summary"))
        direct_wiki_detail = wiki_detail_text(wiki)
        direct_history_detail = combine_sentences(
            direct_history_summary,
            direct_wiki_detail,
            max_chars=MAX_DESCRIPTION_CHARS,
        )
        direct_search_detail = combine_sentences(
            direct_search_summary,
            direct_wiki_detail,
            max_chars=MAX_DESCRIPTION_CHARS,
        )
        anonymous_history_summary = anonymize_text(direct_history_summary, aliases)
        anonymous_search_summary = anonymize_text(direct_search_summary, aliases)
        anonymous_wiki_detail = anonymize_text(direct_wiki_detail, aliases)
        anonymous_history_detail = combine_sentences(
            anonymous_history_summary,
            anonymous_wiki_detail,
            max_chars=MAX_DESCRIPTION_CHARS,
        )
        anonymous_search_detail = combine_sentences(
            anonymous_search_summary,
            anonymous_wiki_detail,
            max_chars=MAX_DESCRIPTION_CHARS,
        )
        season_info = summary.get("season_info") or "{}"
        tag_records = visual_tags.get(viewpoint_id, [])
        tags = merge_tags(useful_tags(tag_records), visual_tags_from_summary(summary))
        best_tags = best_tag_record(tag_records)
        season = best_tags.get("season") or parse_json(season_info, {}).get("season") or "unknown"
        category_norm = clean_text(entity.get("category_norm"))
        category_osm = clean_text(entity.get("category_osm"))

        base = {
            "viewpoint_base_name": viewpoint_id,
            "image_path": f"exports/images/all_image/{viewpoint_id}.png",
            "season_info": season_info,
            "target_name": target_name,
            "tags": json.dumps(tags, ensure_ascii=False),
            "_target_aliases": json.dumps(aliases, ensure_ascii=False),
        }

        if direct_history_summary and len(direct_history_summary) >= 40:
            history_summary = feature_rich_description(
                target_name=target_name,
                primary_summary=direct_history_detail,
                secondary_summary=direct_search_detail,
                tags=tags,
                season=season,
                category_norm=category_norm,
                category_osm=category_osm,
                anonymous=False,
                query_label="Identify this tourist attraction from its name and detailed supporting clues",
            )
            rows.append(
                {
                    **base,
                    "query_type": "history_description",
                    "query_text": history_summary,
                    "history_summary": history_summary,
                    "is_anonymized_name": "0",
                    "anonymous_clue_type": "direct_name",
                }
            )

            anonymous_name = should_anonymize_name(rng, anonymous_ratio)
            if anonymous_name and anonymous_requires_strong_clue and (
                not has_unique_geo_history_clues(anonymous_history_detail)
                or has_leaked_subject_name(anonymous_history_detail)
            ):
                anonymous_name = False
            if anonymous_name:
                history_summary = feature_rich_description(
                    target_name=target_name,
                    primary_summary=anonymous_history_detail,
                    secondary_summary=anonymous_search_detail,
                    tags=tags,
                    season=season,
                    category_norm=category_norm,
                    category_osm=category_osm,
                    anonymous=True,
                    query_label="Identify this anonymized tourist attraction from detailed geographic, historical, and visual clues",
                )
                rows.append(
                    {
                        **base,
                        "query_type": "history_description",
                        "query_text": history_summary,
                        "history_summary": history_summary,
                        "is_anonymized_name": "1",
                        "anonymous_clue_type": anonymous_text_clue_type(history_summary),
                    }
                )

        if direct_search_summary and len(direct_search_summary) >= 40:
            search_summary = feature_rich_description(
                target_name=target_name,
                primary_summary=direct_search_detail,
                secondary_summary=direct_history_detail,
                tags=tags,
                season=season,
                category_norm=category_norm,
                category_osm=category_osm,
                anonymous=False,
                query_label="Identify this tourist attraction from its name and detailed search clues",
            )
            rows.append(
                {
                    **base,
                    "query_type": "search_description",
                    "query_text": search_summary,
                    "history_summary": search_summary,
                    "is_anonymized_name": "0",
                    "anonymous_clue_type": "direct_name",
                }
            )

            anonymous_name = should_anonymize_name(rng, anonymous_ratio)
            if anonymous_name and anonymous_requires_strong_clue and (
                not has_unique_geo_history_clues(anonymous_search_detail)
                or has_leaked_subject_name(anonymous_search_detail)
            ):
                anonymous_name = False
            if anonymous_name:
                search_summary = feature_rich_description(
                    target_name=target_name,
                    primary_summary=anonymous_search_detail,
                    secondary_summary=anonymous_history_detail,
                    tags=tags,
                    season=season,
                    category_norm=category_norm,
                    category_osm=category_osm,
                    anonymous=True,
                    query_label="Identify this anonymized tourist attraction from detailed search, geographic, and scene clues",
                )
                rows.append(
                    {
                        **base,
                        "query_type": "search_description",
                        "query_text": search_summary,
                        "history_summary": search_summary,
                        "is_anonymized_name": "1",
                        "anonymous_clue_type": anonymous_text_clue_type(search_summary),
                    }
                )

        if target_name and len(target_name) >= 3:
            clue_type = "direct_name"
            query = feature_rich_description(
                target_name=target_name,
                primary_summary=direct_history_detail,
                secondary_summary=direct_search_detail,
                tags=tags,
                season=season,
                category_norm=category_norm,
                category_osm=category_osm,
                anonymous=False,
                query_label=f"Identify the tourist attraction named {target_name} using all supporting clues",
            )
            rows.append(
                {
                    **base,
                    "query_type": "name_query",
                    "query_text": query,
                    "history_summary": query,
                    "is_anonymized_name": "0",
                    "anonymous_clue_type": clue_type,
                }
            )

            anonymous_name = should_anonymize_name(rng, anonymous_ratio)
            if anonymous_name:
                _, clue_type = anonymous_geo_history_query(
                    anonymous_history_detail,
                    anonymous_search_detail,
                    tags,
                )
                if anonymous_requires_strong_clue and clue_type != "geo_history":
                    anonymous_name = False
                    clue_type = "direct_name"
            if anonymous_name:
                query = feature_rich_description(
                    target_name=target_name,
                    primary_summary=anonymous_history_detail,
                    secondary_summary=anonymous_search_detail,
                    tags=tags,
                    season=season,
                    category_norm=category_norm,
                    category_osm=category_osm,
                    anonymous=True,
                    query_label="Identify this anonymized tourist attraction from all available non-name clues",
                )
                rows.append(
                    {
                        **base,
                        "query_type": "name_query",
                        "query_text": query,
                        "history_summary": query,
                        "is_anonymized_name": "1",
                        "anonymous_clue_type": clue_type,
                    }
                )

        if tags:
            query = feature_rich_description(
                target_name=target_name,
                primary_summary=anonymous_search_detail,
                secondary_summary=anonymous_history_detail,
                tags=tags,
                season=season,
                category_norm=category_norm,
                category_osm=category_osm,
                anonymous=True,
                query_label="Find the tourist attraction from visual, scene, geographic, and historical clues",
            )
            rows.append(
                {
                    **base,
                    "query_type": "visual_tag_query",
                    "query_text": query,
                    "history_summary": query,
                    "is_anonymized_name": "1",
                    "anonymous_clue_type": "visual",
                }
            )

        if season and season != "unknown" and tags:
            query = feature_rich_description(
                target_name=target_name,
                primary_summary=anonymous_search_detail,
                secondary_summary=anonymous_history_detail,
                tags=tags,
                season=season,
                category_norm=category_norm,
                category_osm=category_osm,
                anonymous=True,
                query_label=f"Find the {season} tourist attraction from visual, geographic, and historical clues",
            )
            rows.append(
                {
                    **base,
                    "query_type": "season_visual_query",
                    "query_text": query,
                    "history_summary": query,
                    "is_anonymized_name": "1",
                    "anonymous_clue_type": "season_visual",
                }
            )

    return rows


def parse_type_weights(raw: str) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Invalid type weight '{item}'. Expected query_type=weight.")
        query_type, weight = item.split("=", 1)
        weights[query_type.strip()] = float(weight)
    return weights


def weighted_quotas(query_types: List[str], size: int, weights: Dict[str, float]) -> Dict[str, int]:
    active_weights = {query_type: max(0.0, weights.get(query_type, 0.0)) for query_type in query_types}
    if not any(active_weights.values()):
        active_weights = {query_type: 1.0 for query_type in query_types}

    total_weight = sum(active_weights.values())
    raw_quotas = {query_type: size * active_weights[query_type] / total_weight for query_type in query_types}
    quotas = {query_type: int(raw_quotas[query_type]) for query_type in query_types}
    remainder = size - sum(quotas.values())
    for query_type in sorted(query_types, key=lambda qt: raw_quotas[qt] - quotas[qt], reverse=True)[:remainder]:
        quotas[query_type] += 1
    return quotas


def stratified_sample(
    rows: List[Dict[str, str]],
    size: int,
    seed: int,
    type_weights: Optional[Dict[str, float]] = None,
    anonymous_target_ratio: float = DEFAULT_ANONYMOUS_TARGET_RATIO,
) -> List[Dict[str, str]]:
    rng = random.Random(seed)
    anonymous_target_ratio = min(1.0, max(0.0, anonymous_target_ratio))
    sampled: List[Dict[str, str]] = []
    used_viewpoints = set()
    used_targets = set()

    anonymous_quota = int(round(size * anonymous_target_ratio))
    detailed_anonymous = [
        row
        for row in rows
        if row.get("is_anonymized_name") == "1" and row.get("anonymous_clue_type") == "geo_history"
    ]
    rng.shuffle(detailed_anonymous)
    detailed_anonymous.sort(key=row_detail_score, reverse=True)
    for row in detailed_anonymous:
        if len(sampled) >= anonymous_quota:
            break
        viewpoint_id = row["viewpoint_base_name"]
        target_name = row.get("target_name") or viewpoint_id
        if viewpoint_id in used_viewpoints or target_name in used_targets:
            continue
        sampled.append(row)
        used_viewpoints.add(viewpoint_id)
        used_targets.add(target_name)

    by_type: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        viewpoint_id = row["viewpoint_base_name"]
        target_name = row.get("target_name") or viewpoint_id
        if viewpoint_id in used_viewpoints or target_name in used_targets:
            continue
        if row.get("anonymous_clue_type") == "generic_history":
            continue
        if row.get("is_anonymized_name") == "1" and row.get("anonymous_clue_type") == "geo_history":
            continue
        by_type[row["query_type"]].append(row)

    for bucket in by_type.values():
        rng.shuffle(bucket)
        bucket.sort(key=row_detail_score, reverse=True)

    query_types = sorted(by_type)
    quotas = weighted_quotas(query_types, max(0, size - len(sampled)), type_weights or DEFAULT_TYPE_WEIGHTS)
    added_by_type: Dict[str, int] = defaultdict(int)

    for query_type in query_types:
        for row in by_type[query_type]:
            if added_by_type[query_type] >= quotas.get(query_type, 0):
                break
            viewpoint_id = row["viewpoint_base_name"]
            target_name = row.get("target_name") or viewpoint_id
            if viewpoint_id in used_viewpoints or target_name in used_targets:
                continue
            sampled.append(row)
            used_viewpoints.add(viewpoint_id)
            used_targets.add(target_name)
            added_by_type[query_type] += 1

    if len(sampled) < size:
        remaining = [
            r
            for r in rows
            if r["viewpoint_base_name"] not in used_viewpoints
            and (r.get("target_name") or r["viewpoint_base_name"]) not in used_targets
            and r.get("anonymous_clue_type") != "generic_history"
            and not (r.get("is_anonymized_name") == "1" and r.get("anonymous_clue_type") == "geo_history")
        ]
        rng.shuffle(remaining)
        remaining.sort(key=row_detail_score, reverse=True)
        for row in remaining:
            if len(sampled) >= size:
                break
            viewpoint_id = row["viewpoint_base_name"]
            target_name = row.get("target_name") or viewpoint_id
            if viewpoint_id in used_viewpoints or target_name in used_targets:
                continue
            sampled.append(row)
            used_viewpoints.add(viewpoint_id)
            used_targets.add(target_name)

    if len(sampled) < size:
        remaining = [
            r
            for r in rows
            if r["viewpoint_base_name"] not in used_viewpoints
            and (r.get("target_name") or r["viewpoint_base_name"]) not in used_targets
            and r.get("anonymous_clue_type") != "generic_history"
        ]
        rng.shuffle(remaining)
        remaining.sort(key=row_detail_score, reverse=True)
        for row in remaining:
            if len(sampled) >= size:
                break
            viewpoint_id = row["viewpoint_base_name"]
            target_name = row.get("target_name") or viewpoint_id
            if viewpoint_id in used_viewpoints or target_name in used_targets:
                continue
            sampled.append(row)
            used_viewpoints.add(viewpoint_id)
            used_targets.add(target_name)

    if len(sampled) < size:
        remaining = [
            r
            for r in rows
            if r["viewpoint_base_name"] not in used_viewpoints
            and r.get("anonymous_clue_type") != "generic_history"
        ]
        rng.shuffle(remaining)
        remaining.sort(key=row_detail_score, reverse=True)
        for row in remaining:
            if len(sampled) >= size:
                break
            viewpoint_id = row["viewpoint_base_name"]
            if viewpoint_id in used_viewpoints:
                continue
            sampled.append(row)
            used_viewpoints.add(viewpoint_id)
            used_targets.add(row.get("target_name") or viewpoint_id)

    if len(sampled) < size:
        used_rows = {
            (row.get("viewpoint_base_name"), row.get("query_type"), row.get("query_text"))
            for row in sampled
        }
        remaining = [
            r
            for r in rows
            if r.get("anonymous_clue_type") != "generic_history"
            and (r.get("viewpoint_base_name"), r.get("query_type"), r.get("query_text")) not in used_rows
        ]
        rng.shuffle(remaining)
        remaining.sort(key=row_detail_score, reverse=True)
        for row in remaining:
            if len(sampled) >= size:
                break
            row_key = (row.get("viewpoint_base_name"), row.get("query_type"), row.get("query_text"))
            if row_key in used_rows:
                continue
            sampled.append(row)
            used_rows.add(row_key)

    return spread_anonymous_rows(sampled[:size], rng)


def spread_anonymous_rows(rows: List[Dict[str, str]], rng: random.Random) -> List[Dict[str, str]]:
    anonymous = [row for row in rows if row.get("is_anonymized_name") == "1"]
    non_anonymous = [row for row in rows if row.get("is_anonymized_name") != "1"]
    rng.shuffle(anonymous)
    rng.shuffle(non_anonymous)
    if not anonymous:
        return non_anonymous

    result: List[Dict[str, str]] = []
    total = len(rows)
    anon_count = len(anonymous)
    anon_idx = 0
    non_idx = 0
    for position in range(total):
        desired_anonymous_so_far = round((position + 1) * anon_count / total)
        if anon_idx < desired_anonymous_so_far and anon_idx < len(anonymous):
            result.append(anonymous[anon_idx])
            anon_idx += 1
        elif non_idx < len(non_anonymous):
            result.append(non_anonymous[non_idx])
            non_idx += 1
        elif anon_idx < len(anonymous):
            result.append(anonymous[anon_idx])
            anon_idx += 1
    return result


def write_rows(rows: List[Dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "viewpoint_base_name",
        "image_path",
        "history_summary",
        "season_info",
        "query_text",
        "query_type",
        "target_name",
        "tags",
        "is_anonymized_name",
        "anonymous_clue_type",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate expanded TourRAG test set.")
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--size", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--anonymous-ratio",
        type=float,
        default=DEFAULT_ANONYMOUS_RATIO,
        help="Chance to anonymize each name-bearing source row before sampling.",
    )
    parser.add_argument(
        "--anonymous-target-ratio",
        type=float,
        default=DEFAULT_ANONYMOUS_TARGET_RATIO,
        help="Approximate fraction of sampled rows reserved for detailed geo/history anonymous queries.",
    )
    parser.add_argument(
        "--keep-direct-names",
        action="store_true",
        help="Keep real attraction names in name-bearing query text.",
    )
    parser.add_argument(
        "--allow-weak-anonymous",
        action="store_true",
        help="Allow anonymous rows even when only generic or visual clues remain.",
    )
    parser.add_argument(
        "--type-weights",
        default=",".join(f"{key}={value}" for key, value in DEFAULT_TYPE_WEIGHTS.items()),
        help="Comma-separated query type sampling weights, e.g. history_description=0.3,name_query=0.25.",
    )
    parser.add_argument(
        "--hard-semantic",
        action="store_true",
        help="Generate a harder semantic retrieval set: mostly anonymous, no direct-name quota, and fewer lexical shortcuts.",
    )
    args = parser.parse_args()

    export_dir = args.export_dir.resolve()
    anonymous_ratio = 1.0 if args.hard_semantic else (0.0 if args.keep_direct_names else args.anonymous_ratio)
    rows = build_rows(
        export_dir,
        anonymous_ratio=anonymous_ratio,
        seed=args.seed,
        anonymous_requires_strong_clue=not args.allow_weak_anonymous,
    )
    if args.hard_semantic:
        strict_anonymous_rows = [
            row
            for row in rows
            if is_hard_semantic_candidate(row)
        ]
        fallback_anonymous_rows = [
            row
            for row in rows
            if is_hard_semantic_fallback_candidate(row)
        ]
        if len(fallback_anonymous_rows) >= args.size:
            rows = fallback_anonymous_rows
            print(
                "Hard semantic candidate pool: "
                f"{len(strict_anonymous_rows)} strict, {len(fallback_anonymous_rows)} fallback"
            )
        type_weights = HARD_SEMANTIC_TYPE_WEIGHTS
        anonymous_target_ratio = HARD_SEMANTIC_ANONYMOUS_TARGET_RATIO
    else:
        type_weights = parse_type_weights(args.type_weights)
        anonymous_target_ratio = args.anonymous_target_ratio
    sampled = stratified_sample(
        rows,
        args.size,
        args.seed,
        type_weights=type_weights,
        anonymous_target_ratio=anonymous_target_ratio,
    )
    write_rows(sampled, args.output.resolve())

    counts: Dict[str, int] = defaultdict(int)
    for row in sampled:
        counts[row["query_type"]] += 1

    print(f"Generated {len(sampled)} rows -> {args.output.resolve()}")
    for query_type in sorted(counts):
        print(f"{query_type}: {counts[query_type]}")


if __name__ == "__main__":
    main()
