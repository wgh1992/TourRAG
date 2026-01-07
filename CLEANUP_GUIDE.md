# 数据库清理指南

## 概述

系统要求所有景点必须包含：
1. ✅ **历史信息**（Wikipedia / Wikidata）
2. ✅ **视觉 Tags**（LLM 提取的结构化 tags）

不符合要求的景点将被从数据库中删除。

## 模型更新

所有脚本已更新为使用 **gpt-4o-mini**（成本更低，仍支持视觉功能）：
- `app/config.py`: 默认模型改为 `gpt-4o-mini`
- `app/tools/extract_query_intent.py`: 使用 `gpt-4o-mini`
- `scripts/generate_visual_tags_from_wiki.py`: 使用 `gpt-4o-mini`

## 清理脚本

### 1. 检查不完整的景点

```bash
python scripts/cleanup_incomplete_viewpoints.py
```

这会显示：
- 缺少 Wikipedia 的景点数量
- 缺少 Wikidata 的景点数量
- 缺少视觉 tags 的景点数量
- 示例景点列表

### 2. 执行清理

```bash
# Dry run（预览，不实际删除）
python scripts/cleanup_incomplete_viewpoints.py

# 实际删除（需要 --execute）
python scripts/cleanup_incomplete_viewpoints.py --execute
```

### 3. 清理选项

**默认模式**（要求历史信息 AND tags）：
```bash
python scripts/cleanup_incomplete_viewpoints.py --execute
```
删除缺少历史信息 **或** 缺少 tags 的景点

**仅要求历史信息**：
```bash
python scripts/cleanup_incomplete_viewpoints.py --require-history-only --execute
```
只删除缺少历史信息的景点（不要求 tags）

**仅要求 tags**：
```bash
python scripts/cleanup_incomplete_viewpoints.py --require-tags-only --execute
```
只删除缺少 tags 的景点（不要求历史信息）

## 完整工作流

### 方案 1：先生成 tags，再清理

```bash
# 1. 为所有景点生成视觉 tags
python scripts/generate_visual_tags_from_wiki.py

# 2. 清理仍然不完整的景点
python scripts/cleanup_incomplete_viewpoints.py --execute
```

### 方案 2：使用自动化脚本

```bash
# 生成 tags 并清理（一步完成）
python scripts/cleanup_and_generate_tags.py --generate-tags --cleanup --execute
```

### 方案 3：分批处理

```bash
# 第一批：生成前 1000 个景点的 tags
python scripts/generate_visual_tags_from_wiki.py --limit 1000

# 清理已处理但仍有问题的
python scripts/cleanup_incomplete_viewpoints.py --execute

# 继续下一批
python scripts/generate_visual_tags_from_wiki.py --limit 1000
```

## 当前状态

根据最新检查：
- ✅ **历史信息**：10,002 个景点（100%）
- ⚠️ **视觉 Tags**：308 个景点（3.1%）
- ❌ **需要清理**：9,694 个景点缺少 tags

## 推荐流程

### 快速清理（如果不需要所有景点）

```bash
# 只保留有 tags 的景点
python scripts/cleanup_incomplete_viewpoints.py --require-tags-only --execute
```

### 完整流程（生成所有 tags）

```bash
# 1. 生成所有景点的视觉 tags（使用 gpt-4o-mini，成本更低）
python scripts/generate_visual_tags_from_wiki.py

# 2. 清理仍然不完整的景点
python scripts/cleanup_incomplete_viewpoints.py --execute

# 3. 验证最终状态
python scripts/ensure_complete_data.py
```

## 注意事项

### 删除操作

- ⚠️ **不可逆**：删除操作无法撤销
- ✅ **级联删除**：相关表数据会自动删除（CASCADE）
- 📊 **影响范围**：删除的景点及其所有关联数据

### 成本考虑

使用 `gpt-4o-mini` 的成本：
- 比 `gpt-4o` 便宜约 10-15 倍
- 处理 9,694 个景点约需 $5-10（vs $50-100 for gpt-4o）
- 仍支持视觉功能

### 数据完整性

清理后，所有保留的景点将：
- ✅ 有完整的 Wikipedia 历史信息
- ✅ 有完整的 Wikidata 结构化数据
- ✅ 有 LLM 提取的视觉 tags（带证据）
- ✅ 支持四季查询和视觉匹配

## 验证

清理后验证：

```bash
python scripts/ensure_complete_data.py
```

应该看到：
- ✅ 所有景点都有历史信息
- ✅ 所有景点都有视觉 tags
- ✅ 覆盖率 100%

