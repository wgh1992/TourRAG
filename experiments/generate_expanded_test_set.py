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
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "exports" / "20260119_111347"
DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "test_set_expanded_1000.csv"


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
    return " ".join((text or "").strip().split())


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


def build_rows(export_dir: Path) -> List[Dict[str, str]]:
    summaries = read_csv_by_id(export_dir / "viewpoint_ai_summaries.csv")
    entities = read_csv_by_id(export_dir / "viewpoint_entity.csv")
    visual_tags = read_visual_tags(export_dir / "viewpoint_visual_tags.csv")

    rows: List[Dict[str, str]] = []
    for viewpoint_id, summary in summaries.items():
        entity = entities.get(viewpoint_id)
        if not entity:
            continue

        target_name = clean_text(entity.get("name_primary"))
        history_summary = clean_text(summary.get("history_summary"))
        search_summary = clean_text(summary.get("search_summary"))
        season_info = summary.get("season_info") or "{}"
        tag_records = visual_tags.get(viewpoint_id, [])
        tags = useful_tags(tag_records)
        best_tags = best_tag_record(tag_records)
        season = best_tags.get("season") or parse_json(season_info, {}).get("season") or "unknown"

        base = {
            "viewpoint_base_name": viewpoint_id,
            "image_path": f"exports/images/all_image/{viewpoint_id}.png",
            "season_info": season_info,
            "target_name": target_name,
            "tags": json.dumps(tags, ensure_ascii=False),
        }

        if history_summary and len(history_summary) >= 40:
            rows.append(
                {
                    **base,
                    "query_type": "history_description",
                    "query_text": history_summary,
                    "history_summary": history_summary,
                }
            )

        if search_summary and len(search_summary) >= 40:
            rows.append(
                {
                    **base,
                    "query_type": "search_description",
                    "query_text": search_summary,
                    "history_summary": search_summary,
                }
            )

        if target_name and len(target_name) >= 3:
            query = f"Identify the tourist attraction named {target_name}."
            rows.append(
                {
                    **base,
                    "query_type": "name_query",
                    "query_text": query,
                    "history_summary": query,
                }
            )

        if tags:
            query = "Find the tourist attraction with these visual or scene cues: " + ", ".join(tags) + "."
            rows.append(
                {
                    **base,
                    "query_type": "visual_tag_query",
                    "query_text": query,
                    "history_summary": query,
                }
            )

        if season and season != "unknown" and tags:
            query = (
                f"Find a {season} tourist attraction matching these visual cues: "
                f"{', '.join(tags[:4])}."
            )
            rows.append(
                {
                    **base,
                    "query_type": "season_visual_query",
                    "query_text": query,
                    "history_summary": query,
                }
            )

    return rows


def stratified_sample(rows: List[Dict[str, str]], size: int, seed: int) -> List[Dict[str, str]]:
    rng = random.Random(seed)
    by_type: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_type[row["query_type"]].append(row)

    for bucket in by_type.values():
        rng.shuffle(bucket)

    query_types = sorted(by_type)
    per_type = max(1, size // len(query_types))
    sampled: List[Dict[str, str]] = []
    used_targets = set()

    for query_type in query_types:
        for row in by_type[query_type]:
            if len([r for r in sampled if r["query_type"] == query_type]) >= per_type:
                break
            key = (row["viewpoint_base_name"], row["query_type"])
            if key in used_targets:
                continue
            sampled.append(row)
            used_targets.add(key)

    if len(sampled) < size:
        remaining = [r for r in rows if (r["viewpoint_base_name"], r["query_type"]) not in used_targets]
        rng.shuffle(remaining)
        sampled.extend(remaining[: size - len(sampled)])

    rng.shuffle(sampled)
    return sampled[:size]


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
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate expanded TourRAG test set.")
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    export_dir = args.export_dir.resolve()
    rows = build_rows(export_dir)
    sampled = stratified_sample(rows, args.size, args.seed)
    write_rows(sampled, args.output.resolve())

    counts: Dict[str, int] = defaultdict(int)
    for row in sampled:
        counts[row["query_type"]] += 1

    print(f"Generated {len(sampled)} rows -> {args.output.resolve()}")
    for query_type in sorted(counts):
        print(f"{query_type}: {counts[query_type]}")


if __name__ == "__main__":
    main()
