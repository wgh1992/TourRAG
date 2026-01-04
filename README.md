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

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 数据库设置

```bash
# 创建数据库
createdb tourrag_db

# 运行迁移
psql -d tourrag_db -f migrations/001_initial_schema.sql
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入必要的配置
```

### 4. 启动服务

```bash
uvicorn app.main:app --reload
```

## 数据模型

### 核心表结构

- `viewpoint_entity`: OSM 景点实体
- `viewpoint_wiki`: Wikipedia 百科文本
- `viewpoint_wikidata`: Wikidata 结构化属性
- `viewpoint_visual_tags`: 视觉特点（核心）
- `viewpoint_commons_assets`: Commons 图像元信息

## API 文档

启动服务后访问：http://localhost:8000/docs

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

