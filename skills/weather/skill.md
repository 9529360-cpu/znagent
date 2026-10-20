---
name: weather
description: "查询指定地点的实时天气与逐日预报，数据来自 Open-Meteo 免密钥接口。当用户问“明天柏林天气怎么样”“北京今天会下雨吗”或 'what is the weather in Berlin tomorrow' 时使用。先按地点名定位坐标，再查预报，答复注明数据来源与查询时间。"
version: 0.1.0
allowed-tools:
  - rest.open_meteo_geocoding.search_location
  - rest.open_meteo_forecast.get_forecast
source: local
---

# 查天气（Open-Meteo）

## 适用场景

- 用户问某个地点现在或未来几天的天气、温度或降雨概率。
- 用户只给地点名，没有给经纬度。

## 步骤

1. 调用 `rest.open_meteo_geocoding.search_location`：`name` 填用户说的地点名，`count` 填 1，`format` 填 `json`。
2. 检查返回的 `results`。为空时明确告知没有找到这个地点，请用户换个写法或补上国家/地区。不要编造坐标。
3. 取 `results` 第一条的 `latitude` 与 `longitude`。
4. 调用 `rest.open_meteo_forecast.get_forecast`：带上一步的经纬度；`current` 填 `temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m`；`daily` 填 `weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max`；`forecast_days` 按用户问的天数填，没说就填 3；`timezone` 填 `auto`。
5. 按下面的答复结构组织答案。数值全部取自接口返回值。
6. 任一步调用失败时，把失败原因如实告诉用户（如 HTTP 状态、地点未找到）。不要用经验或记忆补数值。

## 答复结构

- 地点：名称（国家/地区，时区）
- 当前：温度 °C、天气状况、湿度 %、风速 km/h
- 逐日：日期、天气状况、最低~最高 °C、降雨概率 %
- 来源：Open-Meteo；查询时间：本次查询的时间

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “这个城市很有名，我知道它的大概坐标。” | 坐标必须来自地理编码接口的返回值。用记忆里的坐标查天气，等于把猜测当数据。 |
| “接口没返回降雨概率，我按季节估一个。” | 缺失的字段就写未提供。估出来的数值会被当成真实预报引用。 |
| “接口报错了，我用昨天的天气答吧。” | 报错就报告报错。过期数据冒充实时预报，比不答更糟。 |

## References

- 接口文档与答复结构定义：`runtime/python/zn_agent/core/open_meteo_connector.py` 中两个 OpenAPI 文档（GEOCODING_SPEC、FORECAST_SPEC）与 `lookup_weather`。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R1 条目。
