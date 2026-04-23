"""
Batch comparison: RAG vs No-RAG on the same CSV.

Reads the same CSV format as tests/test_RAG.py. For each row, runs both
the full RAG pipeline and the no-RAG baseline, then computes metrics and
writes JSONL + summary JSON.
"""
import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def build_query_from_row(row: Dict[str, str]) -> str:
    """Build query string from CSV row (same logic as test_RAG.py)."""
    history_summary = (row.get("history_summary") or "").strip()
    base_name = (row.get("viewpoint_base_name") or "").strip()
    season_info_raw = (row.get("season_info") or "").strip()
    season_hint = ""
    if season_info_raw:
        try:
            season_info = json.loads(season_info_raw)
            season_hint = (season_info.get("season") or "").strip()
        except json.JSONDecodeError:
            season_hint = ""
    query = history_summary or base_name
    if season_hint and season_hint != "unknown":
        query = f"{query}. best season {season_hint}"
    return query


def collect_top_candidate_ids(tool_calls: List[Dict], top_k: int) -> List[int]:
    """Collect top-K viewpoint IDs from RAG tool calls (same logic as test_RAG.py)."""
    ordered_ids: List[int] = []
    seen = set()

    for tool_call in tool_calls or []:
        tool_name = tool_call.get("tool")
        if tool_name == "rank_and_explain_results":
            payload = tool_call.get("result") or {}
            candidates = payload.get("candidates") or []
            if not candidates:
                results = payload.get("results") or []
                candidates = [{"viewpoint_id": r.get("viewpoint_id")} for r in results]
            for cand in candidates[:top_k]:
                cid = cand.get("viewpoint_id")
                if isinstance(cid, int) and cid not in seen:
                    ordered_ids.append(cid)
                    seen.add(cid)

    for tool_call in tool_calls or []:
        tool_name = tool_call.get("tool")
        if tool_name in {
            "search_with_llm_sql",
            "search_by_name",
            "search_by_category",
            "search_by_tags",
            "search_by_history_terms",
            "search_popular",
        }:
            payload = tool_call.get("result") or {}
            candidates = payload.get("candidates") or []
            for cand in candidates[:top_k]:
                cid = cand.get("viewpoint_id")
                if isinstance(cid, int) and cid not in seen:
                    ordered_ids.append(cid)
                    seen.add(cid)

    return ordered_ids[:top_k]


def get_name_primary_for_viewpoint(viewpoint_id: int) -> Optional[str]:
    """Fetch name_primary from DB for text-hit evaluation."""
    from app.services.database import db

    with db.get_cursor() as cursor:
        cursor.execute(
            "SELECT name_primary FROM viewpoint_entity WHERE viewpoint_id = %s",
            (viewpoint_id,),
        )
        row = cursor.fetchone()
    return row["name_primary"] if row and row.get("name_primary") else None


async def run_rag(query: str, max_iterations: int) -> Dict[str, Any]:
    """Run full RAG pipeline (agent with tools)."""
    from app.services.agent_service import get_agent_service

    agent = get_agent_service()
    return await agent.answer_query(
        user_query=query,
        language="auto",
        max_iterations=max_iterations,
    )


async def run_no_rag(query: str) -> Dict[str, Any]:
    """Run no-RAG baseline (pure LLM)."""
    from experiments.no_rag_baseline import run_no_rag_async

    return await run_no_rag_async(query, model=None, language="auto")


def text_hit(answer: str, name_primary: Optional[str], base_name: str) -> bool:
    """True if answer contains the ground-truth name (for no-RAG metric)."""
    if not answer:
        return False
    # Prefer DB name; fallback to CSV base_name (e.g. id as string or a name)
    search_name = (name_primary or base_name or "").strip()
    if not search_name:
        return False
    return search_name in answer


async def run_batch(
    input_csv: Path,
    output_dir: Path,
    limit: int,
    name_top_k: int,
    max_iterations: int,
    no_rag_only: bool = False,
) -> None:
    rows: List[Dict[str, str]] = []
    with input_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "no_rag_only" if no_rag_only else "comparison"
    jsonl_path = output_dir / f"{prefix}_{timestamp}.jsonl"
    csv_path = output_dir / f"{prefix}_{timestamp}.csv"
    summary_path = output_dir / f"summary_{prefix}_{timestamp}.json"

    rag_name_matches = 0
    no_rag_text_hits = 0
    total_with_target = 0

    csv_columns = ["index", "viewpoint_base_name", "target_id", "correct_name", "query", "no_rag_answer", "no_rag_text_hit"]
    if not no_rag_only:
        csv_columns.extend(["rag_answer", "rag_top_ids", "name_match", "rag_iterations"])

    with jsonl_path.open("w", encoding="utf-8") as out, csv_path.open(
        "w", newline="", encoding="utf-8"
    ) as csv_file:
        csv_writer = csv.DictWriter(csv_file, fieldnames=csv_columns, extrasaction="ignore")
        csv_writer.writeheader()
        for idx, row in enumerate(rows, start=1):
            query = build_query_from_row(row)
            base_name = (row.get("viewpoint_base_name") or "").strip()
            target_id = int(base_name) if base_name.isdigit() else None

            if no_rag_only:
                rag_result = None
                rag_answer = ""
                top_ids = []
                name_match = False
            else:
                rag_result = await run_rag(query, max_iterations)
                rag_answer = rag_result.get("answer") or ""
                tool_calls = rag_result.get("tool_calls") or []
                top_ids = collect_top_candidate_ids(tool_calls, name_top_k)
                name_match = False
                if target_id is not None:
                    total_with_target += 1
                    name_match = target_id in top_ids
                    if name_match:
                        rag_name_matches += 1

            no_rag_result = await run_no_rag(query)
            no_rag_answer = no_rag_result.get("answer") or ""

            if target_id is not None and no_rag_only:
                total_with_target += 1

            name_primary = get_name_primary_for_viewpoint(target_id) if target_id else None
            correct_name = (name_primary or base_name or "").strip()
            no_rag_hit = text_hit(no_rag_answer, name_primary, base_name)
            if no_rag_hit:
                no_rag_text_hits += 1

            record = {
                "index": idx,
                "viewpoint_base_name": base_name,
                "target_id": target_id,
                "correct_name": correct_name,
                "query": query,
                "no_rag_answer": no_rag_answer[:500],
                "no_rag_text_hit": no_rag_hit,
            }
            if not no_rag_only:
                record["rag_answer"] = rag_answer[:500]
                record["rag_top_ids"] = top_ids
                record["name_match"] = name_match
                record["rag_iterations"] = rag_result.get("iterations") if rag_result else None

            out.write(json.dumps(record, ensure_ascii=False) + "\n")

            csv_row = {k: record.get(k) for k in csv_columns}
            if not no_rag_only:
                csv_row["rag_top_ids"] = ",".join(map(str, record.get("rag_top_ids") or []))
            csv_writer.writerow(csv_row)

            print(f"[comparison] {idx}/{len(rows)} done")

    rag_accuracy = (rag_name_matches / total_with_target) if total_with_target and not no_rag_only else None
    no_rag_hit_rate = (no_rag_text_hits / total_with_target) if total_with_target else None

    summary = {
        "timestamp": timestamp,
        "no_rag_only": no_rag_only,
        "input_csv": str(input_csv),
        "output_jsonl": str(jsonl_path),
        "output_csv": str(csv_path),
        "total_rows": len(rows),
        "total_with_target_id": total_with_target,
        "no_rag_text_hit_rate": no_rag_hit_rate,
        "no_rag_text_hits": no_rag_text_hits,
    }
    if not no_rag_only:
        summary["name_top_k"] = name_top_k
        summary["max_iterations"] = max_iterations
        summary["rag_name_accuracy"] = rag_accuracy
        summary["rag_name_matches"] = rag_name_matches

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    if not no_rag_only:
        print(f"[comparison] RAG name accuracy (top-{name_top_k}): {rag_accuracy}")
    print(f"[comparison] No-RAG text hit rate: {no_rag_hit_rate}")
    print(f"[comparison] Results JSONL: {jsonl_path}")
    print(f"[comparison] Results CSV: {csv_path}")
    print(f"[comparison] Summary: {summary_path}")


def main() -> None:
    default_csv = PROJECT_ROOT / "tests" / "test_set_input.csv"
    parser = argparse.ArgumentParser(description="Batch comparison: RAG vs No-RAG.")
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=default_csv,
        help="Input CSV (same format as test_RAG). Default: tests/test_set_input.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
        help="Output directory for JSONL and summary.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max rows (0 = all).")
    parser.add_argument("--name-top-k", type=int, default=5, help="Top-K for RAG name match.")
    parser.add_argument("--max-iterations", type=int, default=5, help="RAG agent max iterations.")
    parser.add_argument(
        "--no-rag-only",
        action="store_true",
        help="Run only the no-RAG baseline (skip RAG pipeline).",
    )
    args = parser.parse_args()

    input_csv = Path(args.input_csv).resolve()
    if not input_csv.exists():
        sys.exit(f"Input CSV not found: {input_csv}")

    asyncio.run(
        run_batch(
            input_csv=input_csv,
            output_dir=args.output_dir,
            limit=args.limit,
            name_top_k=args.name_top_k,
            max_iterations=args.max_iterations,
            no_rag_only=args.no_rag_only,
        )
    )


if __name__ == "__main__":
    main()
