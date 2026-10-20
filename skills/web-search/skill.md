---
name: web-search
description: "用免密钥的 SearXNG 元搜索在网上查资料，返回带标题、链接和摘要的结果。当用户说“帮我搜一下……”“网上查查……”或 'search the web for …'、'look up … online' 时使用。答复必须给出每条结果的来源链接，并注明搜索实例与查询时间；搜索失败时如实报告原因，绝不编造链接或结果。"
version: 0.1.0
allowed-tools:
  - rest.searxng_search_lumy_live.web_search
source: local
---

# 网页搜索（SearXNG）

## 适用场景

- 用户要查网上的资料、新闻、文档或某个事实的出处，手头没有现成链接。
- 用户的问题需要最新信息，凭记忆回答不可靠。

默认工具对应默认实例（search.lumy.live）。部署若配置了其他 SearXNG 实例，工具名形如 `rest.searxng_<实例主机 slug>.web_search`，用法相同。

## 步骤

1. 调用 `rest.searxng_search_lumy_live.web_search`：`q` 填用户的查询（可适当改写成更易命中的关键词），`format` 填 `json`；用户说了语言就填 `language`（如 `zh`、`en`）；问近期事件可填 `time_range`（`day`/`week`/`month`/`year`）。
2. 检查返回的 `results`。为空时明确告知这次没有搜到结果，建议换个关键词重试。不要编造标题、链接或摘要。
3. 按下面的答复结构组织答案。每条结果的标题、链接、摘要全部取自接口返回值。若返回值带 `truncated: true`，说明本次结果较多、只取到了前面完整的几条，答复里要注明。
4. 调用失败时，把失败原因如实告诉用户（哪个实例、什么原因，如 HTTP 429 限流、实例不可达）。搜索失败就是失败，不要用记忆里的内容冒充搜索结果。

## 答复结构

- 查询：本次用的查询词
- 结果（逐条）：标题 — 链接
  - 摘要原文（可截断，不可改写成接口没说的话）
- 来源：SearXNG（注明实际应答的实例）；查询时间：本次查询的时间

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “这个我知道，直接凭记忆答更快。” | 用户要的是网上查到的出处。凭记忆答没有链接可核对，等于把猜测当搜索结果。 |
| “搜到的摘要太短，我帮它扩写一下。” | 摘要只能引用或截断。扩写出来的句子会被当成原文出处引用。 |
| “实例报错了，我编几条看起来合理的结果先顶上。” | 报错就报告报错和原因。假链接点开是 404，信任一次就没了。 |
| “第一个实例限流了，肯定是查询词的问题。” | 429 是实例侧限流/未开放 JSON，不是查询词的错；如实说明，或换已配置的其他实例。 |

## References

- 接口文档、默认实例的实测核实记录与答复结构定义：`runtime/python/zn_agent/core/web_search_connector.py`（SEARCH_SPEC、search_web 与模块头的核实结论）。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R2 条目。
