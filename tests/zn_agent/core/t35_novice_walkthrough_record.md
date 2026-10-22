# T3-5 新手路径走查记录

- 走查时间：2026-10-22 09:33 UTC
- 基线：T3-4 #641（`17e0aa176bb22f4958b072193b3898585e31cb59`）
- 方式：真 resident 沙箱 ZN_HOME + 真 PTY + 真 `zn` 入口（非 fake socket）
- 场景：空 home → 上手提示 → 交办 → 审批 → 完成
- 约定：输出中 `<thread-id>` / `<request-id>` / `<event-id>` / `<ts>` 为归一化占位；
  ANSI 已剥离；每步独立子进程。

## 步骤

### S1 上手帮助

- 叙事：全新机器，新手先看帮助。
- 命令：`zn help`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 场景化帮助出现
  - [✓] T3-3 三行上手提示出现
  - [✓] 帮助给出真实示例

<details>
<summary>完整输出</summary>

```text
ZN 能帮你干的事（按场景）

--- 交办 (5) ---
  work submit
    交办一件事给 ZN，常驻服务去执行
    例：zn work submit --task "把 downloads 里昨天的发票整理成一张表"
  work list
    看看 ZN 手上正在干的活
    例：zn work list
  work get
    看某件事的进展和结果
    例：zn work get --thread-id <id>
  work cancel
    停掉一件正在干的活
    例：zn work cancel --thread-id <id> --event-id <id>
  chat
    直接跟 ZN 对话交办（交互模式）
    例：zn chat

--- 审批 (3) ---
  approval list
    看等你拍板的申请卡
    例：zn approval list
  approval show
    先看清一张卡的内容再拍板
    例：zn approval show <id>
  approval decide
    批准或拒绝一张卡
    例：zn approval decide --request-id <id> --allow

--- 记忆 (5) ---
  memory list
    看看 ZN 都记着哪些事
    例：zn memory list
  memory remember
    让 ZN 记住一件事
    例：zn memory remember --key "公司 wifi 密码" --value "xxxx"
  memory forget
    让 ZN 忘掉一件事（默认要手动确认）
    例：zn memory forget --key "公司 wifi 密码" --yes
  memory export
    把记忆备份成文件
    例：zn memory export --out ~/memory-backup.json
  memory import
    从备份文件恢复记忆
    例：zn memory import --in ~/memory-backup.json

--- 团队与自驱 (4) ---
  team list
    看有哪些项目团队在干活
    例：zn team list
  team timeline
    看某件事的团队进展时间线
    例：zn team timeline --thread-id <id>
  goal list
    看 ZN 的自驱目标清单
    例：zn goal list
  goal status
    看 ZN 自驱的当前状态
    例：zn goal status

--- 日常 (5) ---
  suggestions list
    看 ZN 给你的建议
    例：zn suggestions list
  autonomy list
    看 ZN 在各领域的自主权设置
    例：zn autonomy list
  connector status
    看连接器挂载得正不正常
    例：zn connector status
  model check
    检查模型通道通不通
    例：zn model check
  status
    一屏看 ZN 的整体状态（服务/模型/审批/连接器）
    例：zn status

细看某条命令：zn <命令> --help，例如 zn work submit --help
① 直接运行 `zn` 开口说话交办（已支持交互对话）
② `zn work submit --task "…"` 从命令行交办
③ `zn help` 查看全部能干的事
```

</details>

### S2 常驻未启动先查活

- 叙事：新手还没起常驻服务就查活——看报错是否指路而非死胡同。
- 命令：`zn work list`
- 退出码：1
- 检查：
  - [✓] exit 非 0（诚实失败）
  - [✓] 报错给了下一步——连接失败必须告诉新手怎么办
  - [✓] 下一步提到常驻服务
  - [✓] 无 traceback 泄漏

<details>
<summary>完整输出</summary>

```text
zn: error: ZN 常驻服务没在运行（does not appear to be running；或 ZN home 不对）：找不到 endpoint 文件 (endpoint not found)：/tmp/t35-walkthrough-9c2afuwl/home/kernel/resident-endpoint.json
下一步：检查 ZN_HOME 是否正确，或启动常驻服务（zn-resident）
① 直接运行 `zn` 开口说话交办（已支持交互对话）
② `zn work submit --task "…"` 从命令行交办
③ `zn help` 查看全部能干的事
```

</details>

### S3 启动常驻服务

- 叙事：新手按 S2 的指引启动常驻服务（走查 harness 代劳，起真 resident）。
- 命令：`(harness) boot resident in sandbox ZN_HOME`
- 退出码：0
- 检查：

<details>
<summary>完整输出</summary>

```text
endpoint published at <home>/kernel/resident-endpoint.json
```

</details>

### S4 正门 REPL

- 叙事：听从上手提示①，直接运行 `zn` 进对话，再退出。
- 命令：`zn`
- 退出码：0
- 检查：
  - [✓] /exit 后干净退出
  - [✓] /help 列出会话命令

<details>
<summary>完整输出</summary>

```text
ZN 会话模式：直接说话就能交办（回车发送），同一会话里可以接着追问。
/help 看会话命令，/new 开新会话，/exit 退出。
zn> /help
/exit
会话命令（单独一行输入）：
  /new       开新会话（下一句话在新 thread 里交办）
  /history   回看当前会话的历史消息
  /help      显示这份帮助
  /exit      退出会话（Ctrl-D 也可以）
其他任何一行文字都会作为任务发给 ZN；干活时按 Ctrl-C 只取消当前这一轮，会话不退出。
zn>
```

</details>

### S5 整体状态

- 叙事：`zn status` 一屏看服务/模型/审批。
- 命令：`zn status`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 常驻活着

<details>
<summary>完整输出</summary>

```text
--- ZN status ---
resident   ✓ ok (pulse_count=3)
summary    ZN Agent v0.2.0 · model_invocations=
model      ✗ no model routes configured  → zn model check
connectors ✓ 0 of 0 mounted
approvals  none pending
autonomy   0 explicit domain(s)  → zn autonomy list
```

</details>

### S6 空活列表

- 叙事：空 home 查活，看 T3-4 下一步提示。
- 命令：`zn work list`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] T3-4 空态下一步提示

<details>
<summary>完整输出</summary>

```text
no work threads
  下一步：交办第一件事，运行 `zn work submit --task "…"`
```

</details>

### S7 交办

- 叙事：新手交办第一件事。
- 命令：`zn work submit --task 帮我整理今天的三件事`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 输出给出 thread id——新手要凭它跟进
  - [✗（记入缺陷清单）] 失败时给出下一步（当前沙箱无模型，run 以 success=False 结束）

<details>
<summary>完整输出</summary>

```text
submitted to thread work-<thread-id>  (帮我整理今天的三件事)
run event=evt-<event-id>  success=False  cancelled=False  path=model  model_invocations=0
```

</details>

### S8 查活看到任务

- 叙事：交办后查活，任务应在列表里。
- 命令：`zn work list`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 任务在列表里

<details>
<summary>完整输出</summary>

```text
work-<thread-id>  帮我整理今天的三件事  updated=<ts>  messages=3  active=no
```

</details>

### S9 看结果（完成）

- 叙事：用 work get 看交办事项的结果。
- 命令：`zn work get --thread-id work-c9edc920d4b4427b`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 能看到任务原文

<details>
<summary>完整输出</summary>

```text
work-<thread-id>  帮我整理今天的三件事
created=<ts>  updated=<ts>
[<ts>] user:
  帮我整理今天的三件事
[<ts>] zn:
  No System 2 model is configured. ZN Resident is still running with local capabilities and structured memory.
[<ts>] activity:
  Resident activity
```

</details>

### S10 审批到达

- 叙事：常驻产生一张审批卡，新手查卡。
- 命令：`zn approval list`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 卡在列表里
  - [✗（记入缺陷清单）] pending 卡给出下一步

<details>
<summary>完整输出</summary>

```text
--- pending (1) ---
! approval-<request-id>  [pending]  send
  target=walkthrough-target  scope=walkthrough  expires=<ts>  waited=0s
```

</details>

### S11 看卡详情

- 叙事：先看清再拍板。
- 命令：`zn approval show approval-56a35414ead0421f`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 详情给出拍板指引

<details>
<summary>完整输出</summary>

```text
! 审批卡 approval-<request-id>  [pending]  send
  目标：walkthrough-target
  范围：walkthrough
  来源：resident
  创建时间：<ts>（已等待 0s）
  失效时间：<ts>
  下一步：用 'zn approval decide --request-id approval-<request-id> --allow' 批准，或 '--deny' 拒绝
```

</details>

### S12 拍板批准

- 叙事：新手批准这张卡。
- 命令：`zn approval decide --request-id approval-56a35414ead0421f --allow`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 批准生效

<details>
<summary>完整输出</summary>

```text
approval-<request-id>  status=approved_once  decision=allow_once
```

</details>

### S13 审批清空

- 叙事：拍板后复查：不应再有 pending。
- 命令：`zn approval list`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 无 pending
  - [✗（记入缺陷清单）] 空态给出下一步

<details>
<summary>完整输出</summary>

```text
--- pending (0) ---
(none)
```

</details>

### S14 收尾探针：取消已结束的活

- 叙事：活已结束，新手试着 cancel 收尾（用交办时拿到的 event id）——看报错是否指路。
- 命令：`zn work cancel --thread-id work-c9edc920d4b4427b --event-id evt-ecc9bcbf4323`
- 退出码：1
- 检查：
  - [✓] exit 非 0（已结束，诚实失败）
  - [✗（记入缺陷清单）] 报错给出下一步而非裸异常

<details>
<summary>完整输出</summary>

```text
zn: error: 服务端返回错误（work_cancel）：RuntimeError: work cancellation requires an active Work run
```

</details>

### S15 闭环

- 叙事：最后查活：任务留痕、无进行中，路径闭环。
- 命令：`zn work list`
- 退出码：0
- 检查：
  - [✓] exit 0
  - [✓] 任务留痕
  - [✓] 无进行中

<details>
<summary>完整输出</summary>

```text
work-<thread-id>  帮我整理今天的三件事  updated=<ts>  messages=3  active=no
```

</details>

## 缺陷清单

### D1 [S7] work submit 报 success=False 时无下一步指引

- 实际看到：输出只有 `run event=… success=False …` 一行，新手不知道该干什么。
- 新手卡点：应提示用 `zn work get --thread-id <id>` 看详情/原因，否则像死胡同。

### D2 [S10] approval list 有 pending 卡时无下一步提示

- 实际看到：卡只展示 target/scope/expires，新手第一眼不知道敲什么命令拍板。
- 新手卡点：`approval show` 有 `下一步：用 'zn approval decide …'`，list 漏了；新手需自行发现 show/decide，算一次猜命令。

### D3 [S13] approval list 空态无下一步提示

- 实际看到：只打印 `(none)`；T3-4 给 work/memory/team/suggestions 四个列表加了下一步尾巴，approval list 漏了。
- 新手卡点：新手看到 (none) 不知道审批从哪来、接下来能干什么。

### D4 [S14] work cancel 对已结束 run 透出裸 RuntimeError 且无下一步

- 实际看到：输出 `zn: error: 服务端返回错误（work_cancel）：RuntimeError: work cancellation requires an active Work run`。
- 新手卡点：应人话化并指引：活已结束，用 `zn work get --thread-id <id>` 看结果。

## 已知局限

- 沙箱常驻无模型配置，run 在 1s 内以 success=False 结束；「执行中取消」(mid-run cancel) 路径本次未覆盖。
- 审批卡由 harness 经 RPC 模拟常驻行动产生（与真审批同源）；
  真实场景中审批来自常驻自主行动或消息渠道。
