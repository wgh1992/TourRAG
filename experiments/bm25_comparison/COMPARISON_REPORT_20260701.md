# TourRAG 对比实验报告（2026-07-01）

## 1. 实验目的

本次实验验证 TourRAG 检索模块在多语言测试集上的表现，并与一个纯词法检索基线 BM25 进行对比。实验重点是“能否把目标景点 `viewpoint_id` 检索到 Top-K 结果中”，因此评估的是检索质量，而不是最终自然语言回答质量。

对比方法：

- `bm25`：Okapi BM25 词法检索基线。把每个景点的名称、别名、类别、Wikipedia 标题、摘要、章节文本拼成一个文档后检索。
- `tourrag_sql`：TourRAG 的非 agent SQL/full-text 检索消融。脚本中先用 query terms 调 `search_by_history_terms`，无结果时再用简单规则推断类别或退回热门景点。

未在 1000 条主跑中包含 `tourrag_agent`，原因是它会调用 OpenAI-backed agent，耗时和 API 成本都明显更高。后续根据补充需求，已新增 `no_rag` 三路对比，见第 11 节。

## 2. 实验环境

- 工作目录：`E:\codex\TourRAG`
- 日期：2026-07-01
- Python：`venv\Scripts\python.exe`
- 数据库：本地 PostgreSQL，通过项目现有 `DATABASE_URL` 连接
- BM25 语料规模：8451 个 viewpoint 文档
- 输入测试集：`tests/datasets/test_set_multilingual_1000.csv`
- 输出明细：`experiments/bm25_comparison/results/retrieval_compare_20260701_160306.jsonl`
- 输出汇总：`experiments/bm25_comparison/results/summary.csv`

## 3. 运行命令

先跑 100 条试验确认数据库、语料加载和脚本可用：

```powershell
venv\Scripts\python.exe experiments\bm25_comparison\evaluate_retrieval.py `
  --input tests\datasets\test_set_multilingual_1000.csv `
  --methods bm25,tourrag_sql `
  --top-k 1,3,5,10 `
  --limit 100
```

正式跑完整 1000 条：

```powershell
venv\Scripts\python.exe experiments\bm25_comparison\evaluate_retrieval.py `
  --input tests\datasets\test_set_multilingual_1000.csv `
  --methods bm25,tourrag_sql `
  --top-k 1,3,5,10 `
  --limit 1000
```

## 4. 指标定义

每个 query 只有一个目标 `viewpoint_id`。设模型返回 Top-K 排名列表：

- `Hit@K` / `Recall@K`：目标是否出现在 Top-K 中。
- `Precision@K`：单一相关目标设置下等于 `Hit@K / K`。
- `MRR`：目标排名的 reciprocal rank，未命中为 0。
- `NDCG@K`：考虑目标排名位置的 Top-K 分数。

因为只有一个相关目标，`Hit@K` 和 `Recall@K` 数值相同。

## 5. 整体结果（1000 queries）

| Method | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@5 | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.3240 | 0.299 | 0.342 | 0.354 | 0.373 | 0.0708 | 0.3359 |
| TourRAG SQL | 0.0557 | 0.051 | 0.058 | 0.063 | 0.064 | 0.0126 | 0.0578 |

主要结论：

- 在当前脚本实现下，BM25 明显优于 `tourrag_sql` 消融。BM25 的 Hit@10 为 37.3%，而 `tourrag_sql` 为 6.4%。
- 差距最明显的原因不是 BM25 很强，而是当前 `tourrag_sql` 消融过于保守：它主要使用 `search_by_history_terms`，失败后只做简单类别/热门 fallback，没有使用完整 agent 的工具选择、结构化意图抽取、多字段综合检索和 LLM reranking。
- 视觉/季节线索类 query 对两种纯文本/简化检索都很难，显著拉低总体表现。

## 6. 按语言细分

| Method | Language | N | Hit@1 | Hit@5 | Hit@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| BM25 | en | 700 | 0.276 | 0.340 | 0.364 | 0.306 |
| BM25 | es | 60 | 0.350 | 0.400 | 0.400 | 0.370 |
| BM25 | hi | 60 | 0.300 | 0.333 | 0.333 | 0.312 |
| BM25 | ja | 60 | 0.383 | 0.417 | 0.417 | 0.397 |
| BM25 | ko | 60 | 0.417 | 0.433 | 0.467 | 0.428 |
| BM25 | zh | 60 | 0.317 | 0.350 | 0.350 | 0.328 |
| TourRAG SQL | en | 700 | 0.060 | 0.073 | 0.074 | 0.065 |
| TourRAG SQL | es | 60 | 0.067 | 0.067 | 0.067 | 0.067 |
| TourRAG SQL | hi | 60 | 0.000 | 0.017 | 0.017 | 0.006 |
| TourRAG SQL | ja | 60 | 0.000 | 0.000 | 0.000 | 0.000 |
| TourRAG SQL | ko | 60 | 0.083 | 0.100 | 0.100 | 0.092 |
| TourRAG SQL | zh | 60 | 0.000 | 0.017 | 0.017 | 0.008 |

观察：

- BM25 在多语言查询上没有明显崩溃，主要因为很多 query 仍保留了景点名或专有名词，词法匹配能直接命中。
- `tourrag_sql` 对日文、中文、印地语表现很弱，说明当前 SQL 消融的 query term 提取和 PostgreSQL 文本检索路径对跨语言/混合脚本支持不足。
- 韩文子集的 `tourrag_sql` 略好，主要来自部分 query 中保留的拉丁或原名片段。

## 7. 按查询类型细分

| Method | Query Type | N | Hit@1 | Hit@5 | Hit@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| BM25 | name | 150 | 0.573 | 0.633 | 0.647 | 0.606 |
| BM25 | history/culture | 143 | 0.469 | 0.545 | 0.545 | 0.496 |
| BM25 | description | 395 | 0.365 | 0.441 | 0.473 | 0.400 |
| BM25 | visual/seasonal | 312 | 0.006 | 0.022 | 0.035 | 0.014 |
| TourRAG SQL | name | 150 | 0.013 | 0.033 | 0.040 | 0.021 |
| TourRAG SQL | history/culture | 143 | 0.091 | 0.098 | 0.098 | 0.093 |
| TourRAG SQL | description | 395 | 0.091 | 0.104 | 0.104 | 0.097 |
| TourRAG SQL | visual/seasonal | 312 | 0.000 | 0.010 | 0.010 | 0.003 |

观察：

- BM25 对 name query 最有效，Hit@1 达 57.3%，Hit@10 达 64.7%。
- BM25 对 history/culture 和自然语言 description 也有一定效果，因为 query 中包含能与 Wikipedia/名称字段对齐的词。
- 视觉/季节线索是主要失败来源。BM25 Top-10 只有 3.5%，`tourrag_sql` Top-10 只有 1.0%。这说明如果论文要强调视觉/季节检索，必须使用 visual tags、season tags 或完整 TourRAG agent 逻辑，而不是只用文本字段。

## 8. 命中关系与案例

按 Top-10 是否命中目标统计：

| Category | Count |
|---|---:|
| 两者都命中 | 59 |
| 仅 BM25 命中 | 314 |
| 仅 TourRAG SQL 命中 | 5 |
| 两者都未命中 | 622 |

代表案例：

- 仅 BM25 命中：query `Liubavas Manor...`，目标 `66629`。BM25 Rank 1 命中，`tourrag_sql` 未进 Top-10。
- 仅 BM25 命中：query `Identify the tourist attraction named Manavgat Şelalesi.`，目标 `64433`。BM25 Rank 1 命中，`tourrag_sql` 未进 Top-10。
- 仅 TourRAG SQL 命中：query `Kjeåsen is a scenic mountain farm in Norway...`，目标 `63191`。BM25 未进 Top-10，`tourrag_sql` Rank 1 命中。
- 两者都未命中：query `Find the tourist attraction with these visual or scene cues: exterior, ground_level, panoramic, sunny, temple.`，目标 `71144`。这类视觉线索缺少强唯一文本锚点。

注意：部分数据库 `name_primary` 字段在终端显示中存在 mojibake，例如中文或西里尔文本被错误编码显示；本实验命中判断基于整数 `viewpoint_id`，不受显示乱码影响。

## 9. 历史 RAG / No-RAG 结果补充

仓库中已有历史结果，可作为生成式/完整 pipeline 对比的补充，但它们不是本次新跑结果，且测试集路径和日期不同。

- No-RAG only：`experiments/results/summary_no_rag_only_20260312_172340.json`
  - 测试条数：100
  - No-RAG text hit rate：0.16
  - No-RAG text hits：16 / 100

- RAG 历史准确率汇总：`tests/accuracy_results/accuracy_summary.csv`
  - 最大一轮 100 条结果：`test_rag_results_iter10_20260121_212459.jsonl`
  - `name_top_k=5`
  - `name_accuracy=0.69`
  - `total_with_name=100`

这组历史结果说明完整 RAG agent 的 Top-5 名称命中率明显高于 No-RAG 文本命中率，但由于它们不是本次同一命令、同一时间重新运行，论文中应标注为历史实验或重新统一跑一遍。

## 10. 结论与建议

本次新跑的检索对比显示：在当前 `evaluate_retrieval.py` 的实现下，BM25 基线显著强于 `tourrag_sql` 简化消融。这个结果更适合表述为“当前 SQL 消融实现不足以代表完整 TourRAG”，而不是“TourRAG 弱于 BM25”。

建议后续改进：

1. 给 `tourrag_sql` 加入 name-based retrieval。当前 name query 下 BM25 Hit@10 为 64.7%，而 `tourrag_sql` 只有 4.0%，说明 SQL 消融没有充分调用 `search_by_name`。
2. 对 multilingual query 做翻译、专名抽取或 Unicode-aware tokenization。尤其是中文、日文、印地语查询下 `tourrag_sql` 近乎失效。
3. 对 visual/seasonal query 使用 `viewpoint_visual_tags`、season tags 和 category constraints，否则文本检索很难区分大量相似景点。
4. 论文主实验应重新跑同一测试集上的 `bm25,tourrag_sql,tourrag_agent`，并单独报告 agent 成本和耗时。

## 11. 补充：BM25 / TourRAG SQL / No-RAG 三路实验

根据补充需求，已修改 `experiments/bm25_comparison/evaluate_retrieval.py`：

- 新增 `no_rag` 方法：纯 LLM name-only baseline，不给数据库、不使用工具、不做 RAG。为了能用同一套 `viewpoint_id` 指标评估，脚本在 LLM 输出景点名后，仅用本地 `search_by_name(answer)` 做评估适配。
- 改进 `tourrag_sql`：对显式名称查询优先抽取景点名并调用 `search_by_name`，再退回 history FTS / category / popular fallback。
- 汇总文件改为 `summary_YYYYMMDD_HHMMSS.csv`，避免 Windows 下固定 `summary.csv` 被占用时写入失败。

运行命令：

```powershell
venv\Scripts\python.exe experiments\bm25_comparison\evaluate_retrieval.py `
  --input tests\datasets\test_set_multilingual_1000.csv `
  --methods bm25,tourrag_sql,no_rag `
  --top-k 1,3,5,10 `
  --limit 100
```

输出文件：

- `experiments/bm25_comparison/results/retrieval_compare_20260701_205717.jsonl`
- `experiments/bm25_comparison/results/summary_20260701_205717.csv`

100 条三路结果：

| Method | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@5 | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.3208 | 0.280 | 0.350 | 0.370 | 0.390 | 0.074 | 0.3377 |
| No-RAG | 0.2833 | 0.280 | 0.290 | 0.290 | 0.290 | 0.058 | 0.2850 |
| TourRAG SQL | 0.1367 | 0.130 | 0.150 | 0.150 | 0.150 | 0.030 | 0.1400 |

按查询类型细分（100 条）：

| Method | Query Type | N | Hit@1 | Hit@5 | Hit@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| BM25 | description | 40 | 0.300 | 0.425 | 0.450 | 0.354 |
| BM25 | history/culture | 16 | 0.250 | 0.375 | 0.375 | 0.297 |
| BM25 | name | 23 | 0.522 | 0.609 | 0.652 | 0.572 |
| BM25 | visual/seasonal | 21 | 0.000 | 0.000 | 0.000 | 0.000 |
| No-RAG | description | 40 | 0.350 | 0.350 | 0.350 | 0.350 |
| No-RAG | history/culture | 16 | 0.250 | 0.250 | 0.250 | 0.250 |
| No-RAG | name | 23 | 0.435 | 0.478 | 0.478 | 0.449 |
| No-RAG | visual/seasonal | 21 | 0.000 | 0.000 | 0.000 | 0.000 |
| TourRAG SQL | description | 40 | 0.100 | 0.125 | 0.125 | 0.108 |
| TourRAG SQL | history/culture | 16 | 0.000 | 0.000 | 0.000 | 0.000 |
| TourRAG SQL | name | 23 | 0.391 | 0.435 | 0.435 | 0.406 |
| TourRAG SQL | visual/seasonal | 21 | 0.000 | 0.000 | 0.000 | 0.000 |

新的结论：

- 加入 name-aware SQL 后，`tourrag_sql` 在 100 条样本上的 Hit@10 从旧试跑的 4% 提升到 15%，说明之前主要短板之一确实是没有处理显式名称查询。
- BM25 仍是最强的非 agent 检索基线，尤其在 name query 上 Top-10 达 65.2%。
- No-RAG 在 description/history/name 查询中有一定效果，因为很多测试 query 直接包含或暗示景点名；但它没有数据库约束，输出必须再通过 name adapter 映射到本地 ID，所以不能替代真实检索。
- 三种方法在 visual/seasonal query 上均为 0，说明这一类必须引入 visual tags、season tags 或完整 agent 逻辑。

## 12. 补充：BM25 / Full RAG Agent / No-RAG 小样本验证

根据进一步确认，完整 RAG 应使用 `tourrag_agent`，而不是 SQL-only 的 `tourrag_sql` 消融。已先跑 10 条小样本，用于确认 BM25、完整 RAG、No-RAG 三类方法能在同一评估脚本中运行。

运行命令：

```powershell
venv\Scripts\python.exe experiments\bm25_comparison\evaluate_retrieval.py `
  --input tests\datasets\test_set_multilingual_1000.csv `
  --methods bm25,tourrag_agent,no_rag `
  --top-k 1,3,5,10 `
  --limit 10 `
  --max-iterations 5
```

输出文件：

- `experiments/bm25_comparison/results/retrieval_compare_20260701_224713.jsonl`
- `experiments/bm25_comparison/results/summary_20260701_224713.csv`

10 条结果：

| Method | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@5 | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.350 | 0.300 | 0.400 | 0.400 | 0.400 | 0.080 | 0.363 |
| No-RAG | 0.400 | 0.400 | 0.400 | 0.400 | 0.400 | 0.080 | 0.400 |
| Full RAG Agent | 0.450 | 0.400 | 0.500 | 0.500 | 0.500 | 0.100 | 0.463 |

说明：

- 这次 `tourrag_agent` 和 `no_rag` 都调用了 OpenAI API key；BM25 不调用 key。
- 小样本结果显示 Full RAG Agent 在 Hit@3/5/10 和 MRR 上优于 BM25 与 No-RAG。
- 由于只有 10 条，不能作为最终论文结论，只能作为 pipeline 验证。正式对比建议扩大到 100 或 1000 条。
- 运行日志中出现多次 `search_with_llm_sql` 参数数量不匹配，例如 SQL placeholder 数多于参数列表。工具通过 name/category/history fallback 继续完成实验，但这会污染日志并可能影响 RAG 上限，建议后续修复 LLM SQL 生成或在参数不匹配时直接跳过执行。

## 13. 正式 100 条：BM25 / Full RAG Agent / No-RAG

按你的要求，重新跑了 100 条，并且这次 RAG 使用完整 `tourrag_agent`，No-RAG 也使用 OpenAI API；BM25 不使用 API key。

运行命令：

```powershell
$env:OPENAI_TIMEOUT='120'
venv\Scripts\python.exe experiments\bm25_comparison\evaluate_retrieval.py `
  --input tests\datasets\test_set_multilingual_1000.csv `
  --methods bm25,tourrag_agent,no_rag `
  --top-k 1,3,5,10 `
  --limit 100 `
  --max-iterations 5 `
  --method-retries 3 `
  --retry-delay 3
```

输出文件：

- `experiments/bm25_comparison/results/retrieval_compare_20260701_230356.jsonl`
- `experiments/bm25_comparison/results/summary_20260701_230356.csv`

100 条整体结果：

| Method | MRR | Hit@1 | Hit@3 | Hit@5 | Hit@10 | Precision@5 | NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.3208 | 0.280 | 0.350 | 0.370 | 0.390 | 0.074 | 0.3377 |
| No-RAG | 0.2733 | 0.270 | 0.280 | 0.280 | 0.280 | 0.056 | 0.2750 |
| Full RAG Agent | 0.3183 | 0.310 | 0.330 | 0.330 | 0.330 | 0.066 | 0.3213 |

按查询类型细分：

| Method | Query Type | N | Hit@1 | Hit@5 | Hit@10 | MRR |
|---|---|---:|---:|---:|---:|---:|
| BM25 | description | 39 | 0.308 | 0.436 | 0.462 | 0.363 |
| BM25 | history/culture | 15 | 0.267 | 0.333 | 0.333 | 0.300 |
| BM25 | name | 25 | 0.480 | 0.600 | 0.640 | 0.537 |
| BM25 | visual/seasonal | 21 | 0.000 | 0.000 | 0.000 | 0.000 |
| No-RAG | description | 39 | 0.359 | 0.359 | 0.359 | 0.359 |
| No-RAG | history/culture | 15 | 0.200 | 0.200 | 0.200 | 0.200 |
| No-RAG | name | 25 | 0.400 | 0.440 | 0.440 | 0.413 |
| No-RAG | visual/seasonal | 21 | 0.000 | 0.000 | 0.000 | 0.000 |
| Full RAG Agent | description | 39 | 0.359 | 0.359 | 0.359 | 0.359 |
| Full RAG Agent | history/culture | 15 | 0.333 | 0.333 | 0.333 | 0.333 |
| Full RAG Agent | name | 25 | 0.480 | 0.560 | 0.560 | 0.513 |
| Full RAG Agent | visual/seasonal | 21 | 0.000 | 0.000 | 0.000 | 0.000 |

结论：

- Full RAG Agent 的 Hit@1 最高：31.0%，比 BM25 高 3 个百分点，比 No-RAG 高 4 个百分点。说明 agent 在部分题上能通过数据库工具把正确景点排到第一。
- BM25 的 Hit@5/Hit@10 和 NDCG@10 最高，说明它虽然第一名不一定最好，但候选召回更稳。对于检索任务，如果后面还有 reranker，BM25 是很强的候选生成基线。
- No-RAG 明显弱于 Full RAG Agent 和 BM25，尤其 Hit@5/10 只有 28%。它能答对一部分，是因为很多 query 本身泄露了景点名；但没有数据库约束，生成答案还必须再通过 name adapter 映射到本地 `viewpoint_id`。
- Full RAG Agent 相比 SQL-only `tourrag_sql` 有明显提升：前一轮 100 条 SQL-only Hit@10 只有 15.0%，Full RAG Agent Hit@10 达到 33.0%。这说明完整 agent 的 name/history/category/tag fallback 对结果贡献很大。
- 三种方法在 visual/seasonal 查询上都是 0，说明现有文本检索、No-RAG 和记忆式 agent 都没有真正解决视觉标签/季节标签匹配；后续要重点修 visual tags、season tags 的索引和排序逻辑。
- 日志中大量出现 `search_with_llm_sql` placeholder 参数不匹配、`geo_hints` 校验错误、候选名称 mojibake 等问题。实验没有崩，因为工具 fallback 继续跑完了；但这会降低 Full RAG Agent 上限，也说明当前结果应表述为“完整 agent pipeline”效果，而不是纯 LLM-SQL 效果。
