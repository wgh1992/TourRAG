# 快速开始指南 - 下载10000个完整Viewpoint

## 一键设置10000个完整Viewpoint

运行以下命令来自动设置10000个viewpoint，包含所有数据（图像、地理信息、历史、标签）：

```bash
python scripts/setup_10000_viewpoints.py
```

这个脚本会自动：
1. ✅ 确保有10000个viewpoint（如果没有会自动插入）
2. ✅ 为所有viewpoint添加Wikipedia/Wikidata数据
3. ✅ 下载图像和地理信息
4. ✅ 生成视觉标签
5. ✅ 更新国家信息

## 自定义选项

```bash
# 设置不同的目标数量
python scripts/setup_10000_viewpoints.py --target 5000

# 跳过图像下载（更快，但缺少图像）
python scripts/setup_10000_viewpoints.py --skip-images

# 跳过标签生成（更快，但缺少标签）
python scripts/setup_10000_viewpoints.py --skip-tags

# 跳过国家信息更新
python scripts/setup_10000_viewpoints.py --skip-country
```

## 简化后的脚本结构

### 核心脚本（保留）

1. **`setup_10000_viewpoints.py`** ⭐ - 一键设置10000个完整viewpoint
2. **`manage_viewpoints.py`** - 统一管理脚本（所有操作）
3. **`check_viewpoint_summary.py`** - 检查数据库摘要和图像（合并了check_downloaded_images.py）
4. **`cleanup_incomplete_viewpoints.py`** - 清理不完整viewpoint（合并了cleanup_and_generate_tags.py）
5. **`remove_duplicate_viewpoints.py`** - 移除重复viewpoint

### 数据插入脚本

6. **`insert_osm_data.py`** - 插入OSM测试数据
7. **`insert_wiki_data.py`** - 插入Wikipedia/Wikidata数据
8. **`insert_sample_data.py`** - 插入示例数据

### 下载脚本

9. **`download_all_viewpoint_images.py`** - 下载所有viewpoint图像和元数据
10. **`download_commons_images.py`** - 下载Commons图像

### 生成脚本

11. **`generate_visual_tags_from_wiki.py`** - 从Wikipedia生成视觉标签
12. **`generate_visual_tags_from_images.py`** - 从图像+历史信息生成标签与摘要
13. **`generate_viewpoint_distribution_map.py`** - 生成分布图

### 工具脚本

13. **`init_db.py`** - 初始化数据库
14. **`download_all_viewpoint_images.py --country-only`** - 获取国家信息

### 已删除的脚本（功能已合并）

- ❌ `check_downloaded_images.py` → 合并到 `check_viewpoint_summary.py`
- ❌ `cleanup_and_generate_tags.py` → 合并到 `cleanup_incomplete_viewpoints.py`
- ❌ `ensure_complete_data.py` → 合并到 `check_viewpoint_summary.py`

## 使用示例

### 场景1：快速设置10000个viewpoint

```bash
# 一键完成所有步骤
python scripts/setup_10000_viewpoints.py
```

### 场景2：分步执行

```bash
# 步骤1: 插入OSM数据
python scripts/manage_viewpoints.py insert osm

# 步骤2: 插入Wikipedia数据
python scripts/manage_viewpoints.py insert wiki

# 步骤3: 下载图像
python scripts/manage_viewpoints.py download images --limit 10000

# 步骤4: 生成标签
python scripts/manage_viewpoints.py generate-tags --limit 10000

# 步骤4.1: 从图像+历史生成标签与摘要（可选）
python scripts/manage_viewpoints.py generate-image-tags --image-dir exports/images/all_image --limit 10000

# 步骤5: 检查状态
python scripts/manage_viewpoints.py status
```

### 场景3：检查数据

```bash
# 查看完整摘要
python scripts/check_viewpoint_summary.py

# 查看下载的图像详情
python scripts/check_viewpoint_summary.py --images

# 查看更多图像
python scripts/check_viewpoint_summary.py --images --images-limit 50
```

### 场景4：清理和维护

```bash
# 生成标签并清理不完整的viewpoint
python scripts/cleanup_incomplete_viewpoints.py --generate-tags --execute

# 只清理不完整的viewpoint
python scripts/cleanup_incomplete_viewpoints.py --execute

# 移除重复的viewpoint
python scripts/remove_duplicate_viewpoints.py --execute
```

## 文件数量对比

**之前**: 23个脚本文件
**现在**: 14个核心脚本文件（减少了9个）

## 注意事项

1. **时间**: 下载10000个viewpoint的图像可能需要几个小时
2. **API成本**: 生成标签使用OpenAI API，会产生费用
3. **网络**: 需要网络连接来下载图像和查询API
4. **数据库**: 确保数据库已初始化

## 推荐工作流

```bash
# 1. 初始化数据库（如果还没做）
python scripts/manage_viewpoints.py init

# 2. 一键设置10000个viewpoint（推荐）
python scripts/setup_10000_viewpoints.py

# 3. 检查结果
python scripts/check_viewpoint_summary.py

# 4. 如果需要，清理重复项
python scripts/remove_duplicate_viewpoints.py --execute
```
