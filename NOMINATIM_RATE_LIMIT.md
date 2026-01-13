# Nominatim 反向地理编码速率限制说明

## 问题

Nominatim API 有严格的速率限制：
- **每秒最多 1 次请求**
- 超过限制会返回 **503 Service Unavailable** 错误
- 频繁请求会导致超时

## 当前状态

从测试结果看：
- ✅ **类别信息已正确保存**（`viewpoint_category_norm`, `viewpoint_category_osm`）
- ❌ **国家地区信息未保存**（因为 Nominatim 速率限制）

## 解决方案

### 方案1：增加延迟（推荐用于小批量）

```bash
# 使用更长的批次延迟（至少3秒）
python scripts/manage_viewpoints.py download images --limit 10 --batch-delay 3.0
```

### 方案2：批量更新类别信息（不需要重新下载图像）

类别信息可以从 `viewpoint_entity` 表复制，不需要反向地理编码：

```sql
-- 更新类别信息（从viewpoint_entity复制）
UPDATE viewpoint_commons_assets vca
SET 
    viewpoint_category_norm = v.category_norm,
    viewpoint_category_osm = v.category_osm
FROM viewpoint_entity v
WHERE vca.viewpoint_id = v.viewpoint_id
  AND vca.downloaded_at IS NOT NULL
  AND (vca.viewpoint_category_norm IS NULL OR vca.viewpoint_category_osm IS NULL);
```

### 方案3：使用本地地理编码服务

如果需要大量获取国家地区信息，建议：
1. 使用本地 Nominatim 实例
2. 或使用其他地理编码服务（如 Google Geocoding API，需要 API key）
3. 或从 OSM 数据中直接提取（如果 `admin_area_ids` 包含相关信息）

### 方案4：异步批量处理

对于大量数据，可以：
1. 先下载所有图像（不获取国家地区信息）
2. 然后单独运行一个脚本来批量获取国家地区信息（使用更长的延迟）

## 当前代码改进

已实现的改进：
- ✅ 请求前延迟（1秒）
- ✅ 重试机制（最多2次）
- ✅ 指数退避（503错误时）
- ✅ 批次间延迟（至少3秒）

## 建议

### 对于测试/小批量数据

```bash
# 使用较长的延迟
python scripts/manage_viewpoints.py download images --limit 10 --batch-delay 5.0
```

### 对于生产环境/大量数据

1. **先更新类别信息**（不需要API调用）：
```sql
UPDATE viewpoint_commons_assets vca
SET 
    viewpoint_category_norm = v.category_norm,
    viewpoint_category_osm = v.category_osm
FROM viewpoint_entity v
WHERE vca.viewpoint_id = v.viewpoint_id
  AND vca.downloaded_at IS NOT NULL;
```

2. **然后单独获取国家地区信息**（使用更长的延迟）：
```bash
# 创建一个专门的脚本，每个请求间隔至少2秒
python scripts/get_country_info.py --delay 2.0
```

## 检查已保存的数据

```sql
-- 检查类别信息
SELECT 
    COUNT(*) as total,
    COUNT(viewpoint_category_norm) as with_category_norm,
    COUNT(viewpoint_category_osm) as with_category_osm,
    COUNT(viewpoint_country) as with_country,
    COUNT(viewpoint_region) as with_region
FROM viewpoint_commons_assets
WHERE downloaded_at IS NOT NULL;
```

## 总结

- ✅ **类别信息**：已正确保存，可以从 `viewpoint_entity` 复制
- ⚠️ **国家地区信息**：受 Nominatim 速率限制影响，需要更长的延迟或使用其他方案
- ✅ **多边形边界和面积**：对于多边形类型的景点，已正确计算和保存
