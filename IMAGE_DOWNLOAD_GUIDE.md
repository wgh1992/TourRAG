# 图像下载和存储指南

本指南说明如何下载 Wikimedia Commons 图像并存储到数据库中，包括原始图像数据和经纬度信息。

## 功能概述

TourRAG 系统支持：
1. **从 Wikimedia Commons 下载图像**：自动下载 Commons 资产对应的原始图像
2. **提取 EXIF 元数据**：包括 GPS 坐标、拍摄时间、相机信息等
3. **从 Commons API 获取地理标签**：如果 EXIF 中没有 GPS 信息，尝试从 Commons API 获取
4. **存储图像和经纬度**：将图像二进制数据、EXIF 元数据和地理坐标存储到 PostgreSQL 数据库

## 数据库扩展

首先需要运行数据库迁移来添加图像存储字段：

```bash
psql -d tourrag_db -f migrations/002_add_image_storage.sql
```

迁移脚本会添加以下字段到 `viewpoint_commons_assets` 表：
- `image_blob`: 图像二进制数据 (BYTEA)
- `image_geometry`: 图像地理位置 (PostGIS Point, WGS84)
- `image_exif`: EXIF 元数据 (JSONB)
- `image_width`, `image_height`: 图像尺寸
- `image_format`: 图像格式 (JPEG, PNG 等)
- `file_size_bytes`: 文件大小
- `downloaded_at`: 下载时间戳

## 安装依赖

确保已安装必要的 Python 包：

```bash
pip install -r requirements.txt
```

新增的依赖包括：
- `exifread`: 用于读取 EXIF 元数据（包括 GPS 坐标）
- `requests`: 用于下载图像

## 使用方法

### 基本用法

下载所有未下载的 Commons 图像：

```bash
python scripts/download_commons_images.py
```

### 选项参数

```bash
# 限制下载数量
python scripts/download_commons_images.py --limit 100

# 只下载特定景点的图像
python scripts/download_commons_images.py --viewpoint-id 123

# 跳过已下载的图像（默认行为）
python scripts/download_commons_images.py --skip-downloaded

# 设置批处理大小（用于速率限制）
python scripts/download_commons_images.py --batch-size 20
```

### 示例

```bash
# 下载前 50 个未下载的图像
python scripts/download_commons_images.py --limit 50 --skip-downloaded

# 为特定景点下载所有图像
python scripts/download_commons_images.py --viewpoint-id 42
```

## 工作流程

1. **查询数据库**：查找需要下载图像的 Commons 资产记录
2. **构建下载 URL**：根据 Commons 文件 ID 生成直接下载链接
3. **下载图像**：使用 HTTP 请求下载图像二进制数据
4. **提取 EXIF**：从图像中提取 EXIF 元数据，包括 GPS 坐标
5. **获取地理标签**：如果 EXIF 中没有 GPS，尝试从 Commons API 获取
6. **存储到数据库**：将图像数据、EXIF 和地理坐标存储到数据库

## 地理坐标提取

系统支持两种方式获取图像的地理坐标：

### 1. EXIF GPS 数据

从图像的 EXIF 元数据中提取 GPS 坐标：
- 读取 `GPS GPSLatitude` 和 `GPS GPSLongitude`
- 转换为十进制度数格式
- 考虑 `GPS GPSLatitudeRef` 和 `GPS GPSLongitudeRef`（N/S, E/W）

### 2. Wikimedia Commons API

如果 EXIF 中没有 GPS 信息，系统会：
- 调用 Commons API 查询文件的扩展元数据
- 查找 `GPSLatitude` 和 `GPSLongitude` 字段
- 提取坐标信息

## 数据存储格式

### 图像二进制数据

图像以 BYTEA 格式存储在 `image_blob` 字段中，支持：
- JPEG
- PNG
- GIF
- WebP

### 地理坐标

地理坐标以 PostGIS Point 几何格式存储（WGS84，SRID 4326）：
- 格式：`POINT(longitude latitude)`
- 示例：`POINT(138.7309 35.3606)` (富士山)

### EXIF 元数据

EXIF 数据以 JSONB 格式存储，包含：
```json
{
  "exif": {
    "width": 1920,
    "height": 1080,
    "format": "JPEG",
    "datetime_original": "2023:03:15 10:30:00"
  },
  "gps": {
    "latitude": 35.3606,
    "longitude": 138.7309,
    "coordinates": [138.7309, 35.3606]
  }
}
```

## 查询图像数据

### 使用 Enrichment Service

```python
from app.services.enrichment import get_enrichment_service

enrichment = get_enrichment_service()

# 获取 Commons 资产元数据（不包括图像数据）
assets = enrichment.enrich_commons_assets(viewpoint_id=123, limit=10)

# 获取包括图像数据的资产（注意：图像数据可能很大）
assets_with_images = enrichment.enrich_commons_assets(
    viewpoint_id=123, 
    limit=10,
    include_image_data=True
)
```

### 直接数据库查询

```sql
-- 查询有图像的资产
SELECT 
    id,
    commons_file_id,
    image_width,
    image_height,
    ST_AsText(image_geometry) as location,
    file_size_bytes,
    downloaded_at
FROM viewpoint_commons_assets
WHERE viewpoint_id = 123
  AND image_blob IS NOT NULL;

-- 查询特定地理范围内的图像
SELECT 
    commons_file_id,
    ST_AsText(image_geometry) as location
FROM viewpoint_commons_assets
WHERE image_geometry IS NOT NULL
  AND ST_DWithin(
    image_geometry,
    ST_GeomFromText('POINT(138.73 35.36)', 4326),
    0.1  -- 约 10 公里
  );
```

## 性能考虑

1. **存储空间**：原始图像可能很大，注意数据库存储空间
2. **下载速率**：脚本包含速率限制，避免对 Commons 服务器造成压力
3. **批处理**：默认每批处理 10 个图像，批次间有短暂延迟
4. **索引**：已为 `image_geometry` 创建 GIST 索引，支持高效的空间查询

## 故障排除

### 下载失败

- 检查网络连接
- 确认 Commons 文件 ID 格式正确
- 查看错误日志了解具体原因

### EXIF 提取失败

- 某些图像可能没有 EXIF 数据（正常情况）
- 系统会尝试从 Commons API 获取地理标签作为备选

### 数据库错误

- 确认已运行数据库迁移
- 检查 PostgreSQL 版本（需要支持 PostGIS）
- 确认有足够的存储空间

## 未来扩展

- [ ] 支持图像压缩和缩略图生成
- [ ] 实现增量更新（只下载新图像）
- [ ] 添加图像质量评估和筛选
- [ ] 支持批量地理坐标验证
- [ ] 实现图像缓存机制

