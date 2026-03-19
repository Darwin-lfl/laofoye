# get_weather - 获取天气信息

## 描述
获取指定城市的实时天气信息。

## 使用说明
这个技能教你如何使用现有的工具来获取天气信息。你需要按照以下步骤操作：

### 步骤 1: 确定城市
- 从用户输入中提取城市名称
- 确保城市名称是有效的（例如："北京"、"上海"、"New York"）

### 步骤 2: 使用 fetch_url 工具获取天气数据
你可以使用以下方法之一：

#### 方法 A: 使用公开天气 API
1. 构造 API URL，例如：
   - 中国城市: `https://wttr.in/{城市}?format=j1`
   - 国际城市: `https://wttr.in/{城市}?format=j1&lang=en`

2. 使用 `fetch_url` 工具获取数据：
   ```
   fetch_url("https://wttr.in/北京?format=j1")
   ```

#### 方法 B: 使用 Python 处理
如果 API 返回 JSON 数据，你可以使用 `python_repl` 工具解析：

```python
import json
import requests

# 获取天气数据
response = requests.get("https://wttr.in/北京?format=j1")
data = response.json()

# 提取关键信息
current = data['current_condition'][0]
temp_c = current['temp_C']
weather_desc = current['weatherDesc'][0]['value']
humidity = current['humidity']
wind_speed = current['windspeedKmph']

print(f"温度: {temp_c}°C")
print(f"天气: {weather_desc}")
print(f"湿度: {humidity}%")
print(f"风速: {wind_speed} km/h")
```

### 步骤 3: 格式化输出
将天气信息整理成易读的格式：

```
## 北京天气

- **温度**: 15°C
- **天气**: 晴朗
- **湿度**: 45%
- **风速**: 10 km/h
- **体感温度**: 14°C
```

## 示例
用户: "查询北京的天气"

你应该:
1. 识别城市 "北京"
2. 使用 fetch_url 获取数据: `fetch_url("https://wttr.in/北京?format=j1")`
3. 解析返回的 JSON 数据
4. 输出格式化的天气信息

## 注意事项
1. 如果城市不存在或 API 失败，提供友好的错误信息
2. 考虑时区差异（如果需要）
3. 可以添加天气预报（未来几小时/几天）
4. 注意 API 的调用频率限制

## 支持的 API
1. wttr.in (免费，无需 API key)
2. OpenWeatherMap (需要 API key)
3. 中国天气网 (中文支持更好)

## 错误处理
- 网络错误: "无法连接到天气服务，请检查网络连接"
- 城市不存在: "找不到该城市的天气信息，请检查城市名称"
- API 限制: "天气服务暂时不可用，请稍后重试"