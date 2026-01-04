
# TourRAG

景点多模态 RAG 系统 - 全本地、Tag 驱动

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/wgh1992/TourRAG.git
cd TourRAG

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的配置

# 4. 初始化数据库
python scripts/init_db.py

# 5. 启动服务
uvicorn app.main:app --reload
```

## 功能特性

- ✅ 全本地化数据查询
- ✅ Tag 驱动的检索机制
- ✅ GPT-4o 图像处理
- ✅ 四季视觉特征支持
- ✅ 严格 JSON Schema 输出

## 文档

- [README.md](README.md) - 项目概述
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构文档
- [USAGE.md](USAGE.md) - 使用指南
- [IMAGE_PROCESSING.md](IMAGE_PROCESSING.md) - 图像处理说明

## License

MIT

