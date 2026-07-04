#!/usr/bin/env python3
"""
Compare TourRAG retrieval against direct BM25 and No-RAG baselines.

Example:
    python experiments/bm25_comparison/evaluate_retrieval.py \
        --input tests/datasets/test_set_expanded_500.csv \
        --methods bm25,tourrag_sql,no_rag,no_rag_list \
        --top-k 1,3,5,10 \
        --limit 100
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.schemas.query import GeoHints, QueryIntent  # noqa: E402
from app.services.database import db  # noqa: E402
from app.tools.sql_search_tool import get_sql_search_tool  # noqa: E402
from experiments.no_rag_baseline import run_no_rag_async, run_no_rag_list_async  # noqa: E402
from experiments.bm25_comparison.bm25_baseline import (  # noqa: E402
    BM25Document,
    BM25Index,
    build_document_text,
)


@dataclass
class TestCase:
    query_id: str
    query: str
    target_id: int
    raw: Dict[str, str]


def build_query_from_row(row: Dict[str, str]) -> str:
    explicit_query = (row.get("query_text") or "").strip()
    if explicit_query:
        return explicit_query

    history_summary = (row.get("history_summary") or "").strip()
    base_name = (row.get("viewpoint_base_name") or "").strip()
    season_info_raw = (row.get("season_info") or "").strip()
    season_hint = ""
    if season_info_raw:
        try:
            season_info = json.loads(season_info_raw)
            season_hint = season_info.get("season", "") or ""
        except json.JSONDecodeError:
            season_hint = ""

    query = history_summary or base_name
    if season_hint and season_hint != "unknown":
        query = f"{query}. best season {season_hint}"
    return query


def load_test_cases(input_csv: Path, limit: int = 0) -> List[TestCase]:
    cases: List[TestCase] = []
    with input_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            target_raw = (row.get("target_id") or row.get("viewpoint_base_name") or "").strip()
            if not target_raw.isdigit():
                continue
            cases.append(
                TestCase(
                    query_id=str(row.get("query_id") or idx),
                    query=build_query_from_row(row),
                    target_id=int(target_raw),
                    raw=row,
                )
            )
            if limit and len(cases) >= limit:
                break
    return cases


def load_corpus(limit: int = 0) -> List[BM25Document]:
    sql = """
        SELECT
            e.viewpoint_id,
            e.name_primary,
            e.name_variants::text AS name_variants,
            e.category_norm,
            e.popularity,
            w.wikipedia_title,
            w.extract_text,
            w.sections::text AS sections
        FROM viewpoint_entity e
        LEFT JOIN viewpoint_wiki w ON e.viewpoint_id = w.viewpoint_id
        WHERE
            e.name_primary IS NOT NULL
            OR w.extract_text IS NOT NULL
            OR w.sections IS NOT NULL
        ORDER BY e.viewpoint_id
    """
    params: List[object] = []
    if limit:
        sql += " LIMIT %s"
        params.append(limit)

    with db.get_cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    documents: List[BM25Document] = []
    for row in rows:
        documents.append(
            BM25Document(
                viewpoint_id=row["viewpoint_id"],
                text=build_document_text(row),
                metadata={
                    "name_primary": row.get("name_primary"),
                    "category_norm": row.get("category_norm"),
                    "popularity": row.get("popularity") or 0.0,
                },
            )
        )
    return documents


def infer_simple_intent(query: str) -> QueryIntent:
    lowered = query.lower()
    valid_categories = [
        "mountain",
        "lake",
        "temple",
        "museum",
        "park",
        "coast",
        "cityscape",
        "monument",
        "bridge",
        "palace",
        "tower",
        "cave",
        "waterfall",
        "valley",
        "island",
    ]
    seasons = ["spring", "summer", "autumn", "winter"]
    query_tags = [tag for tag in valid_categories if tag in lowered]
    season_hint = next((season for season in seasons if season in lowered), "unknown")
    return QueryIntent(
        name_candidates=[],
        query_tags=query_tags,
        season_hint=season_hint,
        scene_hints=[],
        geo_hints=GeoHints(),
        confidence_notes=["Simple non-LLM intent used for reproducible comparison."],
    )


def extract_explicit_name(query: str) -> Optional[str]:
    """Extract an explicit attraction name from common generated query templates."""
    patterns = [
        r"Identify the tourist attraction named\s+(.+?)[\.\。]?$",
        r"Identifica la atraccion turistica llamada\s+(.+?)[\.\。]?$",
        r"请识别名为[“\"']?(.+?)[”\"']?的旅游景点[。\.\s]*$",
        r"[「'](.+?)[」']という観光地を特定してください[。\.\s]*$",
        r"['\"](.+?)['\"]이라는 관광지를 식별해 주세요[。\.\s]*$",
        r"(.+?)\s+नाम वाले पर्यटन स्थल की पहचान करें[।\.\s]*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            name = match.group(1).strip(" .。।\"'“”「」")
            return name or None
    return None


def candidates_from_sql_result(
    result: Dict[str, object],
    top_k: int,
    method: str,
) -> List[Dict[str, object]]:
    candidates = result.get("candidates") or []
    return [
        {
            "viewpoint_id": candidate["viewpoint_id"],
            "score": candidate.get("match_confidence")
            or candidate.get("name_score")
            or candidate.get("category_score")
            or 0.0,
            "name_primary": candidate.get("name_primary"),
            "category_norm": candidate.get("category_norm"),
            "method": method,
        }
        for candidate in candidates[:top_k]
    ]


def normalize_name_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9\u3040-\u30ff\u3400-\u9fff\u0400-\u04ff\uac00-\ud7af]+", " ", normalized)
    normalized = re.sub(r"\b(?:the|a|an|la|le|les|el|los|las|il|lo|der|die|das)\b", " ", normalized)
    return " ".join(normalized.split())


def iter_name_values(name_primary: object, name_variants: object) -> Iterable[str]:
    if name_primary:
        yield str(name_primary)
    variants = name_variants
    if isinstance(variants, str):
        try:
            variants = json.loads(variants)
        except json.JSONDecodeError:
            variants = {}
    if isinstance(variants, dict):
        for value in variants.values():
            if value:
                yield str(value)
    elif isinstance(variants, list):
        for value in variants:
            if value:
                yield str(value)


@lru_cache(maxsize=1)
def local_name_index() -> Dict[str, Dict[str, object]]:
    sql = """
        SELECT viewpoint_id, name_primary, name_variants
        FROM viewpoint_entity
        WHERE name_primary IS NOT NULL OR name_variants IS NOT NULL
    """
    index: Dict[str, Dict[str, object]] = {}
    with db.get_cursor() as cursor:
        cursor.execute(sql)
        for row in cursor.fetchall():
            for name in iter_name_values(row.get("name_primary"), row.get("name_variants")):
                key = normalize_name_key(name)
                if not key:
                    continue
                index.setdefault(
                    key,
                    {
                        "viewpoint_id": row["viewpoint_id"],
                        "name_primary": row.get("name_primary"),
                        "category_norm": None,
                    },
                )
    return index


def local_name_fallback(answer: str, method: str) -> List[Dict[str, object]]:
    key = normalize_name_key(answer)
    if not key:
        return []

    index = local_name_index()
    match = index.get(key)
    if not match:
        return []
    return [
        {
            "viewpoint_id": match["viewpoint_id"],
            "score": 0.95,
            "name_primary": match.get("name_primary"),
            "category_norm": match.get("category_norm"),
            "method": f"{method}_local_name_fallback",
        }
    ]


def map_answer_name(answer: str, top_k: int, method: str) -> List[Dict[str, object]]:
    sql_tool = get_sql_search_tool()
    name_result = sql_tool.search_by_name(answer, top_n=top_k)
    candidates = candidates_from_sql_result(name_result, top_k, method)
    if candidates:
        return candidates
    return local_name_fallback(answer, method)


def run_tourrag_sql(query: str, top_k: int) -> List[Dict[str, object]]:
    sql_tool = get_sql_search_tool()

    explicit_name = extract_explicit_name(query)
    if explicit_name:
        name_result = sql_tool.search_by_name(explicit_name, top_n=top_k)
        candidates = name_result.get("candidates") or []
        if candidates:
            return candidates_from_sql_result(
                name_result,
                top_k,
                "tourrag_sql_name",
            )

    history_terms = [
        term
        for term in query.replace(",", " ").replace(".", " ").split()
        if len(term.strip()) > 2
    ][:12]
    history_result = sql_tool.search_by_history_terms(history_terms, top_n=top_k)

    candidates = history_result.get("candidates") or []
    if candidates:
        return candidates_from_sql_result(
            history_result,
            top_k,
            "tourrag_sql_history_fts",
        )

    intent = infer_simple_intent(query)
    if intent.query_tags:
        fallback = sql_tool.search_by_category(intent.query_tags[0], top_n=top_k)
    else:
        fallback = sql_tool.search_popular(top_n=top_k)
    return candidates_from_sql_result(
        fallback,
        top_k,
        "tourrag_sql_local_fallback",
    )


async def run_no_rag(query: str, top_k: int, model: Optional[str]) -> List[Dict[str, object]]:
    """
    Run pure LLM No-RAG, then map its name-only answer to local IDs for evaluation.

    The LLM does not receive database/tool access. The local name lookup is only an
    evaluation adapter so No-RAG can be scored with the same ranked-ID metrics.
    """
    result = await run_no_rag_async(query, model=model, language="auto")
    answer = (result.get("answer") or "").strip()
    if not answer:
        return []

    candidates = map_answer_name(
        answer,
        top_k,
        "no_rag_name_adapter",
    )
    for candidate in candidates:
        candidate["no_rag_answer"] = answer
        candidate["no_rag_model"] = result.get("model")
    if not candidates:
        candidates.append(
            {
                "viewpoint_id": -1,
                "score": 0.0,
                "name_primary": None,
                "category_norm": None,
                "method": "no_rag_name_adapter",
                "no_rag_answer": answer,
                "no_rag_model": result.get("model"),
            }
        )
    return candidates


async def run_no_rag_list(query: str, top_k: int, model: Optional[str]) -> List[Dict[str, object]]:
    """
    Run pure LLM No-RAG as a ranked top-N name prior, then map each guess to one local ID.

    Each guessed name is mapped with top_n=1 so the metric reflects the LLM's
    candidate list rather than expanding one guess into many database candidates.
    """
    result = await run_no_rag_list_async(query, model=model, language="auto", limit=top_k)
    answers = result.get("answers") or []
    if not answers:
        return []

    candidates: List[Dict[str, object]] = []
    seen_ids = set()
    for guess_rank, answer in enumerate(answers, start=1):
        name = str(answer).strip()
        if not name:
            continue
        mapped = map_answer_name(
            name,
            1,
            "no_rag_list_name_adapter",
        )
        if not mapped:
            candidates.append(
                {
                    "viewpoint_id": -guess_rank,
                    "score": 0.0,
                    "name_primary": None,
                    "category_norm": None,
                    "method": "no_rag_list_name_adapter",
                    "no_rag_answer": name,
                    "no_rag_guess_rank": guess_rank,
                    "no_rag_model": result.get("model"),
                }
            )
            continue
        candidate = mapped[0]
        viewpoint_id = int(candidate["viewpoint_id"])
        if viewpoint_id in seen_ids:
            continue
        seen_ids.add(viewpoint_id)
        candidate["no_rag_answer"] = name
        candidate["no_rag_guess_rank"] = guess_rank
        candidate["no_rag_model"] = result.get("model")
        candidate["no_rag_raw_answer"] = result.get("raw_answer")
        candidates.append(candidate)
        if len(candidates) >= top_k:
            break
    return candidates


def error_result(method: str, error: Exception) -> List[Dict[str, object]]:
    """Represent a failed method call as an empty ranked result for batch robustness."""
    return [
        {
            "viewpoint_id": -1,
            "score": 0.0,
            "name_primary": None,
            "category_norm": None,
            "method": f"{method}_error",
            "error": f"{type(error).__name__}: {error}",
        }
    ]


async def retry_async(
    label: str,
    factory: Callable[[], Awaitable[List[Dict[str, object]]]],
    attempts: int,
    delay_seconds: float,
) -> List[Dict[str, object]]:
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return await factory()
        except Exception as exc:
            last_error = exc
            print(f"[{label}] attempt {attempt}/{attempts} failed: {type(exc).__name__}: {exc}")
            if attempt < attempts:
                await asyncio.sleep(delay_seconds)
    assert last_error is not None
    return error_result(label, last_error)


async def run_tourrag_agent(query: str, top_k: int, max_iterations: int) -> List[Dict[str, object]]:
    from app.services.agent_service import get_agent_service

    agent = get_agent_service()
    result = await agent.answer_query(
        query,
        language="auto",
        max_iterations=max_iterations,
    )

    def append_unique(
        ranked: List[Dict[str, object]],
        seen: set,
        candidate: Dict[str, object],
        score_keys: Sequence[str],
    ) -> None:
        viewpoint_id = candidate.get("viewpoint_id")
        if isinstance(viewpoint_id, int) and viewpoint_id not in seen:
            seen.add(viewpoint_id)
            score = 0.0
            for key in score_keys:
                value = candidate.get(key)
                if isinstance(value, (int, float)):
                    score = float(value)
                    break
            ranked.append(
                {
                    "viewpoint_id": viewpoint_id,
                    "score": score,
                    "name_primary": candidate.get("name_primary"),
                    "category_norm": candidate.get("category_norm"),
                    "method": "tourrag_agent",
                }
            )

    # Prefer the final explicit reranking result. Earlier search tool calls are
    # first-stage recall and can otherwise steal the top_k slots. If the agent
    # fetched details for a candidate, treat that as its final selection because
    # the natural-language answer is based on that viewpoint.
    seen = set()
    ranked: List[Dict[str, object]] = []
    for tool_call in reversed(result.get("tool_calls") or []):
        if tool_call.get("tool") != "get_viewpoint_details":
            continue
        payload = tool_call.get("result") or {}
        append_unique(ranked, seen, payload, ("match_confidence", "hybrid_score", "name_score", "popularity"))
        if ranked:
            break

    for tool_call in reversed(result.get("tool_calls") or []):
        if tool_call.get("tool") != "rank_and_explain_results":
            continue
        payload = tool_call.get("result") or {}
        reranked = payload.get("results") or []
        if reranked:
            for candidate in reranked:
                append_unique(ranked, seen, candidate, ("match_confidence", "hybrid_score", "name_score"))
                if len(ranked) >= top_k:
                    return ranked
            if ranked:
                return ranked

    for tool_call in result.get("tool_calls") or []:
        payload = tool_call.get("result") or {}
        candidates = payload.get("candidates") or payload.get("results") or []
        for candidate in candidates:
            append_unique(ranked, seen, candidate, ("match_confidence", "hybrid_score", "name_score"))
            if len(ranked) >= top_k:
                return ranked
    return ranked


def reciprocal_rank(ranked_ids: Sequence[int], target_id: int) -> float:
    for idx, viewpoint_id in enumerate(ranked_ids, start=1):
        if viewpoint_id == target_id:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[int], target_id: int, k: int) -> float:
    for idx, viewpoint_id in enumerate(ranked_ids[:k], start=1):
        if viewpoint_id == target_id:
            return 1.0 / math.log2(idx + 1)
    return 0.0


def summarize(rows: List[Dict[str, object]], top_ks: Sequence[int]) -> List[Dict[str, object]]:
    by_method: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        by_method.setdefault(str(row["method"]), []).append(row)

    summary: List[Dict[str, object]] = []
    for method, method_rows in sorted(by_method.items()):
        total = len(method_rows)
        record: Dict[str, object] = {"method": method, "queries": total}
        mrr_sum = sum(float(row["rr"]) for row in method_rows)
        record["mrr"] = mrr_sum / total if total else 0.0
        for k in top_ks:
            hits = sum(1 for row in method_rows if int(row.get(f"rank_at_{k}") or 0) > 0)
            record[f"hit@{k}"] = hits / total if total else 0.0
            record[f"precision@{k}"] = hits / (total * k) if total else 0.0
            record[f"recall@{k}"] = hits / total if total else 0.0
            record[f"ndcg@{k}"] = (
                sum(float(row.get(f"ndcg@{k}") or 0.0) for row in method_rows) / total
                if total
                else 0.0
            )
        summary.append(record)
    return summary


async def evaluate(args: argparse.Namespace) -> None:
    input_csv = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    top_ks = [int(value) for value in args.top_k.split(",") if value.strip()]
    max_k = max(top_ks)
    methods = [method.strip() for method in args.methods.split(",") if method.strip()]
    cases = load_test_cases(input_csv, limit=args.limit)
    if not cases:
        raise RuntimeError(f"No usable test cases found in {input_csv}")

    bm25_index: Optional[BM25Index] = None
    if "bm25" in methods:
        documents = load_corpus(limit=args.corpus_limit)
        bm25_index = BM25Index(documents, k1=args.bm25_k1, b=args.bm25_b)
        print(f"BM25 corpus loaded: {len(documents)} documents")

    detail_rows: List[Dict[str, object]] = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = output_dir / f"retrieval_compare_{timestamp}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for idx, case in enumerate(cases, start=1):
            print(f"[{idx}/{len(cases)}] {case.query_id}: {case.query[:80]}")
            for method in methods:
                if method == "bm25":
                    assert bm25_index is not None
                    results = bm25_index.search(case.query, top_k=max_k)
                elif method == "tourrag_sql":
                    results = run_tourrag_sql(case.query, top_k=max_k)
                elif method == "no_rag":
                    results = await retry_async(
                        "no_rag",
                        lambda: run_no_rag(
                            case.query,
                            top_k=max_k,
                            model=args.no_rag_model,
                        ),
                        attempts=args.method_retries,
                        delay_seconds=args.retry_delay,
                    )
                elif method == "no_rag_list":
                    results = await retry_async(
                        "no_rag_list",
                        lambda: run_no_rag_list(
                            case.query,
                            top_k=max_k,
                            model=args.no_rag_model,
                        ),
                        attempts=args.method_retries,
                        delay_seconds=args.retry_delay,
                    )
                elif method == "tourrag_agent":
                    results = await retry_async(
                        "tourrag_agent",
                        lambda: run_tourrag_agent(
                            case.query,
                            top_k=max_k,
                            max_iterations=args.max_iterations,
                        ),
                        attempts=args.method_retries,
                        delay_seconds=args.retry_delay,
                    )
                else:
                    raise ValueError(f"Unknown method: {method}")

                ranked_ids = [int(row["viewpoint_id"]) for row in results]
                rank = (
                    ranked_ids.index(case.target_id) + 1
                    if case.target_id in ranked_ids
                    else 0
                )
                detail = {
                    "query_id": case.query_id,
                    "query": case.query,
                    "target_id": case.target_id,
                    "method": method,
                    "rank": rank,
                    "rr": reciprocal_rank(ranked_ids, case.target_id),
                    "top_results": results,
                }
                for k in top_ks:
                    detail[f"rank_at_{k}"] = rank if 0 < rank <= k else 0
                    detail[f"ndcg@{k}"] = ndcg_at_k(ranked_ids, case.target_id, k)
                detail_rows.append(detail)
                f.write(json.dumps(detail, ensure_ascii=False) + "\n")

    summary = summarize(detail_rows, top_ks)
    summary_path = output_dir / f"summary_{timestamp}.csv"
    fieldnames = list(summary[0].keys())
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary)

    print(f"Details: {jsonl_path}")
    print(f"Summary: {summary_path}")
    for row in summary:
        print(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="tests/datasets/test_set_expanded_500.csv")
    parser.add_argument("--output-dir", default="experiments/bm25_comparison/results")
    parser.add_argument("--methods", default="bm25,tourrag_sql")
    parser.add_argument("--top-k", default="1,3,5,10")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--corpus-limit", type=int, default=0)
    parser.add_argument("--bm25-k1", type=float, default=1.5)
    parser.add_argument("--bm25-b", type=float, default=0.75)
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--no-rag-model", default=None, help="OpenAI model for no_rag (default: app settings).")
    parser.add_argument("--method-retries", type=int, default=3, help="Retries for OpenAI-backed methods.")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Delay between method retries in seconds.")
    return parser.parse_args()


def main() -> None:
    asyncio.run(evaluate(parse_args()))


if __name__ == "__main__":
    main()
