---
name: currency
description: "查询汇率与货币换算，数据来自 Frankfurter 免密钥接口（ECB 参考汇率）。当用户问“1 美元等于多少人民币”“今天欧元对日元汇率”或 'convert 100 USD to EUR' 时使用。答复注明数据来源与汇率日期；过期数据显式标注；只给汇率信息，不给投资建议。"
version: 0.1.0
allowed-tools:
  - rest.frankfurter_fx.get_latest_rates
  - rest.frankfurter_fx.get_historical_rates
source: local
---

# 查汇率 / 货币换算（Frankfurter）

## 适用场景

- 用户问两个货币之间的汇率，或要把一笔金额换算成另一种货币。
- 用户问某一天的历史汇率（过去日期，YYYY-MM-DD）。

## 步骤

1. 把用户说的货币统一成 3 字母代码（美元→USD、欧元→EUR、人民币→CNY、日元→JPY、英镑→GBP、港币→HKD……）。代码拿不准时直接问用户，不要猜。
2. 用户只问汇率（没给金额）：调用 `rest.frankfurter_fx.get_latest_rates`，`base` 填基准货币，`symbols` 填目标货币（逗号分隔，可多个）。返回的 `rates` 就是"1 基准货币 = X 目标货币"。
3. 用户给了金额要换算：同样查汇率，然后金额 × 汇率得出换算结果。换算公式写清楚，让用户能复算。
4. 用户给了过去日期：调用 `rest.frankfurter_fx.get_historical_rates`，路径参数 `date` 填 YYYY-MM-DD，`base`/`symbols` 同上。**必须看返回的 `date` 字段**：ECB 只在交易日发布汇率，非交易日会返回前一个交易日的汇率；返回日期与请求日期不一致时，明确告诉用户"这是 X 日（前一个交易日）的汇率"，不许把旧数据当成当天数据报。
5. 周末/节假日查"最新汇率"时同样：返回的 `date` 不是今天，就明确标注"这是 X 日的最新可得汇率（ECB 交易日）"。
6. 按下面的答复结构组织答案。数值全部取自接口返回值。
7. 任一步调用失败时，把失败原因如实告诉用户（如未知货币代码、网络失败）。不要用记忆里的汇率凑数。

## 答复结构

- 货币对：1 USD = X CNY（或用户问的方向）
- 金额换算：100 USD ≈ X CNY（写清汇率与公式）
- 汇率日期：ECB 参考汇率，日期 X（非当日/非请求日时显式标注原因）
- 来源：Frankfurter（ECB 参考汇率）；查询时间：本次查询的时间
- 提示：汇率仅供信息参考，不构成投资建议

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “美元兑人民币汇率我大概记得，6 点多，直接答吧。” | 汇率每天都在变。用记忆里的数字答汇率，等于把猜测当数据。 |
| “接口返回的日期是上周五，但用户问的是今天，凑合用吧。” | 可以用，但必须明确标注这是上周五（最近交易日）的汇率。过期数据不标注，比不答更糟。 |
| “用户问现在买美元划不划算，我给个建议吧。” | 不给投资建议。这是红线。只给汇率信息和数据日期。 |
| “这个货币代码肯定对，不用校验。” | 代码必须由工具调用验证。拼错的代码会让接口 404，报错了就如实报，不要编一个。 |

## References

- 接口文档与答复结构定义：`runtime/python/zn_agent/core/fx_rates_connector.py` 中 FRANKFURTER_SPEC 与 `lookup_fx_rates` / `convert_currency`。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R7 条目。
