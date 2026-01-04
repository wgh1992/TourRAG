# TourRAG 系统架构文档

## 概述

TourRAG 是一个**全本地、Tag 驱动**的景点多模态 RAG 系统，采用三层分离式架构，确保可控性、可解释性和可复现性。

## 核心设计原则

1. **全本地化**：所有外部数据提前抓取并落库
2. **Tag 驱动**：基于结构化 tags 进行检索和匹配
3. **严格约束**：LLM 职责边界明确，不直接访问数据库
4. **可解释性**：完整记录 SQL 查询和工具调用路径
5. **严格 JSON Schema**：输出格式固定，便于前端和自动化测试

## 三层架构

### 1. In-DB Retrieval（强约束、强可控）

**职责**：在完全本地的数据库中，通过 SQL 查询快速、稳定地生成景点候选集合。

**技术手段**：
- 名称与别名匹配（多语言、模糊匹配）
- 地理范围过滤（bbox、距离约束）
- 类别过滤（基于 OSM 标签映射）

**优势**：
- 查询速度快
- 行为完全可控
- SQL 结果可解释、可审计、可回归

**实现位置**：`app/services/retrieval.py`

### 2. External Enrichment（离线/准实时 → 本地化）

**职责**：在候选景点确定后，补齐该景点的百科信息与视觉元信息。

**数据来源**（均为本地镜像）：
- Wikipedia（文本摘要、章节、引用）
- Wikidata（结构化属性、QID）
- Wikimedia Commons（图像元信息，不存储图像本体）

**实现位置**：`app/services/enrichment.py`

### 3. LLM Understanding & Summarization（抽取 + 融合）

**职责**：利用 LLM 的理解能力，将多源信息转换为结构化、可解释的最终结果。

**LLM 在本系统中的职责（严格限定）**：
- ✅ 对用户文本/图像输入抽取 `query_tags` / `season_hint`
- ✅ 对百科文本进行弱监督抽取（tags + 证据）
- ✅ 融合 SQL 结果、百科信息与视觉 tags
- ✅ 输出严格 JSON

**LLM 禁止的操作**：
- ❌ 直接访问数据库
- ❌ 直接生成事实
- ❌ 直接推断视觉事实（必须有证据）

**实现位置**：
- `app/tools/extract_query_intent.py`（唯一 MCP Tool）
- `app/services/llm_service.py`（融合与重排）

## 数据模型

### 核心表结构

#### 1. `viewpoint_entity`（OSM 实体层）
- 权威 ID 层
- 存储 OSM 原始数据（name, category, geometry）
- 支持多语言名称和别名

#### 2. `viewpoint_wiki` / `viewpoint_wikidata`（增强层）
- 本地百科镜像
- 只读运行时查询

#### 3. `viewpoint_visual_tags`（派生层 - 核心）
- **系统唯一的视觉"真值层"**
- 按季节存储视觉 tags
- 附带证据字段（Commons 文件 ID、Wiki 句子引用等）
- 支持多种来源：`commons_vision`, `wiki_weak_supervision`, `user_image`, `manual`

#### 4. `viewpoint_commons_assets`（元信息层）
- 不存储图像本体
- 仅存储元信息（caption, categories, depicts_wikidata, hash 等）

## MCP Tool 设计

### 唯一工具：`extract_query_intent`

这是系统中**唯一允许 LLM 直接"理解用户输入"的入口**。

**输入**：
- `user_text`（可选）
- `user_images`（可选数组）
- `language`（zh/en/auto）

**输出**（严格 JSON Schema）：
```json
{
  "query_intent": {
    "name_candidates": ["string"],
    "query_tags": ["string"],  // 必须来自受控词表
    "season_hint": "spring|summer|autumn|winter|unknown",
    "scene_hints": ["string"],
    "geo_hints": {
      "place_name": "string|null",
      "country": "string|null"
    },
    "confidence_notes": ["string"]
  },
  "tag_schema_version": "v1.0.0"
}
```

**关键约束**：
- `query_tags` 必须来自受控词表
- 不允许生成自由文本 tag
- 不确定时：`season_hint = "unknown"`，并在 `confidence_notes` 中说明

## Tag 词表系统

### 版本管理

Tag 词表定义在 `config/tags/tag_schema_{version}.json`，支持版本控制。

### 三类 Tags

1. **Category Tags**：mountain, lake, temple, museum, park, coast, cityscape, monument, bridge, palace, tower, cave, waterfall, valley, island

2. **Visual Tags**：snow_peak, autumn_foliage, cherry_blossom, night_view, sunset, sunrise, foggy, rainy, snowy, sunny, cloudy, spring_greenery, summer_lush, winter_barren, ice, blooming_flowers, falling_leaves

3. **Scene Tags**：sunrise, sunset, hiking_trail, skyline_view, panoramic, close_up, aerial, ground_level, interior, exterior, crowded, empty, festival, ceremony

### 四季支持

视觉 tags 按季节存储：
- `spring`, `summer`, `autumn`, `winter`, `unknown`

季节判定顺序：
1. EXIF 拍摄时间
2. Commons 分类/描述文本
3. 视觉特征判别（雪/枫叶/樱花/植被密度等）

## 处理流程

```
用户输入（文本 + 可选图片）
    ↓
[1] extract_query_intent (MCP Tool)
    → 提取结构化意图（query_tags, season_hint, name_candidates）
    ↓
[2] In-DB Retrieval (SQL)
    → 基于名称/类别/地理范围查询
    → 返回 Top-N 候选（如 50）
    ↓
[3] External Enrichment（本地查询）
    → Wikipedia 摘要
    → Wikidata 属性
    → 视觉 tags（按季节过滤）
    ↓
[4] LLM Fusion & Ranking
    → 计算 tag 重叠分数
    → 季节匹配奖励
    → 生成最终 Top-K 结果（如 5）
    ↓
输出严格 JSON 结果
    - 景点身份识别（Top-K）
    - 历史摘要（带证据）
    - 视觉特点（结构化 tags）
    - 检索过程（SQL + 工具调用路径）
```

## 安全性与可控性

### 1. 数据隔离
- 所有外部数据提前抓取并落库
- 运行时仅查询本地数据库
- 不存储原始图像内容

### 2. LLM 职责边界
- LLM 不直接访问数据库
- LLM 不直接生成事实
- LLM 仅负责意图抽取和信息融合

### 3. 可审计性
- 所有 SQL 查询记录在响应中
- 所有工具调用记录在响应中
- 查询日志表（`query_log`）支持回归测试

### 4. 可解释性
- 每个结果附带 `match_explanation`
- 每个视觉 tag 附带 `evidence`
- 历史摘要附带可追溯证据

## 扩展点

### 1. 视觉 Tag 提取（离线）

**路径 A：Commons 图像 → 离线视觉模型 → Tags**
- 离线抓取 Commons 图像元信息
- 本地运行视觉标注器（CLIP / 多标签模型 / 离线 LLM-Vision）
- 输出 (season, tags, confidence, evidence)

**路径 B：百科文本 → 弱监督抽取 → Tags**
- 离线抽取句子/段落
- 规则词典 + LLM 抽取 season → tags
- 保存证据（句子 ID / hash）

### 2. 地理范围过滤
- 当前支持 bbox 过滤
- 可扩展为基于行政区关联
- 可扩展为距离约束（ST_DWithin）

### 3. 多语言支持
- 当前支持中文和英文
- Tag 词表可扩展多语言描述
- 名称匹配已支持多语言别名

## 性能优化

1. **数据库索引**：
   - GIN 索引（name_variants, tags）
   - GIST 索引（geometry）
   - pg_trgm 相似度索引（name_primary）

2. **查询优化**：
   - 先 SQL 召回 Top-N，再 LLM 重排 Top-K
   - 避免 LLM 处理大量候选

3. **缓存策略**（可扩展）：
   - 常见查询结果缓存
   - Tag 词表内存缓存

## 测试与回归

1. **单元测试**：`tests/test_extract_query_intent.py`
2. **查询日志**：`query_log` 表支持回归测试
3. **A/B 对比**：基于严格 JSON Schema，便于对比不同版本

## 部署建议

1. **数据库**：PostgreSQL 14+ with PostGIS
2. **应用服务**：FastAPI + Uvicorn
3. **LLM API**：OpenAI GPT-4o（可通过 MCP 替换）
4. **监控**：查询日志、执行时间、错误率

## 未来扩展

1. **图像处理**：集成视觉模型进行用户上传图像的 tag 提取
2. **实时更新**：定期同步 Wikipedia/Wikidata/Commons 数据
3. **推荐系统**：基于用户历史查询的个性化推荐
4. **多模态融合**：更深入的文本+图像联合理解

