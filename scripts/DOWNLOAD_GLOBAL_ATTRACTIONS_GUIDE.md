# 全球下载Attraction景点指南

## 概述

`download_global_attractions.py` 脚本用于：
1. **清除数据库中所有数据**
2. **从全球随机下载10000个OSM的attraction景点**
3. **下载数据包含**：
   - ✅ 地理信息（坐标、多边形边界）
   - ✅ 国家/地区信息
   - ✅ 历史信息（Wikipedia/Wikidata）
   - ✅ 季节信息（仅季节，不包含复杂visual tags）
4. **不包含**：
   - ❌ 图像信息
   - ❌ 复杂visual tags（只保留季节信息和category）

## 快速开始

```bash
# 完整工作流：清除数据 → 下载10000个全球attraction景点
python scripts/download_global_attractions.py

# 自定义数量
python scripts/download_global_attractions.py --limit 5000

# 如果数据库已空，跳过删除步骤
python scripts/download_global_attractions.py --skip-delete

# 跳过确认提示
python scripts/download_global_attractions.py --yes
```

## 工作流程

脚本会自动执行以下步骤：

### 步骤1: 删除所有景点数据
- 使用 `delete_all_viewpoints.py` 删除所有现有景点
- 会删除所有相关数据（CASCADE）

### 步骤2: 从全球下载attraction景点
- 使用 `download_attraction_only.py` 从6个主要区域批量下载：
  - 中国
  - 欧洲
  - 北美
  - 南美
  - 亚洲其他地区
  - 中东和非洲
- 要求：`tourism=attraction` 或 `tourism=viewpoint`，必须有Wikipedia标签
- 每个区域下载约1666个景点（总计约10000个）
- 按popularity排序，保留前N个

### 步骤3: 下载地理信息和国家信息（不下载图像）
- 使用 `download_all_viewpoint_images.py --country-only`
- 只获取国家/地区信息，**不下载图像**
- 使用反向地理编码（Nominatim）获取国家信息

### 步骤4: 插入历史信息
- 使用 `insert_wiki_data.py` 插入Wikipedia/Wikidata数据
- 包含Wikipedia摘要、章节、引用等历史信息

### 步骤5: 生成季节信息（不生成复杂visual tags）
- 使用 `generate_season_only.py` 从Wikipedia文本提取季节信息
- **只生成季节信息**，tags字段只包含category（不包含复杂visual tags）
- 为每个景点生成spring、summer、autumn、winter季节记录

## 参数说明

```bash
python scripts/download_global_attractions.py [选项]

选项:
  --skip-delete        跳过删除步骤（如果数据库已为空）
  --limit LIMIT        最大下载数量（默认: 10000）
  --yes                跳过确认提示
```

## 数据内容

### 包含的数据

1. **地理信息**：
   - 坐标（经纬度）
   - 多边形边界（如果OSM数据中有）
   - 国家/地区信息（通过反向地理编码获取）

2. **历史信息**：
   - Wikipedia摘要文本
   - Wikipedia章节内容
   - Wikidata QID和claims
   - 引用信息

3. **季节信息**：
   - 每个景点的季节记录（spring, summer, autumn, winter）
   - 季节信息来源（mentioned/inferred）
   - 最小tags（只包含category）

### 不包含的数据

1. **图像信息**：
   - 不下载卫星图像
   - 不下载Commons图像
   - `viewpoint_commons_assets.image_blob` 为空

2. **复杂Visual Tags**：
   - 不生成复杂的visual tags（如snow_peak, cherry_blossom等）
   - tags字段只包含category（如"attraction"）
   - 只保留季节信息

## 验证结果

运行后检查数据库：

```bash
# 查看统计
python scripts/statistics_database.py

# 或直接查询数据库
psql tourrag_db -c "
SELECT 
    COUNT(*) as total,
    COUNT(DISTINCT CASE WHEN vca.viewpoint_country IS NOT NULL THEN v.viewpoint_id END) as with_geo,
    COUNT(DISTINCT CASE WHEN w.viewpoint_id IS NOT NULL THEN v.viewpoint_id END) as with_wiki,
    COUNT(DISTINCT CASE WHEN vt.viewpoint_id IS NOT NULL THEN v.viewpoint_id END) as with_season
FROM viewpoint_entity v
LEFT JOIN viewpoint_commons_assets vca ON v.viewpoint_id = vca.viewpoint_id
LEFT JOIN viewpoint_wiki w ON v.viewpoint_id = w.viewpoint_id
LEFT JOIN viewpoint_visual_tags vt ON v.viewpoint_id = vt.viewpoint_id
WHERE v.category_norm = 'attraction';
"
```

应该看到：
- ✅ 约10000个attraction类型景点
- ✅ 大部分有地理信息（国家）
- ✅ 大部分有历史信息（Wikipedia/Wikidata）
- ✅ 大部分有季节信息
- ✅ 没有图像数据

## 注意事项

1. **删除操作不可逆**：删除所有景点会永久删除所有相关数据
2. **下载时间**：全球下载可能需要较长时间（取决于网络和API限制）
3. **API限制**：
   - Overpass API有速率限制
   - Nominatim反向地理编码限制1请求/秒
   - OpenAI API（用于季节提取）有配额限制
4. **数据质量**：要求Wikipedia标签确保下载的是更著名的景点

## 故障排除

### 问题1: 下载数量不足10000

**原因**: 某些区域可能没有足够的attraction类型景点

**解决**: 
- 检查日志，查看哪些区域下载失败
- 可以手动增加某些区域的limit
- 或者接受实际下载的数量

### 问题2: 地理信息缺失

**原因**: Nominatim反向地理编码失败或超时

**解决**: 
- 检查网络连接
- 可以稍后重新运行 `download_all_viewpoint_images.py --country-only --category attraction`

### 问题3: 季节信息缺失

**原因**: OpenAI API调用失败或配额不足

**解决**: 
- 检查OpenAI API密钥配置
- 可以稍后重新运行 `generate_season_only.py`

## 相关脚本

- `scripts/download_global_attractions.py` - 主脚本（本指南）⭐
- `scripts/download_attraction_only.py` - 下载attraction景点
- `scripts/delete_all_viewpoints.py` - 删除所有景点
- `scripts/download_all_viewpoint_images.py` - 下载地理信息（--country-only）
- `scripts/insert_wiki_data.py` - 插入历史信息
- `scripts/generate_season_only.py` - 生成季节信息（仅季节，无复杂tags）

## 与完整工作流的区别

| 特性 | `setup_attraction_only.py` | `download_global_attractions.py` |
|------|---------------------------|----------------------------------|
| 图像下载 | ✅ 下载图像 | ❌ 不下载图像 |
| Visual Tags | ✅ 生成完整visual tags | ❌ 只生成季节信息 |
| 数据量 | 可自定义 | 固定10000个（可调整） |
| 区域 | 可指定单个区域 | 全球6个区域批量下载 |
| 用途 | 完整数据（含图像） | 轻量数据（无图像） |
