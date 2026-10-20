---
name: calendar
description: "查用户日历上接下来几天的安排（ICS 本地文件或 CalDAV 日历）。当用户问“明天有什么安排”“下周会议多吗”或 'what is on my calendar tomorrow' 时使用。读操作直接执行；新建日程必须先弹审批卡经用户同意，写入成功后用重新读取验证。"
version: 0.1.0
allowed-tools:
  - calendar.ics.list_events
  - calendar.ics.create_event
  - calendar.caldav.list_events
  - calendar.caldav.create_event
source: local
---

# 查日历 / 建日程（ICS / CalDAV）

## 适用场景

- 用户问接下来几天有什么安排、某天忙不忙、某个会议什么时候开。
- 用户说“帮我约个会”“下周三下午记一下”，即新建日程。

## 查安排（读，只读不审批）

1. 默认用 `calendar.ics.list_events` 查本地 ICS 文件；若用户配了 CalDAV（日历源显示为 CalDAV 地址），用 `calendar.caldav.list_events`。
2. `days` 按用户问的范围填，没说就填 7（最多 366）。
3. 按返回的 `start` 时间顺序念给用户听：日期、时间、标题、地点。每条注明来源（ICS 文件路径或 CalDAV 地址）。
4. 结果为空时明确说“这几天没有安排”，不要编造。
5. 读失败时把失败原因如实告诉用户（文件不存在、CalDAV 未配置、401 账号密码不对、网络不通）。CalDAV 未配置时明确说还没接服务器，不要假装查过。

## 建日程（写，必须走审批）

1. 先把要建的日程复述给用户确认关键字段：标题、开始时间、结束时间（可选）、地点（可选）、备注（可选）。`start` 用 ISO 8601（如 `2026-10-25T10:00:00+08:00`）；整天事项只给日期 `2026-10-25`。
2. 调用 `calendar.ics.create_event`（写本地 ICS 文件）或 `calendar.caldav.create_event`（写 CalDAV 日历）。调用后系统会弹出审批卡：**用户不点同意，日程绝不会写入**。不要绕过审批，也不要替用户点。
3. 审批通过且返回成功后，用 `list_events` 重新查一次确认日程在列表里，再告诉用户“已记下”。
4. 审批被拒绝时明确说“没建，日程保持原样”，不要再试。

## 答复结构

- 日期 + 星期：时间段、标题（地点）
- 来源：ICS 文件路径 / CalDAV 地址；查询时间：本次查询的时间

## Common Rationalizations

| 借口 | 反驳 |
| --- | --- |
| “用户说建日程，意思就是授权我直接写入，不需要再审批。” | 写入必须走审批卡：审批通过前不得写入，口头交办不等于对具体内容的审批。 |
| “CalDAV 连不上时，把日程放在本地文件里效果是一样的。” | 连不上就报告连不上，不要把日程写到用户没指定的地方。 |
| “ICS 里有个时间看着不对，按常识推一个更合理的时间报给用户更省事。” | 原样报出并标注存疑，不要按常识改时间。 |

## References

- 工具定义与审批/验证接线：`runtime/python/zn_agent/core/calendar_connector.py`（`attach_calendar_tools`、`register_calendar_runtime`）。
- 接入方式与验收记录：`docs/ZN-IMPLEMENTATION-STATUS.md` 的 R5 条目。
- 为日后 Google 日历 OAuth 版打底：读走列表接口、写走审批卡的形状不变，届时只替换传输层。
