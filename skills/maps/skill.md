---
name: maps
description: "地址与坐标互查、附近地点查询、两地直线距离估算，数据来自 OpenStreetMap 的 Nominatim 地理编码与 Overpass 查询，免密钥。当用户问“X 的经纬度是多少”“柏林附近有什么咖啡馆”“从 A 到 B 有多远”或 'what is near Berlin'、'how far is Munich from Berlin' 时使用。答复注明数据来源；距离是直线估算，不是道路距离。"
version: 0.1.0
allowed-tools:
  - rest.osm_nominatim.geocode_address
  - rest.osm_nominatim.reverse_geocode
  - rest.osm_overpass.query_interpreter
source: local
---

# 地图与地点（OpenStreetMap）

## 适用场景

- 用户给地址或地名，问它的经纬度，或给经纬度问这是什么地方。
- 用户问某个位置附近有什么（咖啡馆、药店、停车场、餐馆等）。
- 用户问两个地方之间有多远。

## 步骤

### 地址 → 坐标

1. 调用 `rest.osm_nominatim.geocode_address`：`q` 填用户说的地址或地名，`format` 填 `jsonv2`，`limit` 填 1（用户想比较多个候选时填更大），`addressdetails` 填 1。
2. 返回为空数组时明确告知没有找到这个地址，请用户补上城市/国家或换个写法。不要编造坐标。
3. 取结果的 `display_name`、`lat`、`lon` 答复；注意接口返回的 `lat`/`lon` 是字符串。

### 坐标 → 地址

1. 调用 `rest.osm_nominatim.reverse_geocode`：`lat`、`lon` 填用户给的坐标，`format` 填 `jsonv2`。
2. 返回带 `error` 字段时明确告知该坐标附近没有查到地址，不要拿最近的城市硬凑。

### 附近地点

1. 先按“地址 → 坐标”拿到中心点坐标（用户直接给坐标则跳过）。
2. 把用户的类别词换成 OSM 标签：咖啡馆 `amenity=cafe`、餐馆 `amenity=restaurant`、药店 `amenity=pharmacy`、停车场 `amenity=parking`、加油站 `amenity=fuel`、酒店 `tourism=hotel`、超市 `shop=supermarket`。类别没有对应标签时如实告知，不要硬套一个不相干的标签。
3. 调用 `rest.osm_overpass.query_interpreter`，`data` 填 Overpass QL（半径单位米，用户没说范围就用 1000；条数上限填 20）：

   ```
   [out:json][timeout:25];(node["amenity"="cafe"] (around:1000,52.520008,13.404954);way["amenity"="cafe"] (around:1000,52.520008,13.404954);relation["amenity"="cafe"] (around:1000,52.520008,13.404954););out center 20;
   ```

   把标签与坐标换成实际值。`out center` 不能省，否则线/面要素没有坐标。
4. 结果里取每条的 `tags.name`（没有名字就写未命名）、坐标（节点用 `lat`/`lon`，线/面用 `center`），按与中心点的远近排序答复。`elements` 为空就是附近没有，如实说，不要从记忆里补地点。

### 两地距离

1. 分别按“地址 → 坐标”拿到两地坐标。
2. 用 Haversine 公式按两组坐标算直线距离，答复时明确写“直线距离约 X km（估算，非道路距离）”。不要把直线距离说成开车距离或时间。

## 答复结构

- 地址查询：规范地址（display_name）、纬度、经度
- 附近地点：名称、与中心点的大致距离、地址（如有）
- 距离：起点、终点、直线距离约 X km（估算）
- 来源：OpenStreetMap（Nominatim / Overpass）；查询时间：本次查询的时间

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “这个地方很有名，我知道它的大概坐标。” | 坐标必须来自地理编码接口的返回值。用记忆里的坐标，等于把猜测当数据。 |
| “附近没查到，我按印象列几个知名的。” | 查不到就说查不到。编出来的地点用户真去了找不到，比不答更糟。 |
| “直线距离乘个系数就是道路距离了。” | 没有路由接口的数据就不报道路距离。只报直线估算并标注清楚。 |
| “接口限流报错了，我连着重试几次总能过。” | OSM 是公共服务，接口要求限速。报错就如实报告，过一会儿再查，不要轰击。 |

## References

- 接口文档、Overpass QL 构造与距离估算：`runtime/python/zn_agent/core/osm_maps_connector.py`（NOMINATIM_SPEC、OVERPASS_SPEC、`geocode_address`、`reverse_geocode`、`find_nearby_places`、`estimate_distance`）；OSM 使用政策（User-Agent + 限速）由该模块的 `OsmPolicyHttpClient` 强制执行。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R4 条目。
