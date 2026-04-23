# Comparison Experiments (RAG vs No-RAG)

This folder contains scripts for **ablation / comparison experiments** used in the paper: comparing **TourRAG (with retrieval)** against a **pure LLM baseline (no database, no RAG)**.

## Purpose

- **RAG**: Same query input (from CSV). Uses the full pipeline (extract intent → SQL search over PostgreSQL → rank & explain). **Returns** ranked candidate `viewpoint_id`s from the local database. The agent prompt instructs it to use tools and return the best match.
- **No-RAG baseline**: Same query input. Single OpenAI call only; no tools, no database search. The **prompt** tells the model to output **name only** (one attraction name), no explanation—so the model replies with just a name from parametric knowledge, not from any retrieval.

The comparison shows that without RAG, the system cannot return **in-database** viewpoints (e.g. `viewpoint_id`); no-RAG outputs a single name only (no search).

## Contents

| File | Description |
|------|-------------|
| `no_rag_baseline.py` | Pure LLM baseline: one OpenAI chat completion per query, no retrieval. |
| `run_batch_comparison.py` | Batch runner: same CSV input, runs both RAG and No-RAG, computes metrics and writes results. |
| `results/` | Default output directory for JSONL and summary (created on first run). |

## Requirements

- Same as the main project: Python 3.10+, `requirements.txt`, `.env` with `OPENAI_API_KEY`.
- For RAG branch: PostgreSQL and migrated DB (so that agent search tools work).
- Input CSV: **test set** is `tests/test_set_input.csv` (columns: `viewpoint_base_name`, `image_path`, `history_summary`, `season_info`). This is the default for the batch comparison script.

## Quick Start

### 1. Single-query No-RAG baseline

```bash
cd /path/to/TourRAG_code
python experiments/no_rag_baseline.py --query "推荐秋天看红叶的景点"
```

### 2. Batch comparison (RAG vs No-RAG)

Uses the same CSV as the RAG batch test. For each row, runs both RAG and No-RAG and writes one JSONL per run plus a summary.

Uses **`tests/test_set_input.csv`** by default:

```bash
python experiments/run_batch_comparison.py --limit 20 --name-top-k 5
```

Or specify another CSV:

```bash
python experiments/run_batch_comparison.py \
  --input-csv path/to/test_queries.csv \
  --output-dir experiments/results \
  --limit 20 \
  --name-top-k 5
```

**Only run no-RAG baseline** (skip RAG; no DB/agent needed for the RAG branch):

```bash
python experiments/run_batch_comparison.py --limit 20 --no-rag-only
```

Outputs:

- `experiments/results/comparison_YYYYMMDD_HHMMSS.jsonl` – one line per query with RAG and No-RAG answers and metrics (or `no_rag_only_*.jsonl` when using `--no-rag-only`).
- `experiments/results/summary_*.json` – aggregate metrics (e.g. RAG name accuracy, No-RAG text hit rate).

## Metrics

- **RAG**: `name_match` = ground-truth `viewpoint_id` is in the top-K candidate IDs returned by the agent (from SQL search + rank). `name_accuracy` = fraction of queries with `name_match`.
- **No-RAG**: `text_hit` = the model’s answer text contains the ground-truth attraction name. No-RAG outputs name only (no database search); we check whether that name matches the ground truth.

These metrics support the claim that RAG is necessary to retrieve in-database information.
