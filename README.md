# TourRAG - 景点多模态 RAG 系统

## 项目概述

TourRAG 是一个面向"景点问答/识别/推荐"的多模态智能系统，在受控、本地化、可解释的条件下，对景点进行识别、理解与推荐。

## 核心特性

- ✅ **全本地化**：所有外部数据提前抓取并落库
- ✅ **Tag 驱动**：基于结构化 tags 进行检索和匹配
- ✅ **四季支持**：特别强调四季相关视觉特征
- ✅ **可解释性**：完整记录 SQL 与工具调用路径
- ✅ **严格 JSON Schema**：输出格式固定，便于前端渲染和自动化测试

## 系统架构

### 三层分离式架构

1. **In-DB Retrieval**：基于 PostgreSQL 的快速 SQL 查询
2. **External Enrichment**：本地百科镜像（Wikipedia/Wikidata/Commons）
3. **LLM Understanding & Summarization**：结构化信息抽取与融合

## 技术栈

- Python 3.10+
- PostgreSQL 14+ (with PostGIS)
- FastAPI
- OpenAI GPT-4o (via MCP)
- pg_trgm extension

## 快速开始 / 运行程序

下面以 Windows PowerShell 为例，项目目录为 `E:\codex\TourRAG`。

### 1. 进入项目目录

```powershell
cd E:\codex\TourRAG
```

### 2. 创建并启用虚拟环境（首次运行）

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

如果 PowerShell 阻止执行脚本，可以先运行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

Linux/macOS 对应命令：

```bash
python -m venv venv
source venv/bin/activate
```

### 3. 安装依赖（首次运行）

```powershell
python -m pip install -r requirements.txt
```

### 4. 配置环境变量

项目根目录需要有 `.env` 文件，至少包含：

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/tourrag_db
OPENAI_API_KEY=你的 OpenAI API Key
OPENAI_MODEL=gpt-4o-mini
MCP_SERVER_URL=http://localhost:8001/mcp
```

如果还没有数据库，需要先创建 PostgreSQL 数据库并执行迁移：

```powershell
createdb tourrag_db
psql -d tourrag_db -f migrations/001_initial_schema.sql
```

### 5. 启动主服务

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8008 --reload
```

启动成功后访问：

- 前端页面：http://127.0.0.1:8008/
- API 文档：http://127.0.0.1:8008/docs

### 6. 可选：启动 MCP 服务

如果需要使用 FastMCP retrieval tools，另开一个 PowerShell 窗口运行：

```powershell
cd E:\codex\TourRAG
.\venv\Scripts\Activate.ps1
python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8001
```

## 数据模型

### 核心表结构

- `viewpoint_entity`: OSM 景点实体
- `viewpoint_wiki`: Wikipedia 百科文本
- `viewpoint_wikidata`: Wikidata 结构化属性
- `viewpoint_visual_tags`: 视觉特点（核心）
- `viewpoint_commons_assets`: Commons 图像元信息

## API 文档

启动服务后访问：http://127.0.0.1:8008/docs

## 项目结构

```
TourRAG_code/
├── app/
│   ├── main.py              # FastAPI 主应用
│   ├── models/              # 数据模型
│   ├── services/            # 业务逻辑层
│   │   ├── retrieval.py    # In-DB Retrieval
│   │   ├── enrichment.py   # External Enrichment
│   │   └── llm_service.py  # LLM Understanding
│   ├── tools/               # MCP Tools
│   │   └── extract_query_intent.py
│   └── schemas/             # Pydantic schemas
├── migrations/              # 数据库迁移脚本
├── config/                  # 配置文件
│   └── tags/               # Tag 词表定义
└── tests/                  # 测试文件
```

## License

MIT

## FastMCP server

TourRAG also exposes its retrieval tools as a FastMCP 3.x server.

Install dependencies:

```bash
pip install -r requirements.txt
```

Run over Streamable HTTP:

```bash
python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8001
```

Run over stdio for local MCP clients:

```bash
python -m app.mcp_server --transport stdio
```

