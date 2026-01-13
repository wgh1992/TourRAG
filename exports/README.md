# 卫星图像下载工具

## 概述

这个工具用于根据 CSV 文件中的景点经纬度信息，批量下载卫星图像。使用 ArcGIS World Imagery API 获取高分辨率卫星图像。

## 功能特性

- ✅ 从 CSV 文件读取景点数据（viewpoint_id, longitude, latitude）
- ✅ 支持按 ID 范围批量下载（例如：`62323-62325`）
- ✅ 自动根据经纬度创建边界框（bbox）
- ✅ 使用 ArcGIS World Imagery API 下载卫星图像
- ✅ 自动保存图像到指定目录
- ✅ 失败重试机制（最多3次）
- ✅ 自动生成失败列表（`failed_list.csv`）

## 安装要求

### Python 依赖

```bash
pip install requests pillow
```

### 必需库

- `requests` - HTTP 请求库
- `PIL` (Pillow) - 图像处理库

## 使用方法

### 基本用法

```bash
# 下载指定 ID 范围的卫星图像
python exports/download_satellite_images.py --id-range 62323-62325

# 下载单个 ID 的图像
python exports/download_satellite_images.py --id-range 62323

# 下载所有景点的图像（不指定 ID 范围）
python exports/download_satellite_images.py
```

### 完整示例

```bash
# 下载 ID 62323-62325，延迟 0.1 秒
python exports/download_satellite_images.py --id-range 62323-62325 --delay 0.1

# 自定义图像尺寸和缓冲区大小
python exports/download_satellite_images.py \
    --id-range 62323-62325 \
    --size 512 512 \
    --buffer 2.0 \
    --delay 0.2

# 使用自定义 CSV 文件和输出目录
python exports/download_satellite_images.py \
    --csv viewpoints_info.csv \
    --output images \
    --id-range 62323-62325
```

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--csv` | string | `viewpoints_info.csv` | CSV 文件路径（相对于 exports/ 目录） |
| `--output` | string | `images` | 输出目录（相对于 exports/ 目录） |
| `--id-range` | string | `None` | ID 范围，格式：`start-end` 或单个 `id`（默认：所有） |
| `--buffer` | float | `1.0` | 缓冲区大小（公里），围绕点的范围 |
| `--size` | int int | `1024 1024` | 图像尺寸（宽度 高度），单位：像素 |
| `--delay` | float | `0.5` | 请求之间的延迟（秒） |

### 参数详细说明

#### `--id-range`
- 格式：`start-end` 或单个数字
- 示例：
  - `62323-62325` - 下载 ID 从 62323 到 62325 的图像
  - `62323` - 只下载 ID 为 62323 的图像
  - 不指定 - 下载 CSV 文件中所有景点的图像

#### `--buffer`
- 单位：公里
- 说明：围绕景点坐标点的缓冲区大小
- 示例：
  - `1.0` - 1 公里缓冲区（默认）
  - `2.0` - 2 公里缓冲区（更大的范围）
  - `0.5` - 0.5 公里缓冲区（更小的范围）

#### `--size`
- 格式：两个整数，用空格分隔
- 单位：像素
- 示例：
  - `1024 1024` - 1024×1024 像素（默认）
  - `512 512` - 512×512 像素
  - `2048 2048` - 2048×2048 像素

#### `--delay`
- 单位：秒
- 说明：每次请求之间的延迟时间，避免请求过快
- 建议：
  - 小批量（<10个）：`0.1-0.2` 秒
  - 中批量（10-100个）：`0.5` 秒（默认）
  - 大批量（>100个）：`1.0-2.0` 秒

## CSV 文件格式

CSV 文件必须包含以下列：

| 列名 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `viewpoint_id` | integer | ✅ | 景点唯一标识符 |
| `longitude` | float | ✅ | 经度（WGS84） |
| `latitude` | float | ✅ | 纬度（WGS84） |
| `name_primary` | string | ❌ | 景点名称（可选，用于日志显示） |

### CSV 示例

```csv
viewpoint_id,name_primary,longitude,latitude
62323,Rupnagar,76.526088,30.9688367
62324,K2,76.5133308,35.8816822
62325,Amarkantak,81.7588417,22.670465
```

## 输出说明

### 输出目录结构

```
exports/
├── images/                    # 图像输出目录
│   ├── 62323.png             # 景点图像（以 viewpoint_id 命名）
│   ├── 62324.png
│   ├── 62325.png
│   └── failed_list.csv       # 失败列表（如果有失败的下载）
└── viewpoints_info.csv       # 输入 CSV 文件
```

### 图像文件

- **文件名格式**：`{viewpoint_id}.png`
- **图像格式**：PNG
- **图像尺寸**：根据 `--size` 参数设置（默认 1024×1024）
- **质量**：高质量 PNG（quality=95）

### 失败列表

如果某些图像下载失败，会自动生成 `failed_list.csv` 文件，包含以下信息：

```csv
viewpoint_id,name,longitude,latitude
62326,Example,76.123456,30.123456
```

## 工作原理

1. **读取 CSV**：从 CSV 文件中读取景点数据
2. **过滤 ID**：根据 `--id-range` 参数过滤景点
3. **创建边界框**：根据经纬度和缓冲区大小创建 bbox
4. **下载图像**：
   - 调用 ArcGIS World Imagery API
   - 支持多个服务端点（自动切换）
   - 失败自动重试（最多3次）
5. **保存图像**：将图像保存为 PNG 格式
6. **生成报告**：显示下载统计和失败列表

## 技术细节

### API 端点

脚本使用以下 ArcGIS 服务端点（按顺序尝试）：

1. `https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export`
2. `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export`

### 边界框计算

根据经纬度坐标和缓冲区大小计算边界框：

```python
# 1度纬度 ≈ 111 公里
# 1度经度 ≈ 111.321 × cos(纬度) 公里

buffer_lat = buffer_km / 111.0
buffer_lon = buffer_km / (111.321 * cos(latitude))

bbox = (
    longitude - buffer_lon,  # min_lon
    latitude - buffer_lat,   # min_lat
    longitude + buffer_lon,   # max_lon
    latitude + buffer_lat    # max_lat
)
```

### 图像验证

下载的图像会经过以下验证：

- 文件大小 > 1000 字节
- 图像尺寸 ≥ 256×256 像素

## 错误处理

### 常见错误

1. **CSV 文件不存在**
   ```
   ❌ 错误: CSV文件不存在: viewpoints_info.csv
   ```
   - 解决：检查 CSV 文件路径是否正确

2. **缺少必需字段**
   ```
   ⚠️  跳过 viewpoint_id=62323: 缺少必需字段
   ```
   - 解决：确保 CSV 包含 `viewpoint_id`, `longitude`, `latitude` 列

3. **下载失败**
   - 脚本会自动重试（最多3次）
   - 失败的记录会保存到 `failed_list.csv`
   - 可能原因：
     - 网络连接问题
     - API 服务暂时不可用
     - 坐标超出服务范围

## 性能建议

### 批量下载优化

1. **调整延迟**：根据网络状况调整 `--delay` 参数
2. **分批处理**：对于大量数据，建议分批下载
3. **监控失败**：定期检查 `failed_list.csv`，重新下载失败的记录

### 示例：分批下载

```bash
# 第一批：ID 62323-62423
python exports/download_satellite_images.py --id-range 62323-62423 --delay 0.5

# 第二批：ID 62424-62524
python exports/download_satellite_images.py --id-range 62424-62524 --delay 0.5

# 第三批：ID 62525-62625
python exports/download_satellite_images.py --id-range 62525-62625 --delay 0.5
```

## 示例输出

```
📋 ID范围: 62323 - 62325
📖 正在读取CSV文件: /path/to/viewpoints_info.csv
✓ 找到 3 个景点
📁 输出目录: /path/to/exports/images
🖼️  图像尺寸: 1024×1024px
📏 缓冲区: 1.0km

[1/3] 处理 viewpoint_id=62323: Rupnagar
  位置: (76.526088, 30.968837)
  BBox: (76.515612, 30.959828, 76.536564, 30.977846)
  正在下载卫星图像...
  ✅ 成功保存: 62323.png (901,337 bytes, 1024×1024px)
  等待 0.1 秒...

[2/3] 处理 viewpoint_id=62324: K2
  位置: (76.513331, 35.881682)
  BBox: (76.502244, 35.872673, 76.524418, 35.890691)
  正在下载卫星图像...
  ✅ 成功保存: 62324.png (533,804 bytes, 1024×1024px)

================================================================================
下载完成！
  总计: 3 个景点
  成功: 3
  失败: 0
  输出目录: /path/to/exports/images
================================================================================
```

## 注意事项

1. **API 限制**：ArcGIS API 可能有请求频率限制，建议设置适当的延迟
2. **网络连接**：确保网络连接稳定，下载大量图像可能需要较长时间
3. **存储空间**：确保有足够的磁盘空间存储图像文件
4. **坐标系统**：使用 WGS84 坐标系（EPSG:4326）
5. **图像质量**：图像质量取决于 API 服务的数据质量

## 许可证

本工具使用的 ArcGIS World Imagery 服务由 Esri 提供。请遵守 Esri 的服务条款和使用政策。

## 更新日志

### v1.0.0 (2026-01-13)
- 初始版本
- 支持从 CSV 文件批量下载卫星图像
- 支持 ID 范围过滤
- 自动失败重试机制
- 失败列表生成

## 问题反馈

如遇到问题，请检查：
1. CSV 文件格式是否正确
2. 网络连接是否正常
3. Python 依赖是否已安装
4. 查看 `failed_list.csv` 了解失败的记录

## 相关文件

- `download_satellite_images.py` - 主脚本
- `viewpoints_info.csv` - 输入数据文件
- `images/` - 输出目录
