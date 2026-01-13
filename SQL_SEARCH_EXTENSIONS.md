# SQL 搜索功能扩展

## 概述

SQL 搜索工具现在支持搜索历史信息、视觉标签和季节等相关信息。

## 新增搜索能力

### 1. 历史信息搜索

可以通过 Wikipedia 文本搜索历史相关信息：

- **数据源**: `viewpoint_wiki.extract_text` 字段
- **搜索方式**: 使用 `ILIKE` 进行文本匹配
- **使用场景**: 当查询包含场景提示（scene_hints）时，会在 Wikipedia 文本中搜索

**示例 SQL**:
```sql
SELECT DISTINCT e.viewpoint_id, e.name_primary, ...
FROM viewpoint_entity e
JOIN viewpoint_wiki w ON e.viewpoint_id = w.viewpoint_id
WHERE w.extract_text ILIKE %s  -- 搜索历史信息
```

### 2. 视觉标签搜索

可以搜索景点的视觉标签（visual tags）：

- **数据源**: `viewpoint_visual_tags.tags` 字段（JSONB 数组）
- **搜索方式**: 使用 JSONB `@>` 操作符检查数组是否包含特定标签
- **使用场景**: 当查询包含视觉标签（如 `cherry_blossom`, `snow_peak` 等）时

**示例 SQL**:
```sql
SELECT DISTINCT e.viewpoint_id, e.name_primary, ...
FROM viewpoint_entity e
JOIN viewpoint_visual_tags vt ON e.viewpoint_id = vt.viewpoint_id
WHERE vt.tags @> %s::jsonb  -- 例如: '["cherry_blossom"]'::jsonb
```

### 3. 季节过滤

可以根据季节过滤景点：

- **数据源**: `viewpoint_visual_tags.season` 字段
- **搜索方式**: 直接匹配季节值
- **使用场景**: 当查询包含季节提示（season_hint）时

**示例 SQL**:
```sql
SELECT DISTINCT e.viewpoint_id, e.name_primary, ...
FROM viewpoint_entity e
JOIN viewpoint_visual_tags vt ON e.viewpoint_id = vt.viewpoint_id
WHERE vt.season = %s  -- 'spring', 'summer', 'autumn', 'winter'
```

## 数据库 Schema 更新

已更新 LLM SQL 生成器的数据库 schema 信息，包括：

### viewpoint_wiki 表
- `extract_text` (TEXT) - Wikipedia 提取文本，包含历史信息
- `sections` (JSONB) - 章节结构，可能包含历史章节
- `wikipedia_title` (VARCHAR) - Wikipedia 文章标题

### viewpoint_visual_tags 表
- `tags` (JSONB) - 视觉标签数组，例如 `["snow_peak", "cherry_blossom"]`
- `season` (VARCHAR) - 季节（spring, summer, autumn, winter）
- `confidence` (FLOAT) - 置信度分数
- `evidence` (JSONB) - 标签证据

## 使用示例

### 示例 1: 搜索春天的樱花景点

```python
query_intent = QueryIntent(
    name_candidates=[],
    query_tags=['cherry_blossom', 'blooming_flowers'],
    season_hint='spring',
    scene_hints=[],
    geo_hints=GeoHints(place_name=None, country=None),
    confidence_notes=[]
)

result = tool.search_with_llm_sql(query_intent, top_n=10)
```

生成的 SQL 会：
- JOIN `viewpoint_visual_tags` 表
- 使用 `tags @> '["cherry_blossom"]'::jsonb` 搜索标签
- 使用 `season = 'spring'` 过滤季节

### 示例 2: 搜索历史相关的景点

```python
query_intent = QueryIntent(
    name_candidates=['杭州'],
    query_tags=[],
    season_hint='unknown',
    scene_hints=['历史', '文化'],
    geo_hints=GeoHints(place_name='杭州', country='中国'),
    confidence_notes=[]
)

result = tool.search_with_llm_sql(query_intent, top_n=10)
```

生成的 SQL 会：
- JOIN `viewpoint_wiki` 表
- 使用 `extract_text ILIKE '%历史%'` 搜索历史信息
- 同时匹配名称 "杭州"

## LLM SQL 生成改进

### 更新的提示信息

1. **数据库 Schema**: 详细说明了如何搜索历史信息和标签
2. **查询模式**: 提供了 JSONB 操作符的使用示例
3. **JOIN 说明**: 说明了何时需要 JOIN 哪些表

### 参数提取逻辑

现在支持提取以下参数：
- 名称模式（name patterns）
- 类别（categories）
- 视觉标签（visual tags）- 转换为 JSONB 格式
- 场景提示（scene hints）- 用于 Wikipedia 文本搜索
- 国家变体（country variants）
- 季节（season）
- 限制数量（top_n）

## Fallback 机制

如果 LLM 生成的 SQL 有问题，系统会自动回退到传统搜索方法：

1. **名称搜索**: 优先使用名称匹配
2. **类别搜索**: 尝试类别过滤
3. **标签搜索**: 使用 `search_by_tags` 方法
4. **部分名称搜索**: 如果完整名称搜索失败，尝试部分匹配

## 注意事项

1. **JSONB 操作符**: 视觉标签搜索需要使用 `@>` 操作符，参数必须是 JSONB 格式
2. **文本搜索**: 历史信息搜索使用 `ILIKE` 进行模糊匹配
3. **性能**: JOIN 多个表可能影响性能，建议使用 `DISTINCT` 避免重复行
4. **参数类型**: 确保参数类型正确（字符串、JSONB、整数等）

## 未来改进

1. 改进 LLM SQL 生成的准确性
2. 添加更多验证规则，确保生成的 SQL 语法正确
3. 优化参数提取逻辑，减少类型错误
4. 添加查询缓存，提高性能

## 相关文件

- `app/tools/sql_search_tool.py` - SQL 搜索工具实现
- `app/schemas/query.py` - 查询意图数据结构
- `LLM_SQL_SEARCH.md` - LLM SQL 搜索功能文档
