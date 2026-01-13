# 统一管理指南

## 概述

本项目现在提供了统一的管理接口，包括：
1. **统一管理脚本** (`scripts/manage_viewpoints.py`) - 整合所有操作
2. **统一数据库视图** - 合并多个表的数据，便于查询

## 快速开始

### 使用统一脚本

```bash
# 查看所有可用命令
python scripts/manage_viewpoints.py --help

# 查看数据库状态
python scripts/manage_viewpoints.py status

# 运行完整工作流
python scripts/manage_viewpoints.py workflow --limit 10
```

详细使用说明请参考：`scripts/MANAGE_VIEWPOINTS_GUIDE.md`

## 数据库视图

运行迁移 `004_create_unified_views.sql` 后，可以使用以下统一视图：

### 1. `viewpoint_complete` - 完整景点信息

合并所有表的数据，包括：
- 基本信息（entity）
- Wikipedia 数据
- Wikidata 数据
- 图像和元数据（commons_assets）
- 视觉标签

```sql
-- 查询完整信息
SELECT * FROM viewpoint_complete WHERE viewpoint_id = 1;

-- 查询有图像的景点
SELECT * FROM viewpoint_complete WHERE has_image = true;
```

### 2. `viewpoint_with_images` - 有图像的景点

只包含已下载图像的景点及其元数据：

```sql
-- 查询所有有图像的景点
SELECT 
    viewpoint_id,
    name_primary,
    viewpoint_country,
    viewpoint_area_sqm,
    downloaded_at
FROM viewpoint_with_images
ORDER BY downloaded_at DESC;
```

### 3. `viewpoint_metadata_summary` - 元数据摘要

包含所有元数据字段的摘要视图：

```sql
-- 查询有边界和面积的景点
SELECT 
    viewpoint_id,
    name_primary,
    area_sqm,
    viewpoint_country,
    viewpoint_region
FROM viewpoint_metadata_summary
WHERE viewpoint_boundary IS NOT NULL
ORDER BY area_sqm DESC;
```

### 4. `viewpoint_completeness` - 完整性检查

显示每个景点的数据完整性：

```sql
-- 查找不完整的景点
SELECT 
    viewpoint_id,
    name_primary,
    completeness_score,
    has_geometry,
    has_wikipedia,
    has_wikidata,
    has_tags,
    has_image,
    has_boundary,
    has_country
FROM viewpoint_completeness
WHERE completeness_score < 8
ORDER BY completeness_score ASC;
```

### 5. `viewpoint_statistics` - 统计信息

整体统计信息：

```sql
-- 查看整体统计
SELECT * FROM viewpoint_statistics;
```

### 6. 辅助函数

```sql
-- 获取特定景点的完整性信息
SELECT * FROM get_viewpoint_completeness(1);
```

## 数据表结构说明

### 核心表

1. **`viewpoint_entity`** - 景点基本信息（OSM数据）
   - 名称、类别、地理位置
   - 不存储图像

2. **`viewpoint_commons_assets`** - 图像和元数据主表 ⭐
   - **图像数据**：`image_blob` (BYTEA)
   - **图像元数据**：`image_geometry`, `image_exif`, `image_width`, `image_height`
   - **景点元数据**：
     - `viewpoint_boundary` - 多边形边界
     - `viewpoint_area_sqm` - 覆盖面积
     - `viewpoint_category_norm` - 标准化类别
     - `viewpoint_category_osm` - OSM类别标签
     - `viewpoint_country` - 国家名称
     - `viewpoint_region` - 地区/州/省
     - `viewpoint_admin_areas` - 行政区信息（JSONB）

3. **`viewpoint_wiki`** - Wikipedia信息
   - 文本摘要、章节结构

4. **`viewpoint_wikidata`** - Wikidata信息
   - QID、claims数据

5. **`viewpoint_visual_tags`** - 视觉标签
   - 季节标签、置信度

### 关系图

```
viewpoint_entity (主表)
├── viewpoint_wiki (1:1)
├── viewpoint_wikidata (1:1)
├── viewpoint_visual_tags (1:N)
└── viewpoint_commons_assets (1:N)
    └── 包含所有图像和元数据
```

## 常用查询示例

### 查询有完整元数据的景点

```sql
SELECT 
    v.viewpoint_id,
    v.name_primary,
    vca.viewpoint_boundary IS NOT NULL as has_boundary,
    vca.viewpoint_area_sqm,
    vca.viewpoint_category_norm,
    vca.viewpoint_country,
    vca.viewpoint_region
FROM viewpoint_entity v
INNER JOIN viewpoint_commons_assets vca ON v.viewpoint_id = vca.viewpoint_id
WHERE vca.viewpoint_boundary IS NOT NULL
   OR vca.viewpoint_country IS NOT NULL
ORDER BY v.popularity DESC;
```

### 按国家统计景点

```sql
SELECT 
    viewpoint_country,
    COUNT(*) as viewpoint_count,
    SUM(viewpoint_area_sqm) as total_area_sqm,
    AVG(viewpoint_area_sqm) as avg_area_sqm
FROM viewpoint_commons_assets
WHERE viewpoint_country IS NOT NULL
GROUP BY viewpoint_country
ORDER BY viewpoint_count DESC;
```

### 查询特定类别的景点及其元数据

```sql
SELECT 
    v.viewpoint_id,
    v.name_primary,
    vca.viewpoint_boundary,
    vca.viewpoint_area_sqm,
    vca.viewpoint_country,
    vca.viewpoint_region,
    ST_AsGeoJSON(vca.viewpoint_boundary) as boundary_geojson
FROM viewpoint_entity v
INNER JOIN viewpoint_commons_assets vca ON v.viewpoint_id = vca.viewpoint_id
WHERE vca.viewpoint_category_norm = 'mountain'
  AND vca.viewpoint_boundary IS NOT NULL;
```

### 使用统一视图查询

```sql
-- 使用完整视图
SELECT 
    viewpoint_id,
    name_primary,
    viewpoint_country,
    viewpoint_area_sqm,
    has_image,
    tag_count
FROM viewpoint_complete
WHERE viewpoint_country = 'Japan'
ORDER BY popularity DESC;

-- 使用完整性视图查找不完整的景点
SELECT 
    viewpoint_id,
    name_primary,
    completeness_score
FROM viewpoint_completeness
WHERE completeness_score < 6
ORDER BY completeness_score ASC;
```

## 迁移指南

### 从原脚本迁移到统一脚本

| 原命令 | 新命令 |
|--------|--------|
| `python scripts/init_db.py` | `python scripts/manage_viewpoints.py init` |
| `python scripts/insert_osm_data.py` | `python scripts/manage_viewpoints.py insert osm` |
| `python scripts/download_all_viewpoint_images.py --limit 10` | `python scripts/manage_viewpoints.py download images --limit 10` |
| `python scripts/generate_visual_tags_from_wiki.py --limit 100` | `python scripts/manage_viewpoints.py generate-tags --limit 100` |
| `python scripts/check_downloaded_images.py` | `python scripts/manage_viewpoints.py check-images` |
| `python scripts/ensure_complete_data.py` | `python scripts/manage_viewpoints.py check-completeness` |

### 运行视图迁移

```bash
# 创建统一视图
psql -d tourrag_db -f migrations/004_create_unified_views.sql
```

## 最佳实践

1. **首次设置**：使用 `workflow` 命令运行完整流程
2. **日常维护**：使用 `status` 检查状态，使用 `check-completeness` 检查完整性
3. **批量操作**：使用 `--limit` 参数先测试少量数据
4. **查询数据**：优先使用统一视图而不是直接查询多个表

## 相关文档

- `scripts/MANAGE_VIEWPOINTS_GUIDE.md` - 统一脚本详细使用指南
- `VIEWPOINT_METADATA_GUIDE.md` - 元数据字段说明
- `migrations/004_create_unified_views.sql` - 视图定义
