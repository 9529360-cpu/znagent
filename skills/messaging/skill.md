---
name: messaging
description: "在 WhatsApp 上收发消息：列出最近会话、读某个会话的新消息、起草并经审批卡发送一条文本消息。当用户问“微信/WhatsApp 上有没有人找我”“帮我回一下 WhatsApp”或 'check my WhatsApp'、'send a WhatsApp message to ...' 时使用。对外发消息一律走审批卡，用户批准后才真正发出。未配置账号时明确说未配置，不编造消息。"
version: 0.1.0
allowed-tools:
  - msg.whatsapp.list_threads
  - msg.whatsapp.read_thread
  - msg.whatsapp.send_text
source: local
---

# 收发消息（WhatsApp）

## 适用场景

- 用户问 WhatsApp 上有没有新消息、谁找他。
- 用户要看某个会话的最近几条消息。
- 用户让你代发一条 WhatsApp 消息。

## 步骤

1. 看会话列表：调用 `msg.whatsapp.list_threads`。`limit` 按用户要的条数填，没说就填 20。返回里有 `peer`（对方号码）、最后一条消息预览、时间和未读数。
2. 读某个会话：调用 `msg.whatsapp.read_thread`，`thread_id` 从上一步的列表里取。返回 `direction` 为 in（对方发来）或 out（自己发出），只报真实返回的内容，不要脑补上下文。
3. 发消息：调用 `msg.whatsapp.send_text`。`to` 是国际区号格式的手机号（必填，如 +4915112345678）、`text` 是消息正文（必填，1–4000 字）。这是写操作：调用后会先弹一张审批卡，只有用户点了批准才会真正发出；被拒绝或一直没决定，消息就不会发出。**调用前先拟稿**：把收件号码和正文逐字复述给用户确认一遍（“我准备给 +49… 发：‘……’，可以吗？”），确认后再调用发送动作走审批。
4. 任一步返回“未配置（not configured）”时，明确告诉用户 WhatsApp 账号还没接上：需要他在部署时授权一次（在 Meta 开发者后台建应用、拿到手机号 ID，把访问令牌存进 ZN 自己的凭证库，一次即可）。不要假装能收发。
5. 如果读操作返回“Cloud API 没有历史读取接口”，如实转告：WhatsApp 官方接口只支持发送，历史消息要等部署时把 webhook 订阅接上 ZN 的事件管道；不要编造会话内容。

## 答复结构

- 会话列表：对方号码 — 最后一条预览，时间，未读数
- 读会话：方向（对方/自己）、发送人、时间、正文
- 发消息：拟稿内容 → 审批卡状态（待批准/已批准已发出/被拒绝）；发出后给出 provider message id
- 来源：WhatsApp Cloud API 实时返回；生成时间：本次操作的时间

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “会话列表是空的，我按常理补一条老板的消息吧。” | 空就是空。编造的消息会被当成真实消息引用，后果比不答严重得多。 |
| “用户说发吧，我直接调发送，不用等审批卡。” | 发消息必须走审批卡。未经批准的发送在运行时层面就被拦下，调用也不会成功。 |
| “正文我大概知道意思，稍微润色一下再发。” | 发出去的正文必须和拟稿时给用户确认的一字不差。润色了就等于没确认过。 |
| “读接口不可用，我按用户描述猜一下会话内容。” | 读不到就说读不到，并指到 webhook 部署步骤。猜测的聊天记录是编造。 |
| “账号没配置，我先假装发了，反正用户看不出来。” | 不得假装发送成功：未配置就明确说未配置，并指到部署时授权一次的步骤。 |

## References

- 通道选型、适配层、审批接入与答复结构定义：`runtime/python/zn_agent/core/messaging_connector.py`（`WhatsAppCloudChannel`、三个动作、`send_text`、`register_messaging_runtime`）。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R10 条目。
