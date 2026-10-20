---
name: mail
description: "读写用户的 IMAP 邮箱：列收件箱、读整封信、按发件人/主题/关键词/时间搜索；发信走审批卡，用户批准后才真正发出。当用户问“今天有没有新邮件”“帮我找老板上周发的邮件”或 'check my inbox'、'send an email to ...' 时使用。未配置邮箱账号时明确说未配置，不编造邮件内容。"
version: 0.1.0
allowed-tools:
  - mail.imap.list_mailbox
  - mail.imap.read_message
  - mail.imap.search
  - mail.smtp.send_message
source: local
---

# 收发邮件（IMAP / SMTP）

## 适用场景

- 用户问收件箱里有没有新邮件、某封信的内容。
- 用户要按发件人、主题、关键词或时间找邮件。
- 用户让你代发一封邮件。

## 步骤

1. 看收件箱：调用 `mail.imap.list_mailbox`。`mailbox` 不填就是 INBOX；`limit` 按用户要的条数填，没说就填 20；只要未读就把 `unseen_only` 填 true；限定时间就把 `since` 填 `YYYY-MM-DD`。
2. 读整封信：调用 `mail.imap.read_message`，`uid` 从上一步的列表里取。返回里 `attachments` 只有文件名/大小，没有正文内容——不要声称自己读过附件内容。
3. 找邮件：调用 `mail.imap.search`。`from` 填发件人、`subject` 填主题关键词、`text` 填全文关键词、`since` 填起始日期、`unseen_only` 限定未读。返回为空时就说没找到，不要编造“可能”的邮件。
4. 发邮件：调用 `mail.smtp.send_message`。`to` 是收件人数组（必填）、`subject`（必填）、`body`（必填）；`cc`/`bcc` 可选，`bcc` 不会出现在信头里。这是写操作：调用后会先弹一张审批卡，只有用户点了批准才会真正发出；被拒绝或一直没决定，邮件就不会发出。调用前把收件人、主题、正文复述给用户确认一遍。
5. 任一步返回“未配置（not configured）”时，明确告诉用户邮箱账号还没接上：需要他在部署时授权一次 IMAP/SMTP 账号（凭证存在 ZN 自己的凭证库里，不会写进任何文件）。不要假装能收发。

## 答复结构

- 列表/搜索：发件人 — 主题，时间，UID；未读标出来
- 读信：发件人、收件人、时间、主题、正文（附件只列文件名和大小）
- 发信：审批卡状态（待批准/已批准已发出/被拒绝）；发出后给出 message-id
- 来源：IMAP/SMTP 实时读取；生成时间：本次操作的时间

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “收件箱是空的，我按常理补一封老板的邮件吧。” | 空就是空。编造的邮件会被当成真实邮件引用，后果比不答严重得多。 |
| “附件列表里有文件名，我大概讲一下附件内容。” | 附件正文根本没取回来。只能报文件名和大小，内容一律说没读。 |
| “用户说发吧，我直接调发送，不用等审批卡。” | 发信必须走审批卡。未经批准的发送在运行时层面就被拦下，调用也不会成功。 |
| “搜索没命中，我把全部邮件列出来充数。” | 没命中就说没命中。用户要的是筛选结果，不是全量倾倒。 |
| “账号没配置，我先假装发了，反正用户看不出来。” | 不得假装发送成功：未配置就明确说未配置，并指到部署时授权一次的步骤。 |

## References

- 协议层、审批接入与答复结构定义：`runtime/python/zn_agent/core/mail_connector.py`（`parse_message_bytes`、四个动作、`send_message`、`register_mail_runtime`）。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R6 条目。
