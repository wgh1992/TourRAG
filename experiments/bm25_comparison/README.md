# BM25 Comparison Experiment

This folder contains a paper-friendly retrieval comparison between:

- `bm25`: direct Okapi BM25 over viewpoint text fields.
- `tourrag_sql`: TourRAG's local SQL/full-text retrieval path without the agent loop.
- `no_rag`: pure LLM name-only baseline without database or tools. For retrieval metrics, the generated name is mapped back to local `viewpoint_id`s with a name lookup adapter.
- `tourrag_agent`: the full TourRAG agent retrieval path, including tool selection and reranking.

## Why This Baseline

BM25, or Best Matching 25, is a lexical retrieval algorithm. It ranks documents by query-term matches, inverse document frequency, term-frequency saturation, and document-length normalization. In this project, each viewpoint is treated as one document built from:

- primary name
- name variants
- normalized category
- Wikipedia title
- Wikipedia extract
- Wikipedia sections

This gives a clean baseline for the paper: "What if we directly retrieve attractions with BM25 instead of using TourRAG's structured intent, SQL tools, metadata, visual tags, and agent reranking?"

## Metrics

The evaluator assumes one relevant viewpoint per query, using `target_id` or `viewpoint_base_name` from the input CSV.

It reports:

- `Hit@K`: whether the target appears in the top K.
- `Precision@K`: with one relevant target, this is `Hit@K / K`.
- `Recall@K`: with one relevant target, this equals `Hit@K`.
- `MRR`: mean reciprocal rank.
- `NDCG@K`: rank-sensitive top-K score.

These are retrieval metrics analogous to using precision and recall in detection, but applied to ranked lists instead of bounding boxes.

## Run

From the repository root:

```powershell
python experiments/bm25_comparison/evaluate_retrieval.py `
  --input tests/datasets/test_set_expanded_500.csv `
  --methods bm25,tourrag_sql `
  --top-k 1,3,5,10 `
  --limit 100
```

For the full TourRAG agent comparison:

```powershell
python experiments/bm25_comparison/evaluate_retrieval.py `
  --input tests/datasets/test_set_expanded_500.csv `
  --methods bm25,tourrag_sql,tourrag_agent `
  --top-k 1,3,5,10 `
  --limit 100 `
  --max-iterations 5
```

`tourrag_agent` calls the OpenAI-backed agent service, so it is slower and may incur API cost.

For the three-way comparison requested in the paper draft:

```powershell
python experiments/bm25_comparison/evaluate_retrieval.py `
  --input tests/datasets/test_set_expanded_500.csv `
  --methods bm25,tourrag_sql,no_rag `
  --top-k 1,3,5,10 `
  --limit 100
```

`no_rag` also calls OpenAI, but it receives no database context and no tools. The evaluator only uses a local name lookup after the model answers so that the name-only output can be scored with the same `viewpoint_id` metrics as BM25 and TourRAG SQL.

## Outputs

Results are written to:

- `experiments/bm25_comparison/results/retrieval_compare_*.jsonl`
- `experiments/bm25_comparison/results/summary_*.csv`

The JSONL file stores per-query rankings and target rank. The CSV file stores aggregate metrics by method.

## Suggested Paper Wording

Use `bm25` as the lexical baseline:

> We compare TourRAG against a direct Okapi BM25 retrieval baseline. BM25 indexes each attraction as a single text document constructed from names, category labels, and Wikipedia fields. The baseline ranks attractions using lexical term matching only, while TourRAG combines structured query intent, SQL retrieval tools, metadata constraints, visual/seasonal tags, and LLM-based reranking.

Use `tourrag_sql` as an ablation:

> We also report a non-agent TourRAG SQL/FTS ablation to isolate the gain from structured local retrieval before agentic tool use and final reranking.
