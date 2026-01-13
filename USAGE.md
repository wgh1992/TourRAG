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

### 4. 使用 Web UI

启动服务后，在浏览器中访问 **http://localhost:8000** 即可使用图形界面：

- **文本搜索**：输入自然语言查询（支持中英文）
- **图片上传**：上传图片进行视觉搜索
- **结果展示**：查看匹配的景点及其详细信息
- **详情查看**：点击任意景点卡片查看完整信息

Web UI 功能：
- 实时查询意图展示
- 可视化标签和匹配度
- 响应式设计，支持移动端
- 景点详情模态窗口

### 5. 快速测试搜索功能

使用测试脚本快速验证搜索功能：

```bash
# 运行完整API测试套件
python test_api.py

# 测试Agent查询
python test_agent.py "Mount Fuji in winter"
python test_agent.py "春天的樱花寺庙"
```

测试脚本会显示：
- 健康检查状态
- 查询意图提取结果
- 搜索结果和匹配度
- MCP 工具使用情况

## API 使用示例

### 1. 健康检查

```bash
curl http://localhost:8000/health
```

响应示例：
```json
{
  "status": "healthy",
  "database": "connected"
}
```

### 2. 完整搜索示例（推荐）

这是最常用的端点，执行完整的搜索流程（MCP 推理 → SQL 检索 → 增强 → LLM 融合）：

```bash
# 示例 1: 搜索冬季的富士山
curl -X POST "http://localhost:8000/api/v1/query?user_text=Mount%20Fuji%20in%20winter&top_k=5" \
  -H "Content-Type: application/json"
```

响应示例：
```json
{
  "query_intent": {
    "name_candidates": ["Mount Fuji", "Fuji"],
    "query_tags": ["mountain", "snow_peak"],
    "season_hint": "winter",
    "scene_hints": [],
    "geo_hints": {
      "place_name": null,
      "country": null
    },
    "confidence_notes": []
  },
  "candidates": [
    {
      "viewpoint_id": 123,
      "name_primary": "Mount Fuji",
      "name_variants": {"name:en": "Mount Fuji", "name:ja": "富士山"},
      "category_norm": "mountain",
      "historical_summary": "Mount Fuji is Japan's highest peak...",
      "visual_tags": [
        {
          "season": "winter",
          "tags": ["snow_peak", "snowy", "mountain"],
          "confidence": 0.95,
          "evidence": [...],
          "tag_source": "wiki_weak_supervision"
        }
      ],
      "match_confidence": 0.92,
      "match_explanation": "Strong match: name matches 'Mount Fuji', winter season matches visual tags, snow_peak tag present"
    }
  ],
  "sql_queries": [...],
  "tool_calls": [
    {
      "tool": "extract_query_intent",
      "input": {...},
      "output": {...}
    }
  ],
  "execution_time_ms": 1234,
  "tag_schema_version": "v1.0.0"
}
```

```bash
# 示例 2: 中文搜索 - 春天的樱花
curl -X POST "http://localhost:8000/api/v1/query?user_text=春天的樱花寺庙&top_k=3&language=zh" \
  -H "Content-Type: application/json"
```

```bash
# 示例 3: 图片搜索
curl -X POST "http://localhost:8000/api/v1/query?top_k=5" \
  -F "user_text=这是什么景点？" \
  -F "user_images=@/path/to/image.jpg"
```

### 3. 提取查询意图（MCP Tool）

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

### 5. Agent 查询（GPT-4o-mini + 工具调用）

使用 GPT-4o-mini 智能代理，自动使用工具搜索和回答问题：

```bash
curl -X POST "http://localhost:8000/api/v1/agent/query?user_query=我想看冬天的富士山&language=zh"
```

响应示例：
```json
{
  "answer": "根据您的查询，我找到了以下关于冬季富士山的景点：\n\n1. **Mount Fuji** - 这是日本最高的山峰，在冬季时被雪覆盖，呈现出壮观的雪峰景象...",
  "tool_calls": [
    {
      "tool": "extract_query_intent",
      "arguments": {...},
      "result": {...}
    },
    {
      "tool": "search_viewpoints",
      "arguments": {...},
      "result": {...}
    }
  ],
  "iterations": 2
}
```

Agent 会自动：
- 提取查询意图
- 搜索数据库
- 获取详细信息
- 排名和解释结果
- 生成自然语言回答

### 6. 获取景点详情

```bash
curl http://localhost:8000/api/v1/viewpoint/1
```

## Python 客户端示例

```python
import requests

# 1. 完整搜索（推荐使用）
response = requests.post(
    "http://localhost:8000/api/v1/query",
    params={
        "user_text": "Mount Fuji in winter",
        "top_k": 5,
        "language": "en"
    }
)
results = response.json()

print(f"Query Intent: {results['query_intent']}")
print(f"Found {len(results['candidates'])} candidates in {results['execution_time_ms']}ms")
print("\nResults:")
for candidate in results['candidates']:
    print(f"\n- {candidate['name_primary']}")
    print(f"  Match: {candidate['match_confidence']:.2%}")
    print(f"  Explanation: {candidate['match_explanation']}")
    if candidate['visual_tags']:
        for vt in candidate['visual_tags']:
            print(f"  {vt['season']}: {', '.join(vt['tags'])}")

# 2. 提取查询意图（仅提取，不搜索）
response = requests.post(
    "http://localhost:8000/api/v1/extract-query-intent",
    json={
        "user_text": "mountain with snow in winter",
        "language": "en"
    }
)
intent = response.json()
print(f"\nExtracted Intent: {intent['query_intent']}")

# 3. 获取景点详情
viewpoint_id = results['candidates'][0]['viewpoint_id']
detail = requests.get(f"http://localhost:8000/api/v1/viewpoint/{viewpoint_id}").json()
print(f"\nViewpoint Detail: {detail['name_primary']}")
if detail.get('wikipedia'):
    print(f"Summary: {detail['wikipedia']['extract_text'][:200]}...")
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

