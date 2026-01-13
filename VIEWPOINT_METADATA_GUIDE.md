# 景点元数据下载指南

## 概述

更新后的下载脚本现在会为每个景点保存以下完整信息：

1. **经纬度坐标** - 景点的地理位置
2. **多边形边界** - 如果景点是多边形区域（如公园、湖泊等）
3. **覆盖面积** - 多边形区域的面积（平方米）
4. **类别属性** - 标准化类别和 OSM 原始标签
5. **国家/地区信息** - 通过反向地理编码获取

## 新增字段

### 数据库字段

在 `viewpoint_commons_assets` 表中新增了以下字段：

- `viewpoint_boundary` (GEOMETRY) - 多边形边界（如果是多边形）
- `viewpoint_area_sqm` (DOUBLE PRECISION) - 面积（平方米）
- `viewpoint_category_norm` (VARCHAR) - 标准化类别
- `viewpoint_category_osm` (JSONB) - OSM 原始类别标签
- `viewpoint_country` (VARCHAR) - 国家名称
- `viewpoint_region` (VARCHAR) - 地区/州/省名称
- `viewpoint_admin_areas` (JSONB) - 行政区信息

## 使用方法

### 运行迁移

首先运行数据库迁移以添加新字段：

```bash
psql -d tourrag_db -f migrations/003_add_viewpoint_metadata.sql
```

### 下载数据

```bash
# 下载所有景点的图像和元数据
python scripts/download_all_viewpoint_images.py

# 只下载未下载的景点
python scripts/download_all_viewpoint_images.py --skip-downloaded

# 限制数量（用于测试）
python scripts/download_all_viewpoint_images.py --limit 100
```

## 数据提取说明

### 1. 多边形边界

- **自动检测**：如果 `viewpoint_entity.geom` 是多边形或多边形集合，会自动提取边界
- **优化**：在查询时直接获取 WKT 格式，避免重复数据库查询
- **存储格式**：PostGIS Geometry 格式（WGS84/4326）
- **查询示例**：
  ```sql
  SELECT viewpoint_id, ST_AsGeoJSON(viewpoint_boundary) as boundary
  FROM viewpoint_commons_assets
  WHERE viewpoint_boundary IS NOT NULL;
  ```

### 2. 覆盖面积

- **计算方式**：使用 PostGIS `ST_Area()` 函数计算（地理坐标系）
- **单位**：平方米
- **查询示例**：
  ```sql
  SELECT viewpoint_id, name_primary, viewpoint_area_sqm
  FROM viewpoint_commons_assets vca
  JOIN viewpoint_entity ve ON vca.viewpoint_id = ve.viewpoint_id
  WHERE viewpoint_area_sqm IS NOT NULL
  ORDER BY viewpoint_area_sqm DESC;
  ```

### 3. 类别属性

- **标准化类别**：`category_norm` - 如 "mountain", "temple", "park" 等
- **OSM 标签**：`category_osm` - JSON 格式的原始 OSM 标签
- **查询示例**：
  ```sql
  SELECT viewpoint_category_norm, COUNT(*) as count
  FROM viewpoint_commons_assets
  WHERE viewpoint_category_norm IS NOT NULL
  GROUP BY viewpoint_category_norm
  ORDER BY count DESC;
  ```

### 4. 国家/地区信息

- **提取方式**：使用 Nominatim 反向地理编码 API（基于 OSM 数据）
- **数据来源**：从 OSM 数据中提取，包括：
  - 国家名称和代码
  - 地区/州/省/县名称
  - 城市/城镇/村庄名称
  - OSM 行政区 ID（如果可用）
- **包含信息**：
  - `viewpoint_country` - 国家名称
  - `viewpoint_region` - 地区/州/省名称
  - `viewpoint_admin_areas` - JSON 格式的完整行政区信息
- **查询示例**：
  ```sql
  SELECT viewpoint_country, viewpoint_region, COUNT(*) as count
  FROM viewpoint_commons_assets
  WHERE viewpoint_country IS NOT NULL
  GROUP BY viewpoint_country, viewpoint_region
  ORDER BY count DESC;
  ```

## 注意事项

### 反向地理编码限制

- **数据来源**：Nominatim 使用 OSM 数据，提供准确的行政区信息
- **速率限制**：Nominatim API 有速率限制（每秒 1 次请求）
- **超时处理**：如果请求超时，会跳过国家/地区信息提取，但其他数据仍会保存
- **建议**：大量下载时，考虑增加延迟或使用本地地理编码服务
- **改进**：现在会提取更详细的行政区信息，包括国家代码、城市、城镇等

### 多边形检测

- 只有 `ST_Polygon` 和 `ST_MultiPolygon` 类型的几何对象会提取边界
- 点（`ST_Point`）和线（`ST_LineString`）不会提取边界

### 面积计算

- 面积计算使用地理坐标系（WGS84），单位为平方米
- 对于非常大的区域，可能会有轻微误差

## 查询示例

### 查看所有有边界的景点

```sql
SELECT 
    ve.name_primary,
    vca.viewpoint_category_norm,
    vca.viewpoint_area_sqm,
    vca.viewpoint_country,
    ST_GeometryType(vca.viewpoint_boundary) as boundary_type
FROM viewpoint_commons_assets vca
JOIN viewpoint_entity ve ON vca.viewpoint_id = ve.viewpoint_id
WHERE vca.viewpoint_boundary IS NOT NULL;
```

### 按国家统计景点数量

```sql
SELECT 
    viewpoint_country,
    COUNT(*) as viewpoint_count,
    SUM(viewpoint_area_sqm) as total_area_sqm
FROM viewpoint_commons_assets
WHERE viewpoint_country IS NOT NULL
GROUP BY viewpoint_country
ORDER BY viewpoint_count DESC;
```

### 查找特定类别的景点

```sql
SELECT 
    ve.name_primary,
    vca.viewpoint_category_norm,
    vca.viewpoint_country,
    vca.viewpoint_region
FROM viewpoint_commons_assets vca
JOIN viewpoint_entity ve ON vca.viewpoint_id = ve.viewpoint_id
WHERE vca.viewpoint_category_norm = 'mountain'
ORDER BY ve.popularity DESC;
```

## 性能优化

1. **批量处理**：使用 `--batch-size` 和 `--batch-delay` 参数控制处理速度
2. **跳过已下载**：使用 `--skip-downloaded` 避免重复处理
3. **反向地理编码**：考虑缓存结果或使用本地地理编码服务以提高速度

## 相关文件

- `migrations/003_add_viewpoint_metadata.sql` - 数据库迁移文件
- `scripts/download_all_viewpoint_images.py` - 下载脚本
- `DOWNLOAD_ALL_VIEWPOINTS.md` - 基本下载指南

