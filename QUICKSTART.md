# TourRAG 快速启动指南

## 前置条件检查

### 1. 确认数据库已初始化
```bash
# 检查数据库连接
psql -d tourrag_db -c "SELECT COUNT(*) FROM viewpoint_entity;"
```

### 2. 确认环境变量已配置
```bash
# 检查 .env 文件
cat .env | grep OPENAI_API_KEY
```

## 启动服务

### 方法 1：直接启动（开发模式）
```bash
cd /Users/z3548881/Desktop/TourRAG/TourRAG_code
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 方法 2：后台运行
```bash
# 启动服务（后台运行）
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > app.log 2>&1 &

# 查看日志
tail -f app.log

# 停止服务
pkill -f "uvicorn app.main:app"
```

## 验证服务运行

### 1. 健康检查
```bash
curl http://localhost:8000/health
```

预期响应：
```json
{
  "status": "healthy",
  "database": "connected"
}
```

### 2. 查看 API 文档
在浏览器中打开：
```
http://localhost:8000/docs
```

## 测试 API

### 1. 提取查询意图（MCP Tool）
```bash
curl -X POST http://localhost:8000/api/v1/extract-query-intent \
  -H "Content-Type: application/json" \
  -d '{
    "user_text": "我想看春天的樱花，最好是日本的寺庙",
    "language": "zh"
  }'
```

### 2. 完整查询（文本）
```bash
curl -X POST "http://localhost:8000/api/v1/query?user_text=mountain&top_k=5" \
  -H "Content-Type: application/json"
```

### 3. 完整查询（中文）
```bash
curl -X POST "http://localhost:8000/api/v1/query?user_text=富士山&top_k=3" \
  -H "Content-Type: application/json"
```

### 4. 获取景点详情
```bash
curl http://localhost:8000/api/v1/viewpoint/1
```

## Python 客户端示例

创建测试脚本 `test_api.py`：

```python
import requests
import json

BASE_URL = "http://localhost:8000"

# 1. 健康检查
response = requests.get(f"{BASE_URL}/health")
print("Health Check:", response.json())

# 2. 提取查询意图
response = requests.post(
    f"{BASE_URL}/api/v1/extract-query-intent",
    json={
        "user_text": "mountain with snow in winter",
        "language": "en"
    }
)
intent = response.json()
print("\nQuery Intent:")
print(json.dumps(intent, indent=2, ensure_ascii=False))

# 3. 完整查询
response = requests.post(
    f"{BASE_URL}/api/v1/query",
    params={
        "user_text": "mountain",
        "top_k": 5
    }
)
results = response.json()
print(f"\nFound {len(results['candidates'])} candidates:")
for i, candidate in enumerate(results['candidates'], 1):
    print(f"{i}. {candidate['name_primary']}")
    print(f"   Category: {candidate['category_norm']}")
    print(f"   Confidence: {candidate['match_confidence']:.2f}")
    if candidate.get('historical_summary'):
        print(f"   Summary: {candidate['historical_summary'][:100]}...")
    print()
```

运行：
```bash
python test_api.py
```

## 常见问题

### 1. 端口被占用
```bash
# 查找占用 8000 端口的进程
lsof -i :8000

# 杀死进程
kill -9 <PID>

# 或使用其他端口
uvicorn app.main:app --port 8001
```

### 2. 数据库连接失败
```bash
# 检查 PostgreSQL 是否运行
pg_isready

# 检查数据库是否存在
psql -l | grep tourrag_db
```

### 3. OpenAI API 错误
```bash
# 检查 API key 是否正确
python -c "from app.config import settings; print(settings.OPENAI_API_KEY[:20])"
```

## 性能测试

### 使用 Apache Bench (ab)
```bash
# 安装 ab（如果未安装）
# macOS: brew install httpd
# Ubuntu: sudo apt-get install apache2-utils

# 测试健康检查端点
ab -n 100 -c 10 http://localhost:8000/health
```

## 生产环境部署

### 使用 Gunicorn（推荐）
```bash
# 安装 gunicorn
pip install gunicorn

# 启动（多 worker）
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 使用 Docker（可选）
```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 监控和日志

### 查看查询日志
```bash
# 查看最近的查询
psql -d tourrag_db -c "
SELECT 
    created_at,
    user_text,
    execution_time_ms,
    jsonb_array_length(results) as result_count
FROM query_log
ORDER BY created_at DESC
LIMIT 10;
"
```

### 查看系统统计
```bash
# 数据库统计
psql -d tourrag_db -c "
SELECT 
    'Viewpoints' as type, COUNT(*) as count FROM viewpoint_entity
UNION ALL
SELECT 'Wikipedia', COUNT(*) FROM viewpoint_wiki
UNION ALL
SELECT 'Wikidata', COUNT(*) FROM viewpoint_wikidata
UNION ALL
SELECT 'Visual Tags', COUNT(*) FROM viewpoint_visual_tags;
"
```

