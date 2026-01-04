# 图像处理说明 - GPT-4o

## 概述

TourRAG 系统使用 **GPT-4o** 模型来处理图像输入。GPT-4o 是 OpenAI 的多模态模型，支持同时处理文本和图像输入。

## 图像处理流程

### 1. 图像上传

用户可以通过以下方式提供图像：

**方式 A：文件上传（推荐）**
```bash
curl -X POST "http://localhost:8000/api/v1/query?top_k=5" \
  -F "user_text=这是什么景点？" \
  -F "user_images=@/path/to/image.jpg"
```

**方式 B：Base64 数据 URL**
```python
import base64

with open("image.jpg", "rb") as f:
    image_base64 = base64.b64encode(f.read()).decode('utf-8')
    data_url = f"data:image/jpeg;base64,{image_base64}"

response = requests.post(
    "http://localhost:8000/api/v1/extract-query-intent",
    json={
        "user_text": "这是什么地方？",
        "user_images": [{
            "image_id": data_url,
            "mime_type": "image/jpeg"
        }]
    }
)
```

### 2. 图像处理

系统会自动：
1. 读取上传的图像文件
2. 编码为 Base64 格式
3. 创建数据 URL（`data:image/jpeg;base64,...`）
4. 传递给 GPT-4o 进行视觉分析

### 3. GPT-4o 视觉分析

GPT-4o 会分析图像并提取：
- **视觉特征**：识别图像中的视觉元素（如雪峰、樱花、寺庙等）
- **季节信息**：推断图像拍摄的季节（spring/summer/autumn/winter）
- **场景类型**：识别场景类型（sunrise, sunset, night_view 等）
- **地点线索**：识别可能的地点名称或地理特征

### 4. 结构化输出

GPT-4o 的输出会被转换为结构化查询意图：
```json
{
  "query_intent": {
    "name_candidates": ["Mount Fuji"],
    "query_tags": ["mountain", "snow_peak", "winter"],
    "season_hint": "winter",
    "scene_hints": ["sunrise"],
    "geo_hints": {
      "place_name": "Japan",
      "country": "Japan"
    }
  }
}
```

## 支持的图像格式

- JPEG (.jpg, .jpeg)
- PNG (.png)
- GIF (.gif)
- WebP (.webp)

## 使用示例

### Python 示例

```python
import requests

# 方式 1: 文件上传
with open("mountain.jpg", "rb") as f:
    files = {"user_images": ("mountain.jpg", f, "image/jpeg")}
    data = {"user_text": "这是什么山？", "top_k": 5}
    response = requests.post(
        "http://localhost:8000/api/v1/query",
        files=files,
        data=data
    )

# 方式 2: Base64 数据 URL
import base64

with open("temple.jpg", "rb") as f:
    image_base64 = base64.b64encode(f.read()).decode('utf-8')
    data_url = f"data:image/jpeg;base64,{image_base64}"

response = requests.post(
    "http://localhost:8000/api/v1/extract-query-intent",
    json={
        "user_images": [{
            "image_id": data_url,
            "mime_type": "image/jpeg"
        }]
    }
)
```

### cURL 示例

```bash
# 仅图像查询
curl -X POST "http://localhost:8000/api/v1/query?top_k=5" \
  -F "user_images=@image.jpg"

# 文本 + 图像
curl -X POST "http://localhost:8000/api/v1/query?user_text=这是什么地方&top_k=5" \
  -F "user_images=@image.jpg"
```

## 测试脚本

使用提供的测试脚本：

```bash
python test_image_api.py /path/to/image.jpg "这是什么景点？"
```

## 注意事项

1. **模型要求**：系统强制使用 GPT-4o 模型处理图像，确保视觉能力
2. **图像大小**：建议图像大小不超过 20MB
3. **API 限制**：OpenAI API 对图像大小和分辨率有限制，请参考 OpenAI 文档
4. **成本**：GPT-4o 的图像处理按 token 计费，图像会占用较多 tokens

## 技术细节

### 图像编码

图像通过以下方式编码：
1. 读取二进制数据
2. Base64 编码
3. 创建数据 URL：`data:{mime_type};base64,{base64_string}`

### GPT-4o API 调用

```python
messages = [
    {
        "role": "system",
        "content": system_prompt
    },
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "用户文本"},
            {
                "type": "image_url",
                "image_url": {
                    "url": "data:image/jpeg;base64,..."
                }
            }
        ]
    }
]

response = client.chat.completions.create(
    model="gpt-4o",  # 强制使用 GPT-4o
    messages=messages,
    response_format={"type": "json_object"}
)
```

## 故障排除

### 问题：图像无法处理

1. 检查图像格式是否支持
2. 检查图像大小是否过大
3. 查看服务器日志中的错误信息

### 问题：GPT-4o 返回错误

1. 确认 API key 有效
2. 检查 API 配额和限制
3. 验证图像数据 URL 格式正确

### 问题：识别结果不准确

1. 确保图像清晰
2. 提供更多上下文文本
3. 检查图像是否包含足够的视觉特征

