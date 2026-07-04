#!/usr/bin/env python3
"""
Generate a multilingual evaluation set from an existing TourRAG test CSV.

The output keeps all original columns and adds:
- original_query_text
- query_language
- is_multilingual_query

By default, 20% of rows are rewritten into multilingual query templates across
Chinese, Japanese, Korean, Spanish, and Hindi.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "tests" / "datasets" / "test_set_expanded_1000.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "datasets" / "test_set_multilingual_1000.csv"

LANGUAGES = ["zh", "ja", "ko", "es", "hi"]

TAG_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "zh": {
        "mountain": "山地",
        "lake": "湖泊",
        "temple": "寺庙",
        "museum": "博物馆",
        "park": "公园",
        "coast": "海岸",
        "cityscape": "城市景观",
        "monument": "纪念碑",
        "bridge": "桥梁",
        "palace": "宫殿",
        "tower": "塔楼",
        "cave": "洞穴",
        "waterfall": "瀑布",
        "valley": "山谷",
        "island": "岛屿",
        "exterior": "外景",
        "ground_level": "地面视角",
        "panoramic": "全景",
        "sunny": "晴天",
        "cloudy": "多云",
        "spring_greenery": "春季绿意",
        "hiking_trail": "徒步路线",
        "aerial": "空中视角",
        "crowded": "人群密集",
        "autumn_foliage": "秋季红叶",
        "summer_lush": "夏季葱郁",
        "snow_peak": "雪峰",
        "winter_barren": "冬季荒原",
        "snowy": "积雪",
        "interior": "室内",
        "festival": "节庆",
        "ice": "冰雪",
        "foggy": "雾景",
        "falling_leaves": "落叶",
        "night_view": "夜景",
        "ceremony": "仪式",
        "china": "中国",
        "japan": "日本",
        "india": "印度",
        "france": "法国",
        "south_africa": "南非",
        "united_kingdom": "英国",
    },
    "ja": {
        "mountain": "山岳",
        "lake": "湖",
        "temple": "寺院",
        "museum": "博物館",
        "park": "公園",
        "coast": "海岸",
        "cityscape": "都市景観",
        "monument": "記念碑",
        "bridge": "橋",
        "palace": "宮殿",
        "tower": "塔",
        "cave": "洞窟",
        "waterfall": "滝",
        "valley": "渓谷",
        "island": "島",
        "exterior": "外観",
        "ground_level": "地上視点",
        "panoramic": "パノラマ",
        "sunny": "晴天",
        "cloudy": "曇り",
        "spring_greenery": "春の緑",
        "hiking_trail": "登山道",
        "aerial": "空撮視点",
        "crowded": "人が多い",
        "autumn_foliage": "紅葉",
        "summer_lush": "夏の緑",
        "snow_peak": "雪山",
        "winter_barren": "冬の荒涼",
        "snowy": "雪景色",
        "interior": "内部",
        "festival": "祭り",
        "ice": "氷",
        "foggy": "霧",
        "falling_leaves": "落ち葉",
        "night_view": "夜景",
        "ceremony": "儀式",
        "china": "中国",
        "japan": "日本",
        "india": "インド",
        "france": "フランス",
        "south_africa": "南アフリカ",
        "united_kingdom": "英国",
    },
    "ko": {
        "mountain": "산",
        "lake": "호수",
        "temple": "사원",
        "museum": "박물관",
        "park": "공원",
        "coast": "해안",
        "cityscape": "도시 경관",
        "monument": "기념비",
        "bridge": "다리",
        "palace": "궁전",
        "tower": "탑",
        "cave": "동굴",
        "waterfall": "폭포",
        "valley": "계곡",
        "island": "섬",
        "exterior": "외부",
        "ground_level": "지상 시점",
        "panoramic": "파노라마",
        "sunny": "맑은 날",
        "cloudy": "흐린 날",
        "spring_greenery": "봄 녹음",
        "hiking_trail": "하이킹 코스",
        "aerial": "항공 시점",
        "crowded": "사람이 많은",
        "autumn_foliage": "가을 단풍",
        "summer_lush": "여름 녹음",
        "snow_peak": "설산",
        "winter_barren": "겨울 황량함",
        "snowy": "눈 덮인",
        "interior": "실내",
        "festival": "축제",
        "ice": "얼음",
        "foggy": "안개",
        "falling_leaves": "낙엽",
        "night_view": "야경",
        "ceremony": "의식",
        "china": "중국",
        "japan": "일본",
        "india": "인도",
        "france": "프랑스",
        "south_africa": "남아프리카",
        "united_kingdom": "영국",
    },
    "es": {
        "mountain": "montana",
        "lake": "lago",
        "temple": "templo",
        "museum": "museo",
        "park": "parque",
        "coast": "costa",
        "cityscape": "paisaje urbano",
        "monument": "monumento",
        "bridge": "puente",
        "palace": "palacio",
        "tower": "torre",
        "cave": "cueva",
        "waterfall": "cascada",
        "valley": "valle",
        "island": "isla",
        "exterior": "exterior",
        "ground_level": "vista a nivel del suelo",
        "panoramic": "panoramica",
        "sunny": "soleado",
        "cloudy": "nublado",
        "spring_greenery": "vegetacion primaveral",
        "hiking_trail": "sendero",
        "aerial": "vista aerea",
        "crowded": "con mucha gente",
        "autumn_foliage": "follaje de otono",
        "summer_lush": "vegetacion de verano",
        "snow_peak": "cumbre nevada",
        "winter_barren": "paisaje invernal austero",
        "snowy": "nevado",
        "interior": "interior",
        "festival": "festival",
        "ice": "hielo",
        "foggy": "brumoso",
        "falling_leaves": "hojas caidas",
        "night_view": "vista nocturna",
        "ceremony": "ceremonia",
        "china": "China",
        "japan": "Japon",
        "india": "India",
        "france": "Francia",
        "south_africa": "Sudafrica",
        "united_kingdom": "Reino Unido",
    },
    "hi": {
        "mountain": "पर्वत",
        "lake": "झील",
        "temple": "मंदिर",
        "museum": "संग्रहालय",
        "park": "उद्यान",
        "coast": "समुद्र तट",
        "cityscape": "शहरी दृश्य",
        "monument": "स्मारक",
        "bridge": "पुल",
        "palace": "महल",
        "tower": "मीनार",
        "cave": "गुफा",
        "waterfall": "झरना",
        "valley": "घाटी",
        "island": "द्वीप",
        "exterior": "बाहरी दृश्य",
        "ground_level": "जमीनी दृश्य",
        "panoramic": "विस्तृत दृश्य",
        "sunny": "धूप वाला",
        "cloudy": "बादल वाला",
        "spring_greenery": "वसंत की हरियाली",
        "hiking_trail": "पैदल यात्रा मार्ग",
        "aerial": "हवाई दृश्य",
        "crowded": "भीड़भाड़ वाला",
        "autumn_foliage": "शरद ऋतु के पत्ते",
        "summer_lush": "गर्मी की हरियाली",
        "snow_peak": "बर्फीली चोटी",
        "winter_barren": "सर्दियों का विरान दृश्य",
        "snowy": "बर्फ से ढका",
        "interior": "भीतरी भाग",
        "festival": "त्योहार",
        "ice": "बर्फ",
        "foggy": "कोहरा",
        "falling_leaves": "गिरते पत्ते",
        "night_view": "रात्रि दृश्य",
        "ceremony": "समारोह",
        "china": "चीन",
        "japan": "जापान",
        "india": "भारत",
        "france": "फ्रांस",
        "south_africa": "दक्षिण अफ्रीका",
        "united_kingdom": "यूनाइटेड किंगडम",
    },
}

SEASON_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "zh": {"spring": "春季", "summer": "夏季", "autumn": "秋季", "winter": "冬季"},
    "ja": {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"},
    "ko": {"spring": "봄", "summer": "여름", "autumn": "가을", "winter": "겨울"},
    "es": {"spring": "primavera", "summer": "verano", "autumn": "otono", "winter": "invierno"},
    "hi": {"spring": "वसंत", "summer": "गर्मी", "autumn": "शरद", "winter": "सर्दी"},
}


def parse_tags(raw: str) -> List[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data if item]


def parse_season(raw: str) -> str:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return "unknown"
    return str(data.get("season") or "unknown")


def translated_tags(tags: List[str], language: str) -> str:
    mapping = TAG_TRANSLATIONS[language]
    filtered_tags = [tag for tag in tags if tag != "empty"]
    translated = [mapping.get(tag, tag.replace("_", " ")) for tag in filtered_tags[:5]]
    return "、".join(translated) if language in {"zh", "ja"} else ", ".join(translated)


def multilingual_query(row: Dict[str, str], language: str) -> str:
    query_type = row.get("query_type") or "history_description"
    tags = parse_tags(row.get("tags", "[]"))
    tag_text = translated_tags(tags, language) if tags else ""
    season = parse_season(row.get("season_info", "{}"))
    season_text = SEASON_TRANSLATIONS[language].get(season, "")
    fallback_clues = tag_text or "non-name clues"
    target_name = (row.get("target_name") or row.get("viewpoint_base_name") or "").strip()
    is_anonymized = row.get("is_anonymized_name", "1") != "0"
    clue_type = row.get("anonymous_clue_type") or ""
    original_query = (row.get("query_text") or row.get("history_summary") or "").strip()

    if not is_anonymized and target_name:
        if language == "es":
            return f"Identifica la atraccion turistica llamada {target_name}."
        return f"Identify the tourist attraction named {target_name}."

    if clue_type == "geo_history" and original_query:
        if original_query.startswith("Identify this anonymized tourist attraction"):
            return original_query
        if language == "es":
            return f"Identifica esta atraccion turistica anonimizada usando estas pistas geograficas o historicas: {original_query}"
        return f"Identify this anonymized tourist attraction using these geographic or historical clues: {original_query}"

    if language == "zh":
        if query_type == "season_visual_query" and season_text:
            return f"Find an anonymized tourist attraction suitable for {season_text} with these visual clues: {fallback_clues}."
        return f"Identify this anonymized tourist attraction using non-name clues: {fallback_clues}."

    if language == "ja":
        if query_type == "season_visual_query" and season_text:
            return f"Find an anonymized tourist attraction suitable for {season_text} with these visual clues: {fallback_clues}."
        return f"Identify this anonymized tourist attraction using non-name clues: {fallback_clues}."

    if language == "ko":
        if query_type == "season_visual_query" and season_text:
            return f"Find an anonymized tourist attraction suitable for {season_text} with these visual clues: {fallback_clues}."
        return f"Identify this anonymized tourist attraction using non-name clues: {fallback_clues}."

    if language == "es":
        if query_type == "season_visual_query" and season_text:
            return f"Encuentra una atraccion turistica anonimizada adecuada para {season_text} con estas pistas visuales: {fallback_clues}."
        return f"Identifica esta atraccion turistica anonimizada usando pistas sin nombre: {fallback_clues}."

    if query_type == "season_visual_query" and season_text:
        return f"Find an anonymized tourist attraction suitable for {season_text} with these visual clues: {fallback_clues}."
    return f"Identify this anonymized tourist attraction using non-name clues: {fallback_clues}."


def choose_multilingual_indices(row_count: int, ratio: float, seed: int) -> Dict[int, str]:
    rng = random.Random(seed)
    indices = list(range(row_count))
    rng.shuffle(indices)
    multilingual_count = round(row_count * ratio)
    selected = indices[:multilingual_count]

    assignments: Dict[int, str] = {}
    for offset, idx in enumerate(selected):
        assignments[idx] = LANGUAGES[offset % len(LANGUAGES)]
    return assignments


def write_dataset(input_path: Path, output_path: Path, ratio: float, seed: int) -> None:
    with input_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        original_fieldnames = list(reader.fieldnames or [])

    assignments = choose_multilingual_indices(len(rows), ratio, seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = original_fieldnames + [
        "original_query_text",
        "query_language",
        "is_multilingual_query",
    ]

    counts = {"en": 0, **{language: 0 for language in LANGUAGES}}
    for idx, row in enumerate(rows):
        original_query = row.get("query_text") or row.get("history_summary") or ""
        row["original_query_text"] = original_query
        language = assignments.get(idx)
        if language:
            row["query_text"] = multilingual_query(row, language)
            row["history_summary"] = row["query_text"]
            row["query_language"] = language
            row["is_multilingual_query"] = "1"
            counts[language] += 1
        else:
            row["query_language"] = "en"
            row["is_multilingual_query"] = "0"
            counts["en"] += 1

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {output_path}")
    print(f"Multilingual ratio: {sum(counts[l] for l in LANGUAGES)}/{len(rows)}")
    for language in ["en", *LANGUAGES]:
        print(f"{language}: {counts[language]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate multilingual TourRAG test set.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ratio", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    write_dataset(args.input.resolve(), args.output.resolve(), args.ratio, args.seed)


if __name__ == "__main__":
    main()
