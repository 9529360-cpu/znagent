---
name: travel-shopping
description: "查询航班动态（OpenSky ADS-B 观测）与商品价格（Open Prices 众包小票价），以及本地比价。当用户问“某机场最近有什么航班”“这个条码的商品多少钱”“帮我比比价”时使用。只查不买：价格带币种与抓取时间，过期显式标注；没有任何购买/预订/付款动作。"
version: 0.1.0
allowed-tools:
  - rest.opensky_flights.get_departures
  - rest.opensky_flights.get_arrivals
  - rest.openprices_prices.query_prices
source: local
---

# 出行与购物查询（只查不买）

## 适用场景

- 用户问某机场最近的航班动态（起飞/到达）。
- 用户问某个商品（条码/EAN）的市场价格观测。
- 用户要对比几个报价（比价）。

**红线：本 Skill 只有查询能力。购买机票、订酒店、下单、付款一律不在本 Skill 范围内——用户要求购买时，明确说明需要走审批的单独流程，不要尝试任何购买动作（也没有购买工具可用）。**

## 数据源与诚实边界

- **航班**：OpenSky Network（ADS-B 观测），免密钥。返回的是观测到的起降，不是官方时刻表，更不是票价——**OpenSky 没有票价**。机场用 4 字母 ICAO 代码（首都机场 ZBAA、法兰克福 EDDF、希思罗 EGLL……）；代码拿不准时问用户，不要猜。
- **商品价格**：Open Prices（OpenFoodFacts 价格观测站），免密钥。每个价格都由小票/proof 照片背书；覆盖最强的是食品与日用品。查价用商品条码（EAN，如 3017620422003）。
- **酒店**：没有稳定的免密钥公开数据源（Amadeus Self-Service 已于 2026-07-17 关闭，Booking.com Demand API 仅签约伙伴，Google Hotels 无公开 API）。**不要编造酒店价格**；如用户问酒店比价，如实说明需要接入带 key 的供应商（部署时授权），目前只能给查询建议，不能给实时房价。
- **机票价格**：同理，实时票价需要带 key 的供应商（Duffel/Amadeus 等），目前只能查航班动态，不能报票价。不要把"有航班"说成"有这个价格的票"。

## 步骤

1. 航班动态：`direction` 填 `departure`（起飞）或 `arrival`（到达），`airport` 填 ICAO 四字码，`begin`/`end` 为 unix 时间戳（查最近 N 小时：`end` = 现在，`begin` = 现在 − N×3600，N ≤ 168）。返回空列表是正常答案（"这个窗口内没有观测到起降"），不是失败。
2. 商品查价：调用 `rest.openprices_prices.query_prices`，`product_code` 填条码，`size` 填要看的条数（默认 3；单条观测约 3.3KB，工具输出上限约 12KB，`size` 太大时会明确报错让你改小，不要硬调大），`order_by` 填 `-date`（最新观测优先）。
3. **必须看每条观测的 `currency_unknown` / `date_unknown` 标记**：币种解析不出的观测只展示、不参与比价；观测日期为 `unknown` 的要明确告诉用户"这条价格不知道是哪天的小票"。
4. 比价：用 `compare_offers` 的规则组织答案——同币种才能排名；混币种时不排名，提示先用 currency Skill 换算成同一币种再比；过期的报价（`expired`）列出但不参与"最便宜"结论。
5. 任一步调用失败时，把失败原因如实告诉用户（机场代码不对、条码无记录、网络失败）。**不要用记忆里的价格凑数，不要编一个"大概价"。**

## 答复结构

- 航班：机场 + 方向 + 时间窗口；每班：航班号/应答机码、起降机场（标注"ADS-B 估计"）、观测到的起降时间；来源：OpenSky Network；查询时间：本次查询的时间
- 商品：商品名（有的话）+ 条码；每条观测：价格 + 币种、商家、观测日期（unknown 则显式标注）、proof 编号；来源：Open Prices（众包小票价）；查询时间：本次查询的时间
- 比价：参与币种；排名（ cheapest 优先，过期排除在外）；每条报价的来源与抓取时间；`age_status` 非 fresh 的要标注（aging = 超过 1 天，stale = 超过 7 天或时间不明）
- 提示：价格/航班为查询时点的公开观测数据，不构成购买建议；购买动作需走审批

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “这个航班有飞，那票价大概就 X 吧。” | 有航班 ≠ 有这个价格的票。OpenSky 没有票价，不知道就说不知道。 |
| “酒店价格我搜一下网页大概报一个吧。” | 不要。没有稳定数据源的价格就是没有，编一个会害用户按假价格做计划。 |
| “这条观测没币种，但数字看着像欧元，直接按欧元比吧。” | 币种不明就不参与比价。猜币种等于猜价格。 |
| “一周前的价格，应该还准，直接当现价报吧。” | 可以用，但必须标注 aging/stale。过期数据不标注，比不答更糟。 |
| “用户说买，我顺手帮他点了吧。” | 没有购买工具，也绝不该有。购买走审批，这是红线。 |

## References

- 接口文档与答复结构定义：`runtime/python/zn_agent/core/travel_shopping_connector.py` 中的 OPENSKY_SPEC / OPENPRICES_SPEC 与 `lookup_flight_movements` / `lookup_product_prices` / `compare_offers` / `quote_age_status`。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R12 条目。
