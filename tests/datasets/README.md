# TourRAG Test Datasets

This folder keeps the CSV evaluation sets in one place.

## Files

- `test_set_input.csv`: original 100-row legacy test set.
- `test_set_expanded_100.csv`: carefully sampled 100-row retrieval test set.
- `test_set_expanded_500.csv`: carefully sampled 500-row retrieval test set.
- `test_set_expanded_1000.csv`: carefully sampled 1000-row retrieval test set.
- `test_set_hard_semantic_100.csv`: anonymous semantic retrieval stress test.
- `test_set_hard_semantic_500.csv`: larger anonymous semantic retrieval stress test.
- `test_set_hard_semantic_1000.csv`: 1000-row anonymous semantic retrieval stress test.
- `test_set_multilingual_1000.csv`: 1000-row set based on expanded 1000, with 20% multilingual queries.

The expanded sets are the recommended benchmarks. They use detailed attraction
descriptions assembled from `viewpoint_ai_summaries`, `viewpoint_wiki` extract
and section prose, OSM category hints, season metadata, and visual/scene tags
where available. Reference sections, CSS/reflist artifacts, disambiguation pages,
and obvious non-place taxonomy pages are filtered out. Each target viewpoint
appears at most once per generated set so that metrics are not inflated by
repeated variants of the same attraction.

## Sampling Profile

The generator reserves about 60% of each expanded set for detailed anonymous
geo/history queries. These rows remove the target attraction name from the query
text, but keep stronger identifying clues such as location, historical period,
landmark function, nearby geography, visual tags, and category hints.

The remaining rows keep a smaller direct-name slice for sanity checks and
regression debugging. Report direct-name and anonymous subsets separately.

Default query type weights for the non-reserved remainder:

- `history_description`: 0.36
- `search_description`: 0.36
- `name_query`: 0.18
- `visual_tag_query`: 0.07
- `season_visual_query`: 0.03

Rows include:

- `target_name`: human-readable attraction name for inspection only.
- `is_anonymized_name`: `1` if the query removes the target name; `0` otherwise.
- `anonymous_clue_type`: `direct_name`, `geo_history`, `visual`, or `season_visual`.
- `query_type`: generation template family.

## Regenerate

From the repository root:

```powershell
python experiments/generate_expanded_test_set.py `
  --output tests/datasets/test_set_expanded_100.csv `
  --size 100 `
  --seed 42

python experiments/generate_expanded_test_set.py `
  --output tests/datasets/test_set_expanded_500.csv `
  --size 500 `
  --seed 42

python experiments/generate_expanded_test_set.py `
  --output tests/datasets/test_set_expanded_1000.csv `
  --size 1000 `
  --seed 42

python experiments/generate_expanded_test_set.py `
  --output tests/datasets/test_set_hard_semantic_1000.csv `
  --size 1000 `
  --seed 42 `
  --hard-semantic

python scripts/generate_multilingual_test_set.py `
  --input tests/datasets/test_set_expanded_1000.csv `
  --output tests/datasets/test_set_multilingual_1000.csv `
  --ratio 0.20 `
  --seed 2026
```

Use `--keep-direct-names` only when intentionally building an older-style
name-leaking benchmark. Use `--anonymous-ratio 1.0 --anonymous-target-ratio 1.0`
for a fully anonymous stress test.
