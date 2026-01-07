# 数据完整性说明

## 当前状态

根据系统要求，所有景点需要包含：

1. ✅ **离线百科历史信息**（Wikipedia / Wikidata）
   - 状态：**100% 完成**
   - 所有 10,002 个景点都有 Wikipedia 和 Wikidata 数据

2. ⚠️ **LLM 提取的结构化视觉 tags**
   - 状态：**3.1% 完成**（308/10,002）
   - 需要为剩余 9,694 个景点生成视觉 tags

## 数据生成流程

### 1. 历史信息（已完成）

所有景点都已包含：
- **Wikipedia 数据**：
  - 摘要文本（extract_text）
  - 章节结构（sections）：History, Architecture/Features, Tourism
  - 引用信息（citations）
  
- **Wikidata 数据**：
  - Wikidata QID
  - 结构化属性（claims）：
    - 实例类型（P31）
    - 创建时间（P571）
    - 海拔高度（P2044，适用于山峰）
    - 图片引用（P18）
  - 语言链接数量（sitelinks_count）

### 2. 视觉 Tags（需要补充）

使用 GPT-4o 从 Wikipedia 文本中提取结构化视觉 tags：

**提取内容**：
- 视觉特征（snow_peak, cherry_blossom, autumn_foliage 等）
- 场景类型（sunrise, sunset, night_view 等）
- 季节信息（spring, summer, autumn, winter）
- 证据句子（来自 Wikipedia 文本的引用）

**Tag 来源**：`wiki_weak_supervision`

## 生成脚本

### 检查数据完整性

```bash
python scripts/ensure_complete_data.py
```

### 生成视觉 Tags（使用 GPT-4o）

```bash
# 为所有景点生成 tags（会消耗 API credits）
python scripts/generate_visual_tags_from_wiki.py

# 限制处理数量（例如只处理前 5000 个）
python scripts/generate_visual_tags_from_wiki.py --limit 5000

#  dry run（不实际调用 API）
python scripts/generate_visual_tags_from_wiki.py --dry-run
```

## 注意事项

### API 成本

- 每个景点需要 1-2 次 GPT-4o API 调用
- 处理 9,694 个景点大约需要：
  - 时间：约 2-4 小时（取决于 API 速率限制）
  - 成本：约 $50-100（取决于文本长度和 API 定价）

### 批量处理建议

1. **分批处理**：使用 `--limit` 参数分批处理
   ```bash
   # 第一批：前 1000 个
   python scripts/generate_visual_tags_from_wiki.py --limit 1000
   
   # 第二批：接下来 1000 个
   # （脚本会自动跳过已处理的）
   ```

2. **监控进度**：脚本会显示进度和预计剩余时间

3. **错误处理**：脚本会自动跳过错误，继续处理下一个

## 数据验证

生成后验证数据：

```bash
python scripts/ensure_complete_data.py
```

应该看到：
- ✅ 所有景点都有 Wikipedia/Wikidata
- ✅ 所有景点都有 LLM-extracted visual tags

## 数据示例

### Wikipedia 历史信息示例

```json
{
  "viewpoint_id": 1,
  "wikipedia_title": "Mount_Fuji",
  "extract_text": "Mount Fuji is a volcanic peak...",
  "sections": [
    {
      "title": "History",
      "content": "The history of Mount Fuji dates back centuries...",
      "level": 2
    }
  ],
  "citations": [...]
}
```

### LLM 提取的视觉 Tags 示例

```json
{
  "viewpoint_id": 1,
  "season": "winter",
  "tags": ["mountain", "snow_peak", "sunrise"],
  "confidence": 0.85,
  "evidence": {
    "source": "wiki_weak_supervision",
    "sentences": [
      "The mountain is covered with snow in winter...",
      "Sunrise views from the summit are spectacular..."
    ]
  },
  "tag_source": "wiki_weak_supervision"
}
```

## 下一步

1. 运行数据完整性检查
2. 根据需要生成视觉 tags
3. 验证数据完整性
4. 系统即可使用完整数据

