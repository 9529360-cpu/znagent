---
name: rss-reader
description: "读取用户订阅的 RSS/Atom 信息源：查看订阅列表、拉取某个源的最新条目、按时间或关键词汇总成简报。当用户问“我订阅的博客有什么更新”“帮我看看今天 RSS 里的 AI 新闻”或 'summarize my feeds from the last day' 时使用。条目全部来自实时抓取的 feed 原文，答复注明来源订阅与抓取时间。"
version: 0.1.0
allowed-tools:
  - rss.feeds.list_subscriptions
  - rss.feeds.fetch_feed
  - rss.feeds.digest
  - rss.feeds.add_subscription
  - rss.feeds.remove_subscription
source: local
---

# 读 RSS/Atom 订阅

## 适用场景

- 用户问自己订阅的信息源有什么新内容，或要一份按时间/关键词筛过的简报。
- 用户要看某个订阅源（或某个 feed 地址）的最新条目。
- 用户要新增或删除一个订阅源。

## 步骤

1. 不确定用户有哪些订阅时，先调用 `rss.feeds.list_subscriptions` 看订阅列表，不要凭记忆猜源名。
2. 看单个源：调用 `rss.feeds.fetch_feed`，`name` 填订阅名（或 `url` 直接填 feed 地址），`limit` 按用户要的条数填，没说就填 20。返回里 `skipped_entries` 大于 0 时，在答复里说明有几条坏条目被跳过。
3. 做汇总简报：调用 `rss.feeds.digest`。用户说了时间范围就换算成 `since_hours`；提了主题就把关键词填 `keyword`；只看部分源就把源名列表填 `names`。返回里 `feed_errors` 非空时，把抓取失败的源逐个列明，不要假装它们没更新。
4. 新增订阅：调用 `rss.feeds.add_subscription`（`name` 用小写字母/数字/短横线，`url` 是完整的 http(s) feed 地址）。删除订阅：调用 `rss.feeds.remove_subscription`。这两个是写操作，只有主机批准后才存在；调用失败或工具不存在时如实告诉用户订阅管理未启用，不要反复重试。
5. 按下面的答复结构组织答案。标题、时间、链接全部取自工具返回值。

## 答复结构

- 范围：看了哪些源、时间范围/关键词（没筛就写全部）
- 条目（按时间从新到旧）：标题 — 来源订阅名，发布时间，链接，一句摘要
- 抓取失败的源：源名 + 失败原因（有才写）
- 来源：RSS/Atom 订阅抓取；生成时间：本次汇总的时间

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “这个源抓取失败了，我大概知道它最近发了啥，补几条吧。” | 抓不到就写抓不到，并注明原因。凭印象补的条目会被当成真实更新引用。 |
| “这条没写发布时间，应该是今天的，放进今日简报里。” | 没日期的条目不能证明新鲜。按时间筛选时它被排除，答复里要说明有未注明日期的条目未计入。 |
| “关键词一条都没命中，我把全部条目列出来充数。” | 没命中就说没命中。用户要的是筛选结果，不是全量倾倒。 |
| “坏条目跳过了几条，不用提。” | `skipped_entries` 和 `feed_errors` 是抓取质量的一部分，必须如实报告。 |

## References

- 解析、订阅存储与答复结构定义：`runtime/python/zn_agent/core/rss_feed_connector.py`（`parse_feed_document`、五个动作与 `build_feed_digest`）。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R3 条目。
