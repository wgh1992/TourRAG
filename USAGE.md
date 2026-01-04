# TourRAG 使用指南

## 快速开始

### 1. 环境设置

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的配置
```

### 2. 数据库初始化

```bash
# 确保 PostgreSQL 已安装并运行
# 创建数据库
createdb tourrag_db

# 运行迁移脚本
python scripts/init_db.py

# (可选) 插入示例数据
python scripts/insert_sample_data.py
```

### 3. 启动服务

```bash
uvicorn app.main:app --reload
```

服务将在 http://localhost:8000 启动

## API 使用示例

### 1. 健康检查

```bash
curl http://localhost:8000/health
```

### 2. 提取查询意图（MCP Tool）

```bash
curl -X POST http://localhost:8000/api/v1/extract-query-intent \
  -H "Content-Type: application/json" \
  -d '{
    "user_text": "我想看春天的樱花，最好是日本的寺庙",
    "language": "zh"
  }'
```

响应示例：
```json
{
  "query_intent": {
    "name_candidates": [],
    "query_tags": ["cherry_blossom", "temple"],
    "season_hint": "spring",
    "scene_hints": [],
    "geo_hints": {
      "place_name": "日本",
      "country": null
    },
    "confidence_notes": []
  },
  "tag_schema_version": "v1.0.0"
}
```

### 3. 完整查询（文本输入）

```bash
curl -X POST "http://localhost:8000/api/v1/query?user_text=Mount Fuji winter&top_k=3" \
  -H "Content-Type: application/json"
```

### 4. 完整查询（文本 + 图片）

```bash
curl -X POST "http://localhost:8000/api/v1/query?top_k=5" \
  -F "user_text=这是什么景点？" \
  -F "user_images=@/path/to/image.jpg"
```

### 5. 获取景点详情

```bash
curl http://localhost:8000/api/v1/viewpoint/1
```

## Python 客户端示例

```python
import requests

# 1. 提取查询意图
response = requests.post(
    "http://localhost:8000/api/v1/extract-query-intent",
    json={
        "user_text": "mountain with snow in winter",
        "language": "en"
    }
)
intent = response.json()
print(intent)

# 2. 完整查询
response = requests.post(
    "http://localhost:8000/api/v1/query",
    params={
        "user_text": "Mount Fuji",
        "top_k": 5
    }
)
results = response.json()
print(f"Found {len(results['candidates'])} candidates")
for candidate in results['candidates']:
    print(f"- {candidate['name_primary']}: {candidate['match_confidence']:.2f}")
```

## 系统架构说明

### 处理流程

1. **用户输入** → `extract_query_intent` MCP Tool
   - 提取结构化意图（name_candidates, query_tags, season_hint）
   - 严格使用受控词表

2. **In-DB Retrieval** → SQL 查询
   - 基于名称、类别、地理范围
   - 返回 Top-N 候选

3. **External Enrichment** → 本地百科数据
   - Wikipedia 摘要
   - Wikidata 属性
   - 视觉 tags（按季节）

4. **LLM Fusion** → 融合与重排
   - 计算 tag 重叠分数
   - 季节匹配奖励
   - 生成最终 Top-K 结果

### 数据流

```
用户输入 (文本/图片)
    ↓
extract_query_intent (MCP Tool)
    ↓
结构化意图 (query_tags, season_hint)
    ↓
SQL 查询 (viewpoint_entity)
    ↓
候选列表 (Top-N)
    ↓
百科增强 (wiki/wikidata/visual_tags)
    ↓
LLM 融合与重排
    ↓
最终结果 (Top-K, 严格 JSON)
```

## Tag 词表管理

Tag 词表定义在 `config/tags/tag_schema_v1.0.0.json`。

### 类别 Tags (Categories)
- mountain, lake, temple, museum, park, coast, cityscape, monument, bridge, palace, tower, cave, waterfall, valley, island

### 视觉 Tags (Visual)
- snow_peak, autumn_foliage, cherry_blossom, night_view, sunset, sunrise, foggy, rainy, snowy, sunny, cloudy, spring_greenery, summer_lush, winter_barren, ice, blooming_flowers, falling_leaves

### 场景 Tags (Scene)
- sunrise, sunset, hiking_trail, skyline_view, panoramic, close_up, aerial, ground_level, interior, exterior, crowded, empty, festival, ceremony

## 注意事项

1. **全本地化**：所有外部数据必须提前抓取并落库
2. **不存储图像**：只存储视觉 tags 和元信息
3. **严格 JSON Schema**：输出格式固定，便于前端和测试
4. **可解释性**：所有 SQL 查询和工具调用都记录在响应中

## 开发与测试

```bash
# 运行测试
pytest tests/

# 代码格式化
black app/

# 类型检查
mypy app/
```

