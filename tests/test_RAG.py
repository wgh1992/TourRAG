#!/usr/bin/env python3
"""
Batch test for RAG with bbox IoU + accuracy.
"""
import argparse
import asyncio
import base64
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from openai import OpenAI

from app.config import settings
from app.schemas.query import ExtractQueryIntentInput, UserImageInput
from app.tools.extract_query_intent import get_extract_query_intent_tool
from app.tools.sql_search_tool import get_sql_search_tool


def load_image_data_url(image_path: Path) -> str:
    image_bytes = image_path.read_bytes()
    ext = image_path.suffix.lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    mime_type = mime_types.get(ext, "image/jpeg")
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def parse_bbox(raw: List[float]) -> Tuple[float, float, float, float]:
    if len(raw) != 4:
        raise ValueError("bbox must have 4 numbers: min_x min_y max_x max_y")
    min_x, min_y, max_x, max_y = raw
    if min_x > max_x:
        min_x, max_x = max_x, min_x
    if min_y > max_y:
        min_y, max_y = max_y, min_y
    return min_x, min_y, max_x, max_y


def compute_iou(
    bbox_a: Tuple[float, float, float, float],
    bbox_b: Tuple[float, float, float, float]
) -> float:
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter_area
    if denom == 0:
        return 0.0
    return inter_area / denom


def request_bbox_from_llm(image_path: Path, model: str) -> Optional[List[float]]:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    image_data = load_image_data_url(image_path)
    system_prompt = (
        "You are a vision assistant that outputs a single JSON object. "
        "Return a bounding box for the main attraction in the image. "
        "The bbox must be normalized [min_x, min_y, max_x, max_y] in [0,1]. "
        "If you cannot determine it, return {\"bbox\": null}."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Return bbox JSON only."},
                    {"type": "image_url", "image_url": {"url": image_data}},
                ],
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    raw = response.choices[0].message.content
    data = json.loads(raw)
    bbox = data.get("bbox")
    if not bbox or len(bbox) != 4:
        return None
    return bbox


def collect_top_candidate_ids(tool_calls: List[Dict], top_k: int) -> List[int]:
    """
    Collect top candidate IDs from all search and ranking tool calls.
    
    Priority order:
    1. rank_and_explain_results (highest priority - these are already ranked)
    2. Search tool results (in order of appearance)
    """
    ordered_ids: List[int] = []
    seen = set()
    
    # First, collect from rank_and_explain_results (highest priority)
    for tool_call in tool_calls or []:
        tool_name = tool_call.get("tool")
        if tool_name == "rank_and_explain_results":
            payload = tool_call.get("result") or {}
            # Check candidates field first (contains original candidates with scores)
            candidates = payload.get("candidates") or []
            # Fallback to results field if candidates not available
            if not candidates:
                results = payload.get("results") or []
                candidates = [{"viewpoint_id": r.get("viewpoint_id")} for r in results]
            
            for cand in candidates[:top_k]:
                cid = cand.get("viewpoint_id")
                if isinstance(cid, int) and cid not in seen:
                    ordered_ids.append(cid)
                    seen.add(cid)
    
    # Then collect from search tools (in order of appearance)
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
    
    return ordered_ids[:top_k]  # Ensure we only return top_k


async def run_extract_and_search(query: str, image_path: Optional[Path], top_n: int) -> None:
    tool = get_extract_query_intent_tool()
    user_images = []
    if image_path:
        user_images.append(UserImageInput(image_id=str(image_path)))
    input_data = ExtractQueryIntentInput(
        user_text=query,
        user_images=user_images,
        language="auto"
    )
    intent = await tool.extract(input_data)
    print("query_intent:", intent.query_intent.model_dump())

    sql_tool = get_sql_search_tool()
    result = sql_tool.search_with_llm_sql(intent.query_intent, top_n=top_n)
    print("sql_search_count:", result.get("count"))
    for cand in (result.get("candidates") or [])[:10]:
        print(f"- {cand['viewpoint_id']}: {cand['name_primary']} ({cand.get('category_norm')})")


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


async def run_batch_rag(
    input_csv: Path,
    output_jsonl: Path,
    limit: int,
    fixed_bbox: Tuple[float, float, float, float],
    model: str,
    iou_threshold: float,
    max_iterations: int,
    name_top_k: int
) -> None:
    from app.services.agent_service import get_agent_service

    agent = get_agent_service()
    rows = []
    with input_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            if limit and len(rows) >= limit:
                break

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as f:
        total_bbox = 0
        passed_bbox = 0
        iou_sum = 0.0
        total_name = 0
        passed_name = 0
        total_combined = 0
        passed_combined = 0
        
        # Track accuracy at each iteration step
        iteration_stats: Dict[int, Dict[str, int]] = {}  # {iteration: {"total": X, "passed": Y}} for top_k
        iteration_stats_top1: Dict[int, Dict[str, int]] = {}  # {iteration: {"total": X, "passed": Y}} for top1
        iteration_stats_top3: Dict[int, Dict[str, int]] = {}  # {iteration: {"total": X, "passed": Y}} for top3
        iteration_stats_top5: Dict[int, Dict[str, int]] = {}  # {iteration: {"total": X, "passed": Y}} for top5
        found_at_iteration_stats: Dict[int, int] = {}  # Track how many queries found target at each iteration (top_k)
        found_at_top1_iteration_stats: Dict[int, int] = {}  # Track how many queries found target in top1 at each iteration
        found_at_top3_iteration_stats: Dict[int, int] = {}  # Track how many queries found target in top3 at each iteration
        found_at_top5_iteration_stats: Dict[int, int] = {}  # Track how many queries found target in top5 at each iteration
        stopped_at_iteration_stats: Dict[int, int] = {}  # Track how many queries stopped at each iteration
        stopped_at_iteration_match_stats: Dict[int, int] = {}  # Track how many queries stopped at each iteration with match (top_k)
        
        # Track final iteration accuracy for top1, top3, top5, and top_k
        final_top1_matches = 0  # Count of queries with target in top1 at final iteration
        final_top3_matches = 0  # Count of queries with target in top3 at final iteration
        final_top5_matches = 0  # Count of queries with target in top5 at final iteration
        final_topk_matches = 0  # Count of queries with target in top_k at final iteration
        total_with_target = 0  # Total queries with valid target_id  # Track how many queries stopped at each iteration
        
        for idx, row in enumerate(rows, start=1):
            query = build_query_from_row(row)
            result = await agent.answer_query(
                query,
                language="auto",
                max_iterations=max_iterations
            )
            image_path = (row.get("image_path") or "").strip()
            image_file = (Path(image_path).resolve() if image_path else None)
            base_name = (row.get("viewpoint_base_name") or "").strip()
            target_id = int(base_name) if base_name.isdigit() else None
            bbox_pred = None
            iou = None
            passed_iou = None
            if image_file and image_file.exists():
                bbox_pred = request_bbox_from_llm(image_file, model)
                if bbox_pred:
                    pred_bbox = parse_bbox([float(v) for v in bbox_pred])
                    iou = compute_iou(pred_bbox, fixed_bbox)
                    passed_iou = iou >= iou_threshold
                    total_bbox += 1
                    iou_sum += iou
                    if passed_iou:
                        passed_bbox += 1

            name_match = None
            top_candidate_ids: List[int] = []
            if target_id is not None:
                total_name += 1
                top_candidate_ids = collect_top_candidate_ids(
                    result.get("tool_calls", []) or [],
                    name_top_k
                )
                name_match = target_id in top_candidate_ids
                if name_match:
                    passed_name += 1

            combined_pass = None
            if passed_iou is not None and name_match is not None:
                total_combined += 1
                combined_pass = passed_iou and name_match
                if combined_pass:
                    passed_combined += 1
            
            # Calculate accuracy at each iteration step
            iteration_accuracies = []
            iteration_snapshots = result.get("iteration_snapshots", [])
            found_at_iteration = None  # Track when the target was first found (in top_k)
            found_at_top1_iteration = None  # Track when the target was first found in top1
            found_at_top3_iteration = None  # Track when the target was first found in top3
            found_at_top5_iteration = None  # Track when the target was first found in top5
            if target_id is not None:
                # Build maps of iteration -> match for all iterations (top_k, top1, top3, top5)
                iteration_match_map: Dict[int, bool] = {}  # top_k
                iteration_match_map_top1: Dict[int, bool] = {}  # top1
                iteration_match_map_top3: Dict[int, bool] = {}  # top3
                iteration_match_map_top5: Dict[int, bool] = {}  # top5
                
                # Process all snapshots in order
                for snapshot in iteration_snapshots:
                    iter_num = snapshot.get("iteration", 0)
                    snapshot_tool_calls = snapshot.get("tool_calls", [])
                    
                    # Collect top candidate IDs for different K values
                    snapshot_top_candidate_ids = collect_top_candidate_ids(
                        snapshot_tool_calls,
                        name_top_k
                    )
                    snapshot_top1_candidate_ids = collect_top_candidate_ids(
                        snapshot_tool_calls,
                        1
                    )
                    snapshot_top3_candidate_ids = collect_top_candidate_ids(
                        snapshot_tool_calls,
                        3
                    )
                    snapshot_top5_candidate_ids = collect_top_candidate_ids(
                        snapshot_tool_calls,
                        5
                    )
                    
                    snapshot_name_match = target_id in snapshot_top_candidate_ids
                    snapshot_top1_match = target_id in snapshot_top1_candidate_ids
                    snapshot_top3_match = target_id in snapshot_top3_candidate_ids
                    snapshot_top5_match = target_id in snapshot_top5_candidate_ids
                    
                    # Track the first iteration where target was found (in top_k)
                    if snapshot_name_match and found_at_iteration is None:
                        found_at_iteration = iter_num
                    
                    # Track the first iteration where target was found in top1
                    if snapshot_top1_match and found_at_top1_iteration is None:
                        found_at_top1_iteration = iter_num
                    
                    # Track the first iteration where target was found in top3
                    if snapshot_top3_match and found_at_top3_iteration is None:
                        found_at_top3_iteration = iter_num
                    
                    # Track the first iteration where target was found in top5
                    if snapshot_top5_match and found_at_top5_iteration is None:
                        found_at_top5_iteration = iter_num
                    
                    iteration_match_map[iter_num] = snapshot_name_match
                    iteration_match_map_top1[iter_num] = snapshot_top1_match
                    iteration_match_map_top3[iter_num] = snapshot_top3_match
                    iteration_match_map_top5[iter_num] = snapshot_top5_match
                    
                    iteration_accuracies.append({
                        "iteration": iter_num,
                        "name_match": snapshot_name_match,
                        "top_candidate_ids": snapshot_top_candidate_ids
                    })
                
                # Once found, all subsequent iterations should be marked as found
                # This is the key fix: if found at iteration N, iterations N, N+1, ..., max_iterations are all "found"
                # Ensure all iterations from 1 to max_iterations are accounted for
                # Helper function to propagate match status
                def propagate_match_status(match_map: Dict[int, bool], found_at: Optional[int], iter_num: int) -> bool:
                    if iter_num not in match_map:
                        # No snapshot for this iteration
                        if found_at is not None and iter_num >= found_at:
                            # Target was found at an earlier iteration, mark this iteration as found
                            return True
                        else:
                            # Query finished before this iteration or not found yet
                            # Use the last known status from snapshots (before query ended)
                            # If target was found at an earlier iteration, all subsequent iterations should be True
                            if found_at is not None and iter_num > found_at:
                                return True
                            else:
                                last_known_match = False
                                for prev_iter in range(iter_num - 1, 0, -1):
                                    if prev_iter in match_map:
                                        last_known_match = match_map[prev_iter]
                                        break
                                return last_known_match
                    else:
                        # Has snapshot for this iteration
                        # But if target was found at an earlier iteration, this iteration should also be True
                        if found_at is not None and iter_num >= found_at:
                            return True
                        return match_map[iter_num]
                
                for iter_num in range(1, max_iterations + 1):
                    # Propagate match status for top_k, top1, top3, and top5
                    iteration_match_map[iter_num] = propagate_match_status(
                        iteration_match_map, found_at_iteration, iter_num
                    )
                    iteration_match_map_top1[iter_num] = propagate_match_status(
                        iteration_match_map_top1, found_at_top1_iteration, iter_num
                    )
                    iteration_match_map_top3[iter_num] = propagate_match_status(
                        iteration_match_map_top3, found_at_top3_iteration, iter_num
                    )
                    iteration_match_map_top5[iter_num] = propagate_match_status(
                        iteration_match_map_top5, found_at_top5_iteration, iter_num
                    )
                    
                    # Accumulate statistics for this iteration (top_k)
                    if iter_num not in iteration_stats:
                        iteration_stats[iter_num] = {"total": 0, "passed": 0}
                    iteration_stats[iter_num]["total"] += 1
                    if iteration_match_map[iter_num]:
                        iteration_stats[iter_num]["passed"] += 1
                    
                    # Accumulate statistics for this iteration (top1)
                    if iter_num not in iteration_stats_top1:
                        iteration_stats_top1[iter_num] = {"total": 0, "passed": 0}
                    iteration_stats_top1[iter_num]["total"] += 1
                    if iteration_match_map_top1[iter_num]:
                        iteration_stats_top1[iter_num]["passed"] += 1
                    
                    # Accumulate statistics for this iteration (top3)
                    if iter_num not in iteration_stats_top3:
                        iteration_stats_top3[iter_num] = {"total": 0, "passed": 0}
                    iteration_stats_top3[iter_num]["total"] += 1
                    if iteration_match_map_top3[iter_num]:
                        iteration_stats_top3[iter_num]["passed"] += 1
                    
                    # Accumulate statistics for this iteration (top5)
                    if iter_num not in iteration_stats_top5:
                        iteration_stats_top5[iter_num] = {"total": 0, "passed": 0}
                    iteration_stats_top5[iter_num]["total"] += 1
                    if iteration_match_map_top5[iter_num]:
                        iteration_stats_top5[iter_num]["passed"] += 1
                
                # Track which iteration the target was found at (top_k)
                if found_at_iteration is not None:
                    if found_at_iteration not in found_at_iteration_stats:
                        found_at_iteration_stats[found_at_iteration] = 0
                    found_at_iteration_stats[found_at_iteration] += 1
                
                # Track which iteration the target was first found in top1
                if found_at_top1_iteration is not None:
                    if found_at_top1_iteration not in found_at_top1_iteration_stats:
                        found_at_top1_iteration_stats[found_at_top1_iteration] = 0
                    found_at_top1_iteration_stats[found_at_top1_iteration] += 1
                
                # Track which iteration the target was first found in top3
                if found_at_top3_iteration is not None:
                    if found_at_top3_iteration not in found_at_top3_iteration_stats:
                        found_at_top3_iteration_stats[found_at_top3_iteration] = 0
                    found_at_top3_iteration_stats[found_at_top3_iteration] += 1
                
                # Track which iteration the target was first found in top5
                if found_at_top5_iteration is not None:
                    if found_at_top5_iteration not in found_at_top5_iteration_stats:
                        found_at_top5_iteration_stats[found_at_top5_iteration] = 0
                    found_at_top5_iteration_stats[found_at_top5_iteration] += 1
                
                # Check final iteration accuracy (at max_iterations)
                # Track top3 and top5 match status for final iteration
                total_with_target += 1
                
                # Get the last snapshot for max_iterations
                final_snapshot = None
                for snapshot in reversed(iteration_snapshots):
                    if snapshot.get("iteration", 0) == max_iterations:
                        final_snapshot = snapshot
                        break
                
                if final_snapshot:
                    # Use actual data from last snapshot
                    final_tool_calls = final_snapshot.get("tool_calls", [])
                    final_top1_ids = collect_top_candidate_ids(final_tool_calls, 1)
                    final_top3_ids = collect_top_candidate_ids(final_tool_calls, 3)
                    final_top5_ids = collect_top_candidate_ids(final_tool_calls, 5)
                    final_topk_ids = collect_top_candidate_ids(final_tool_calls, name_top_k)
                    
                    if target_id in final_top1_ids:
                        final_top1_matches += 1
                    if target_id in final_top3_ids:
                        final_top3_matches += 1
                    if target_id in final_top5_ids:
                        final_top5_matches += 1
                    if target_id in final_topk_ids:
                        final_topk_matches += 1
                else:
                    # No snapshot for max_iterations, use propagation logic
                    # If found earlier, it should be in final iteration too
                    if found_at_iteration is not None and found_at_iteration <= max_iterations:
                        final_topk_matches += 1
                    if found_at_top5_iteration is not None and found_at_top5_iteration <= max_iterations:
                        final_top5_matches += 1
                    if found_at_top3_iteration is not None and found_at_top3_iteration <= max_iterations:
                        final_top3_matches += 1
                    if found_at_top1_iteration is not None and found_at_top1_iteration <= max_iterations:
                        final_top1_matches += 1
            else:
                # Target not found in any iteration
                found_at_iteration = None
                found_at_top1_iteration = None
                found_at_top3_iteration = None
                found_at_top5_iteration = None
            
            # Track which iteration the query stopped at (when final answer was given)
            stopped_at_iteration = result.get("iterations")
            if stopped_at_iteration is not None:
                if stopped_at_iteration not in stopped_at_iteration_stats:
                    stopped_at_iteration_stats[stopped_at_iteration] = 0
                stopped_at_iteration_stats[stopped_at_iteration] += 1
                
                # Track match status for queries stopped at this iteration (using top_k)
                if target_id is not None:
                    if stopped_at_iteration not in stopped_at_iteration_match_stats:
                        stopped_at_iteration_match_stats[stopped_at_iteration] = 0
                    # Check if target was found at the stopped iteration (using top_k)
                    if found_at_iteration is not None and found_at_iteration <= stopped_at_iteration:
                        stopped_at_iteration_match_stats[stopped_at_iteration] += 1
            
            record = {
                "index": idx,
                "viewpoint_base_name": row.get("viewpoint_base_name"),
                "image_path": row.get("image_path"),
                "query": query,
                "answer": result.get("answer"),
                "tool_calls": result.get("tool_calls"),
                "iterations": result.get("iterations"),
                "iteration_snapshots": iteration_snapshots,
                "iteration_accuracies": iteration_accuracies,
                "found_at_iteration": found_at_iteration,  # Which iteration found the target in top_k (None if not found)
                "found_at_top1_iteration": found_at_top1_iteration,  # Which iteration found the target in top1 (None if not found)
                "found_at_top3_iteration": found_at_top3_iteration,  # Which iteration found the target in top3 (None if not found)
                "found_at_top5_iteration": found_at_top5_iteration,  # Which iteration found the target in top5 (None if not found)
                "stopped_at_iteration": stopped_at_iteration,  # Which iteration the query stopped at
                "bbox_pred": bbox_pred,
                "fixed_bbox": list(fixed_bbox),
                "iou": iou,
                "iou_threshold": iou_threshold,
                "bbox_pass": passed_iou,
                "name_top_k": name_top_k,
                "top_candidate_ids": top_candidate_ids,
                "name_match": name_match,
                "combined_pass": combined_pass,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"[batch] {idx}/{len(rows)} done")

        # Calculate accuracy for each iteration step (top_k)
        iteration_accuracies_summary = {}
        for iter_num in sorted(iteration_stats.keys()):
            stats = iteration_stats[iter_num]
            accuracy = (stats["passed"] / stats["total"]) if stats["total"] > 0 else 0.0
            iteration_accuracies_summary[iter_num] = {
                "total": stats["total"],
                "passed": stats["passed"],
                "accuracy": accuracy
            }
        
        # Calculate accuracy for each iteration step (top1)
        iteration_accuracies_summary_top1 = {}
        for iter_num in sorted(iteration_stats_top1.keys()):
            stats = iteration_stats_top1[iter_num]
            accuracy = (stats["passed"] / stats["total"]) if stats["total"] > 0 else 0.0
            iteration_accuracies_summary_top1[iter_num] = {
                "total": stats["total"],
                "passed": stats["passed"],
                "accuracy": accuracy
            }
        
        # Calculate accuracy for each iteration step (top3)
        iteration_accuracies_summary_top3 = {}
        for iter_num in sorted(iteration_stats_top3.keys()):
            stats = iteration_stats_top3[iter_num]
            accuracy = (stats["passed"] / stats["total"]) if stats["total"] > 0 else 0.0
            iteration_accuracies_summary_top3[iter_num] = {
                "total": stats["total"],
                "passed": stats["passed"],
                "accuracy": accuracy
            }
        
        # Calculate accuracy for each iteration step (top5)
        iteration_accuracies_summary_top5 = {}
        for iter_num in sorted(iteration_stats_top5.keys()):
            stats = iteration_stats_top5[iter_num]
            accuracy = (stats["passed"] / stats["total"]) if stats["total"] > 0 else 0.0
            iteration_accuracies_summary_top5[iter_num] = {
                "total": stats["total"],
                "passed": stats["passed"],
                "accuracy": accuracy
            }
        
        # Calculate distribution of found_at_iteration (top_k)
        found_at_iteration_distribution = {}
        for iter_num in sorted(found_at_iteration_stats.keys()):
            found_at_iteration_distribution[iter_num] = found_at_iteration_stats[iter_num]
        
        # Calculate distribution of found_at_top1_iteration
        found_at_top1_iteration_distribution = {}
        for iter_num in sorted(found_at_top1_iteration_stats.keys()):
            found_at_top1_iteration_distribution[iter_num] = found_at_top1_iteration_stats[iter_num]
        
        # Calculate distribution of found_at_top3_iteration
        found_at_top3_iteration_distribution = {}
        for iter_num in sorted(found_at_top3_iteration_stats.keys()):
            found_at_top3_iteration_distribution[iter_num] = found_at_top3_iteration_stats[iter_num]
        
        # Calculate distribution of found_at_top5_iteration
        found_at_top5_iteration_distribution = {}
        for iter_num in sorted(found_at_top5_iteration_stats.keys()):
            found_at_top5_iteration_distribution[iter_num] = found_at_top5_iteration_stats[iter_num]
        
        # Calculate distribution of stopped_at_iteration
        stopped_at_iteration_distribution = {}
        for iter_num in sorted(stopped_at_iteration_stats.keys()):
            stopped_at_iteration_distribution[iter_num] = stopped_at_iteration_stats[iter_num]
        
        # Calculate average iteration when found (only for queries that found the target)
        avg_found_iteration = None
        if found_at_iteration_stats:
            total_found = sum(found_at_iteration_stats.values())
            weighted_sum = sum(iter_num * count for iter_num, count in found_at_iteration_stats.items())
            avg_found_iteration = weighted_sum / total_found if total_found > 0 else None
        
        # Calculate average iteration when found in top1
        avg_found_top1_iteration = None
        if found_at_top1_iteration_stats:
            total_found_top1 = sum(found_at_top1_iteration_stats.values())
            weighted_sum = sum(iter_num * count for iter_num, count in found_at_top1_iteration_stats.items())
            avg_found_top1_iteration = weighted_sum / total_found_top1 if total_found_top1 > 0 else None
        
        # Calculate average iteration when found in top3
        avg_found_top3_iteration = None
        if found_at_top3_iteration_stats:
            total_found_top3 = sum(found_at_top3_iteration_stats.values())
            weighted_sum = sum(iter_num * count for iter_num, count in found_at_top3_iteration_stats.items())
            avg_found_top3_iteration = weighted_sum / total_found_top3 if total_found_top3 > 0 else None
        
        # Calculate average iteration when found in top5
        avg_found_top5_iteration = None
        if found_at_top5_iteration_stats:
            total_found_top5 = sum(found_at_top5_iteration_stats.values())
            weighted_sum = sum(iter_num * count for iter_num, count in found_at_top5_iteration_stats.items())
            avg_found_top5_iteration = weighted_sum / total_found_top5 if total_found_top5 > 0 else None
        
        # Calculate average iteration when stopped
        avg_stopped_iteration = None
        if stopped_at_iteration_stats:
            total_stopped = sum(stopped_at_iteration_stats.values())
            weighted_sum = sum(iter_num * count for iter_num, count in stopped_at_iteration_stats.items())
            avg_stopped_iteration = weighted_sum / total_stopped if total_stopped > 0 else None
        
        # Calculate final iteration accuracies (top1, top3, top5, top_k)
        final_top1_accuracy = (final_top1_matches / total_with_target) if total_with_target > 0 else None
        final_top3_accuracy = (final_top3_matches / total_with_target) if total_with_target > 0 else None
        final_top5_accuracy = (final_top5_matches / total_with_target) if total_with_target > 0 else None
        final_accuracy = (final_topk_matches / total_with_target) if total_with_target > 0 else None
        
        summary = {
            "iou_threshold": iou_threshold,
            "total_with_bbox": total_bbox,
            "bbox_accuracy": (passed_bbox / total_bbox) if total_bbox else None,
            "avg_iou": (iou_sum / total_bbox) if total_bbox else None,
            "name_top_k": name_top_k,
            "total_with_name": total_name,
            "name_accuracy": (passed_name / total_name) if total_name else None,
            "total_with_iou_and_name": total_combined,
            "combined_accuracy": (passed_combined / total_combined) if total_combined else None,
            "iteration_accuracies": iteration_accuracies_summary,  # Iteration accuracies for top_k
            "iteration_accuracies_top1": iteration_accuracies_summary_top1,  # Iteration accuracies for top1
            "iteration_accuracies_top3": iteration_accuracies_summary_top3,  # Iteration accuracies for top3
            "iteration_accuracies_top5": iteration_accuracies_summary_top5,  # Iteration accuracies for top5
            "found_at_iteration_distribution": found_at_iteration_distribution,  # How many queries found target at each iteration (top_k)
            "avg_found_iteration": avg_found_iteration,  # Average iteration when target was found (top_k)
            "found_at_top1_iteration_distribution": found_at_top1_iteration_distribution,  # How many queries found target in top1 at each iteration
            "avg_found_top1_iteration": avg_found_top1_iteration,  # Average iteration when target was found in top1
            "found_at_top3_iteration_distribution": found_at_top3_iteration_distribution,  # How many queries found target in top3 at each iteration
            "avg_found_top3_iteration": avg_found_top3_iteration,  # Average iteration when target was found in top3
            "found_at_top5_iteration_distribution": found_at_top5_iteration_distribution,  # How many queries found target in top5 at each iteration
            "avg_found_top5_iteration": avg_found_top5_iteration,  # Average iteration when target was found in top5
            "stopped_at_iteration_distribution": stopped_at_iteration_distribution,  # How many queries stopped at each iteration
            "avg_stopped_iteration": avg_stopped_iteration,  # Average iteration when query stopped
            "final_top1_accuracy": final_top1_accuracy,  # Final accuracy at last iteration (top1)
            "final_top3_accuracy": final_top3_accuracy,  # Final accuracy at last iteration (top3)
            "final_top5_accuracy": final_top5_accuracy,  # Final accuracy at last iteration (top5)
            "final_accuracy": final_accuracy,  # Final accuracy at last iteration (top_k)
            "max_iterations": max_iterations,
            "timestamp": datetime.now().isoformat(),
            "output_file": str(output_jsonl)
        }
        f.write(json.dumps({"summary": summary}, ensure_ascii=False) + "\n")
        if total_bbox:
            print(f"[batch] bbox_accuracy={summary['bbox_accuracy']:.4f} avg_iou={summary['avg_iou']:.4f}")
        if total_name:
            print(f"[batch] name_accuracy={summary['name_accuracy']:.4f}")
        if total_combined:
            print(f"[batch] combined_accuracy={summary['combined_accuracy']:.4f}")
        if final_accuracy is not None:
            print(f"[batch] final_accuracy (top{name_top_k})={final_accuracy:.4f}")
        if final_top1_accuracy is not None:
            print(f"[batch] final_top1_accuracy={final_top1_accuracy:.4f}")
        if final_top3_accuracy is not None:
            print(f"[batch] final_top3_accuracy={final_top3_accuracy:.4f}")
        if final_top5_accuracy is not None:
            print(f"[batch] final_top5_accuracy={final_top5_accuracy:.4f}")
        if avg_found_iteration is not None:
            print(f"[batch] avg_found_iteration (top{name_top_k})={avg_found_iteration:.2f}")
        if avg_found_top1_iteration is not None:
            print(f"[batch] avg_found_top1_iteration={avg_found_top1_iteration:.2f}")
        if avg_found_top3_iteration is not None:
            print(f"[batch] avg_found_top3_iteration={avg_found_top3_iteration:.2f}")
        if avg_found_top5_iteration is not None:
            print(f"[batch] avg_found_top5_iteration={avg_found_top5_iteration:.2f}")
        if found_at_iteration_distribution:
            print(f"[batch] Found at iteration distribution (top{name_top_k}):")
            for iter_num in sorted(found_at_iteration_distribution.keys()):
                count = found_at_iteration_distribution[iter_num]
                print(f"[batch]   Iteration {iter_num}: {count} query(ies)")
        if found_at_top1_iteration_distribution:
            print(f"[batch] Found at iteration distribution (top1):")
            for iter_num in sorted(found_at_top1_iteration_distribution.keys()):
                count = found_at_top1_iteration_distribution[iter_num]
                print(f"[batch]   Iteration {iter_num}: {count} query(ies)")
        if found_at_top3_iteration_distribution:
            print(f"[batch] Found at iteration distribution (top3):")
            for iter_num in sorted(found_at_top3_iteration_distribution.keys()):
                count = found_at_top3_iteration_distribution[iter_num]
                print(f"[batch]   Iteration {iter_num}: {count} query(ies)")
        if found_at_top5_iteration_distribution:
            print(f"[batch] Found at iteration distribution (top5):")
            for iter_num in sorted(found_at_top5_iteration_distribution.keys()):
                count = found_at_top5_iteration_distribution[iter_num]
                print(f"[batch]   Iteration {iter_num}: {count} query(ies)")
        # Calculate and print stopped iteration accuracies for all iterations (1 to max_iterations)
        # This shows cumulative accuracy: at iteration N, how many queries that stopped at or before iteration N found the target
        if stopped_at_iteration_distribution or stopped_at_iteration_match_stats:
            print(f"[batch] Iteration accuracies (stop):")
            cumulative_passed = 0  # Cumulative count of queries that stopped and found target
            for iter_num in range(1, max_iterations + 1):
                # Add queries that stopped at this iteration and found target
                if iter_num in stopped_at_iteration_match_stats:
                    cumulative_passed += stopped_at_iteration_match_stats[iter_num]
                # Calculate cumulative accuracy up to this iteration
                stopped_acc = (cumulative_passed / total_name) if total_name > 0 else 0.0
                print(f"[batch]   Iteration {iter_num}: {stopped_acc:.4f} ({cumulative_passed}/{total_name})")
        if avg_stopped_iteration is not None:
            print(f"[batch] avg_stopped_iteration={avg_stopped_iteration:.2f}")
        if iteration_accuracies_summary:
            print(f"[batch] Iteration accuracies (top{name_top_k}):")
            for iter_num in sorted(iteration_accuracies_summary.keys()):
                acc_data = iteration_accuracies_summary[iter_num]
                print(f"[batch]   Iteration {iter_num}: {acc_data['accuracy']:.4f} ({acc_data['passed']}/{acc_data['total']})")
        if iteration_accuracies_summary_top1:
            print(f"[batch] Iteration accuracies (top1):")
            for iter_num in sorted(iteration_accuracies_summary_top1.keys()):
                acc_data = iteration_accuracies_summary_top1[iter_num]
                print(f"[batch]   Iteration {iter_num}: {acc_data['accuracy']:.4f} ({acc_data['passed']}/{acc_data['total']})")
        if iteration_accuracies_summary_top3:
            print(f"[batch] Iteration accuracies (top3):")
            for iter_num in sorted(iteration_accuracies_summary_top3.keys()):
                acc_data = iteration_accuracies_summary_top3[iter_num]
                print(f"[batch]   Iteration {iter_num}: {acc_data['accuracy']:.4f} ({acc_data['passed']}/{acc_data['total']})")
        # Only print top5 if name_top_k is not 5 (to avoid duplicate)
        if iteration_accuracies_summary_top5 and name_top_k != 5:
            print(f"[batch] Iteration accuracies (top5):")
            for iter_num in sorted(iteration_accuracies_summary_top5.keys()):
                acc_data = iteration_accuracies_summary_top5[iter_num]
                print(f"[batch]   Iteration {iter_num}: {acc_data['accuracy']:.4f} ({acc_data['passed']}/{acc_data['total']})")
        
        # Save accuracy results to separate files for easy comparison
        save_accuracy_results(summary, output_jsonl, max_iterations)


def save_accuracy_results(summary: Dict, output_jsonl: Path, max_iterations: int) -> None:
    """
    Save accuracy results to separate CSV and JSON files for easy comparison.
    
    Args:
        summary: Summary dictionary with accuracy metrics
        output_jsonl: Path to the output JSONL file
        max_iterations: Maximum iterations used in this run
    """
    # Create accuracy results directory
    accuracy_dir = output_jsonl.parent / "accuracy_results"
    accuracy_dir.mkdir(parents=True, exist_ok=True)
    
    # Save as JSON
    json_file = accuracy_dir / f"{output_jsonl.stem}_accuracy.json"
    with json_file.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[batch] Accuracy results saved to: {json_file}")
    
    # Save as CSV for easy comparison
    csv_file = accuracy_dir / "accuracy_summary.csv"
    csv_exists = csv_file.exists()
    
    with csv_file.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        
        # Write header if file is new
        if not csv_exists:
            writer.writerow([
                "timestamp",
                "max_iterations",
                "name_top_k",
                "iou_threshold",
                "total_with_name",
                "name_accuracy",
                "total_with_bbox",
                "bbox_accuracy",
                "avg_iou",
                "total_with_both",
                "combined_accuracy",
                "iter_1_acc", "iter_2_acc", "iter_3_acc", "iter_4_acc", "iter_5_acc",
                "iter_6_acc", "iter_7_acc", "iter_8_acc", "iter_9_acc", "iter_10_acc",
                "output_file"
            ])
        
        # Prepare iteration accuracies (fill missing with None)
        iter_accs = {}
        for i in range(1, max_iterations + 1):
            if i in summary.get("iteration_accuracies", {}):
                iter_accs[i] = summary["iteration_accuracies"][i]["accuracy"]
            else:
                iter_accs[i] = None
        
        # Write row
        row = [
            summary.get("timestamp", ""),
            max_iterations,
            summary.get("name_top_k", ""),
            summary.get("iou_threshold", ""),
            summary.get("total_with_name", ""),
            summary.get("name_accuracy", ""),
            summary.get("total_with_bbox", ""),
            summary.get("bbox_accuracy", ""),
            summary.get("avg_iou", ""),
            summary.get("total_with_iou_and_name", ""),
            summary.get("combined_accuracy", ""),
            iter_accs.get(1), iter_accs.get(2), iter_accs.get(3), iter_accs.get(4), iter_accs.get(5),
            iter_accs.get(6), iter_accs.get(7), iter_accs.get(8), iter_accs.get(9), iter_accs.get(10),
            summary.get("output_file", str(output_jsonl))
        ]
        writer.writerow(row)
    
    print(f"[batch] Accuracy summary appended to: {csv_file}")


def parse_iterations(raw: str) -> List[int]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    iters = []
    for part in parts:
        if part.isdigit():
            iters.append(int(part))
    return iters


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch test for RAG.")
    parser.add_argument("--query", required=False, help="User query text")
    parser.add_argument("--image", required=False, help="Local image path for bbox")
    parser.add_argument("--input-csv", help="Run batch LLM RAG using CSV input")
    parser.add_argument(
        "--output-jsonl",
        default="tests/test_rag_results.jsonl",
        help="Output JSONL path for batch results"
    )
    parser.add_argument("--limit", type=int, default=100, help="Batch row limit")
    parser.add_argument(
        "--rag-iterations",
        default="1,2,3,4,5",
        help="Comma-separated max_iterations for RAG"
    )
    parser.add_argument(
        "--fixed-bbox",
        nargs=4,
        type=float,
        default=[-0.4, -0.4, 0.4, 0.4],
        metavar=("MIN_X", "MIN_Y", "MAX_X", "MAX_Y"),
        help="Fixed bbox for IoU comparison"
    )
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model for bbox")
    parser.add_argument("--top-n", type=int, default=10, help="Top N SQL results")
    parser.add_argument("--iou-threshold", type=float, default=0.5, help="IoU threshold for accuracy")
    parser.add_argument("--name-top-k", type=int, default=5, help="Top K for name accuracy")
    parser.add_argument(
        "--allow-name-fallback",
        action="store_true",
        help="Allow name-based fallback in SQL search"
    )
    args = parser.parse_args()

    from app.tools import sql_search_tool as sql_search_tool_module
    if not args.allow_name_fallback:
        sql_search_tool_module.DISABLE_NAME_FALLBACK = True

    if args.input_csv:
        input_csv = Path(args.input_csv).resolve()
        if not input_csv.exists():
            raise FileNotFoundError(f"CSV not found: {input_csv}")
        output_jsonl = Path(args.output_jsonl).resolve()
        fixed_bbox = parse_bbox(args.fixed_bbox)
        
        iterations = parse_iterations(args.rag_iterations)
        if not iterations:
            iterations = [1]
        
        total_runs = len(iterations)
        
        # Generate timestamp for all runs in this batch
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for run_idx, iteration in enumerate(iterations, start=1):
            print(f"\n{'='*60}")
            print(f"[Batch] Run {run_idx}/{total_runs}: Processing with max_iterations={iteration}")
            print(f"{'='*60}\n")
            
            suffix = f"_iter{iteration}_{timestamp}"
            output_path = output_jsonl.with_name(
                f"{output_jsonl.stem}{suffix}{output_jsonl.suffix}"
            )
            asyncio.run(run_batch_rag(
                input_csv=input_csv,
                output_jsonl=output_path,
                limit=args.limit,
                fixed_bbox=fixed_bbox,
                model=args.model,
                iou_threshold=args.iou_threshold,
                max_iterations=iteration,
                name_top_k=args.name_top_k
            ))
            
            print(f"\n[Batch] Run {run_idx}/{total_runs} completed. Output: {output_path}")
        
        print(f"\n{'='*60}")
        print(f"[Batch] All {total_runs} iteration(s) completed!")
        print(f"{'='*60}")
        return

    if not args.query:
        raise ValueError("--query is required when not running batch mode")

    image_path = Path(args.image).resolve() if args.image else None
    if image_path and not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    asyncio.run(run_extract_and_search(args.query, image_path, args.top_n))

    if image_path:
        fixed_bbox = parse_bbox(args.fixed_bbox)
        pred_bbox = request_bbox_from_llm(image_path, args.model)
        if pred_bbox is None:
            print("llm_bbox: null")
            return
        pred_bbox_tuple = parse_bbox([float(v) for v in pred_bbox])
        iou = compute_iou(pred_bbox_tuple, fixed_bbox)
        print("llm_bbox:", pred_bbox_tuple)
        print("fixed_bbox:", fixed_bbox)
        print("iou:", round(iou, 6))


if __name__ == "__main__":
    main()
