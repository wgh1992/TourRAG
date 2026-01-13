# LLM SQL 搜索功能

## 概述

MCP SQL 工具现在支持使用 LLM（大语言模型）自动生成 SQL 查询，使搜索功能更加灵活和智能。

## 功能特性

### 1. LLM 生成的 SQL 查询

新增 `search_with_llm_sql` 方法，使用 LLM 根据查询意图自动生成优化的 SQL 查询。

**优势：**
- 自动处理复杂的多条件查询（名称 + 类别 + 国家 + 季节）
- 根据查询意图动态生成最适合的 SQL
- 支持组合多个搜索条件

### 2. 安全性保障

- 只允许 SELECT 查询
- 禁止危险操作（INSERT, UPDATE, DELETE, DROP 等）
- 使用参数化查询防止 SQL 注入
- 自动验证生成的 SQL

### 3. 智能回退机制

如果 LLM 生成的 SQL 有问题，系统会自动回退到传统的硬编码搜索方法，确保功能稳定性。

## 使用方法

### 在 Agent Service 中使用

Agent 现在可以使用 `search_with_llm_sql` 工具进行搜索：

```python
# Agent 会自动调用
search_with_llm_sql(
    query_intent={
        "name_candidates": ["西湖"],
        "query_tags": ["lake"],
        "season_hint": "spring",
        "geo_hints": {
            "country": "China"
        }
    },
    top_n=50
)
```

### 直接使用 SQLSearchTool

```python
from app.tools.sql_search_tool import get_sql_search_tool
from app.schemas.query import QueryIntent, GeoHints

tool = get_sql_search_tool()

query_intent = QueryIntent(
    name_candidates=[],
    query_tags=['lake'],
    season_hint='unknown',
    scene_hints=[],
    geo_hints=GeoHints(place_name=None, country='China'),
    confidence_notes=[]
)

result = tool.search_with_llm_sql(query_intent, top_n=10)
```

## 数据库 Schema 信息

LLM 会收到完整的数据库 schema 信息，包括：

- `viewpoint_entity` - 核心景点表
- `viewpoint_commons_assets` - 图像和元数据
- `viewpoint_wiki` - Wikipedia 数据
- `viewpoint_wikidata` - Wikidata 数据
- `viewpoint_visual_tags` - 视觉标签

## 工作流程

1. **提取查询意图** - 使用 `extract_query_intent` 工具
2. **生成 SQL** - LLM 根据查询意图生成 SQL 查询
3. **验证 SQL** - 检查安全性（只允许 SELECT，禁止危险操作）
4. **执行查询** - 使用参数化查询执行
5. **回退机制** - 如果失败，自动回退到传统搜索方法

## 配置

在 `app/tools/sql_search_tool.py` 中：

```python
self.use_llm_sql = True  # 启用 LLM SQL 生成（默认开启）
```

## 示例

### 示例 1: 搜索中国的湖泊

```python
query_intent = QueryIntent(
    name_candidates=[],
    query_tags=['lake'],
    geo_hints=GeoHints(country='China'),
    season_hint='unknown'
)

result = tool.search_with_llm_sql(query_intent, top_n=10)
```

### 示例 2: 搜索春天的樱花寺庙

```python
query_intent = QueryIntent(
    name_candidates=[],
    query_tags=['temple', 'cherry_blossom'],
    season_hint='spring',
    geo_hints=None
)

result = tool.search_with_llm_sql(query_intent, top_n=10)
```

## 注意事项

1. **参数匹配** - LLM 生成的 SQL 中的参数占位符数量必须与实际参数数量匹配
2. **性能** - LLM 生成 SQL 需要额外的 API 调用，可能比硬编码 SQL 稍慢
3. **准确性** - LLM 生成的 SQL 可能不总是最优的，系统会自动回退到传统方法
4. **成本** - 每次搜索都会调用 LLM API，会产生 API 费用

## 与传统方法的对比

| 特性 | LLM SQL | 传统方法 |
|------|---------|----------|
| 灵活性 | 高（自动适应复杂查询） | 中（需要预定义方法） |
| 性能 | 中（需要 LLM API 调用） | 高（直接执行） |
| 准确性 | 中（可能生成错误 SQL） | 高（经过测试） |
| 成本 | 有（API 调用费用） | 无 |

## 未来改进

1. 改进 LLM 提示，提高 SQL 生成准确性
2. 添加 SQL 查询缓存，减少重复的 LLM 调用
3. 优化参数提取逻辑，确保参数数量匹配
4. 添加更多验证规则，提高生成 SQL 的质量

## 相关文件

- `app/tools/sql_search_tool.py` - SQL 搜索工具实现
- `app/services/agent_service.py` - Agent 服务，使用 SQL 工具
- `app/schemas/query.py` - 查询意图数据结构
