# ZN Next Phase

这份文件只描述下一阶段产品主线，不给 updater、rollback、signing、release trust、credential、identity 或 long-term memory 的高风险改动自动授权。

## 产品目标

ZN 的下一阶段不是继续堆基础设施，而是把已经存在的 Self、Body、Senses、Situation、Thought、Will、Work、Memory、Browser、Desktop、Computer Use、File、Terminal、Git、Recovery 和 Cognitive Resource 真正组合成普通用户能长期使用的完整任务闭环。

ZN 的产品定位是 **长期常驻在个人电脑里的通用型个人助理**。它不是办公 Agent、代码 Agent、浏览器 Agent、桌面自动化 Agent 或命令行 Agent 中的某一个，也不应围绕任何单一垂直领域收缩产品定义。

用户只需要表达正常的人类目标。ZN 自己判断完成目标需要什么资源组合：

```text
用户目标
-> 恢复当前 Work / Memory / Situation
-> 判断真正缺口
-> 组合需要的 cognition + tools + authority + verification
-> Browser / Desktop / File / Terminal / Git / API / specialist model 按需参与
-> 必要时拆成多个 delegated SubWork / worker
-> 状态变化后重新 Sense / Situation / Thought
-> 独立验证用户真正要的结果
-> 保持后续连续性
```

复杂编码可以主要依赖强 coding model；深度研究可以依赖 research model 和 Web；视觉任务可以依赖 vision model；电脑操作依赖真实 Browser/Desktop/File/Terminal 等工具。模型、worker 和工具都是资源，ZN 继续拥有用户目标、Durable Work、权限边界、现实证据、任务连续性和最终 completion judgment。

判断下一项工作，只问一件事：

**这个改动能不能直接提高 ZN 在真实用户电脑上自主完成真实任务的能力？**

如果不能，默认不是当前主线，除非它正在直接阻塞主线。

## ZN 负责调度和持续盯住整个任务

对于“帮我开发一个产品”这类长期、复杂、跨专业任务，ZN 不应该把整件事一次性扔给某一个模型或 Agent 后等待结果。ZN 应该持续拥有根目标，并在需要时完成：

```text
理解用户意图
-> 只对真正影响方向的问题进行澄清
-> 自主调查市场 / 技术 / 现有环境
-> 形成当前计划和验收目标
-> 拆分可执行 SubWork
-> 为每个 SubWork 选择合适资源
-> 并行或串行委派 worker / tool / specialist cognition
-> 跟踪依赖、进度、结果和 blocker
-> 收集 fresh evidence
-> 发现偏差后重规划 / 重分配 / 升级资源
-> 用户改变方向时安全 steering 现有 Work
-> 汇总各子任务结果
-> 验证整个用户目标，而不是只相信子任务“已完成”
-> 继续长期存在并支持后续修改和跨天继续
```

例如：

```text
用户：帮我开发一个个人记账产品

ZN / root Work
├─ 调研：竞品、用户痛点、技术约束
├─ 产品：功能范围、优先级、验收条件
├─ 设计：交互流程和必要界面
├─ 开发：实现代码和真实运行
├─ 测试：功能、回归、错误复现
└─ ZN：持续监督、整合、重规划、向用户汇报和最终验收
```

这些分支不要求每个都是独立大模型 Agent。某个 SubWork 可以由 coding agent 完成，也可以由普通模型、Web、Terminal、Browser、程序脚本或 ZN 已有确定性能力完成。**是否创建 worker，和是否调用模型，是两个不同决策。**

worker 是当前 Work 下的受限执行上下文，不是新的 Resident 主体。它不得自动继承整个用户身份、全部 Memory、全部凭据、全部工具权限或根 Work 的 completion authority。ZN 给它完成当前 SubWork 所需的最小上下文、工具、权限范围和验收标准即可。

worker 返回的“done”“success”或模型自评只是候选结果。ZN 必须检查真实产物、测试、页面状态、文件状态、运行结果或其他独立证据，再决定该 SubWork 是否真正完成以及整个 root Work 是否可以继续。

## worker 数量和模型数量必须解耦

**一个模型不等于一个 Agent，一个 Agent/worker 也不等于一个模型。**

如果用户只给 ZN 接入一个可用模型，ZN 仍然可以根据真实任务需要创建多个 worker：

```text
一个可用模型：GPT-X

root Work
├─ research worker  -> GPT-X + Web
├─ coding worker    -> GPT-X + File/Git/Terminal
├─ test worker      -> GPT-X + Terminal/Test tools
└─ review worker    -> GPT-X + bounded current evidence
```

这些 worker 可以串行，也可以在安全、资源和依赖允许时并行。它们共享同一个 cognitive provider，并不代表它们共享同一个上下文、SubWork、权限或执行状态。

如果用户接入多个模型，ZN 才进一步进行 **model routing**：根据当前子任务需要，在用户允许的模型集合里选择更合适的 cognition resource。

例如用户可以配置：

```text
primary reasoning / conversation: GPT
coding candidates:                 GPT / Claude / Codex-class resource
research candidates:               GPT / Gemini / other research-capable model
vision candidates:                 GPT / Gemini / other vision-capable model
cheap bounded classification:      small/local model when available
```

这里的 `primary reasoning` 表示用户偏好的主要对话/思考资源，不表示所有 delegated work 必须强制使用同一个模型。

ZN 可以在用户策略允许范围内自行决定：

```text
这个 SubWork 需要什么能力？
-> 哪些已连接模型具备该能力？
-> 是否需要长上下文 / coding / vision / research / tool use？
-> 当前数据敏感性允许哪些模型？
-> 用户有没有 pin / 禁用 / 优先级要求？
-> 成本、延迟、并发额度是否合理？
-> 失败后应该重试同模型、换模型还是升级强模型？
-> 最终需要哪些真实工具和验证路径？
```

模型路由的目标不是“永远选最便宜”或“永远选最强”，而是为当前 SubWork 选择 **足够合适且受用户策略约束的认知资源**。

用户显式指定必须优先于自动路由。例如：

- “平时你跟我思考都用 GPT。”
- “写代码优先用 Codex。”
- “这个项目不要把内容发给云端模型。”
- “这次全部只用我指定的那个模型。”

ZN 可以在这些约束内自主工作，但不能把“自动路由”理解成绕过用户的模型、隐私、成本或权限偏好。

模型失败、额度耗尽或暂时不可用时，如果存在用户允许的兼容资源，ZN 可以重路由；如果没有，应保存当前 Work 和证据并明确说明资源 blocker，而不是伪造继续。

## 调度必须服务真实任务，不变成新的基础设施主线

不要为了“支持多 Agent / 多模型”先建一个庞大的通用编排平台，再很久以后才接真实用户任务。

正确顺序仍然是：

```text
选择一个真实长任务
-> 看它哪里真的需要拆分、并行、专业模型或监督
-> 在现有 Work / Will / Thought / Cognitive Resource / Body 上补最小缺口
-> 让这个真实 E2E 从失败变成功
-> 再把可复用机制扩展到下一个任务
```

只有一个模型时，系统也必须能工作；只有一个 worker 时，也必须能工作。多模型、多 worker 是能力扩展，不得成为 ZN 能否存在和持有任务的前提。

## 当前优先顺序

1. 真实任务自主闭环。
2. 真实 User Browser Bridge。
3. 自主 Investigation / replanning。
4. 长期 Work / Memory / Resident 连续性。
5. 普通用户能看懂的任务状态、授权、失败和完成体验。

Installer、Release Candidate、签名、额外 CI、维护系统、文档整理、新抽象、新 provider、新状态机默认都是支撑线，不得自动抢主线。

## 真实任务开发方式

以后按这个顺序开发：

```text
选一个高价值真实用户任务
-> 从普通用户的一句自然语言开始
-> 找出完成它真正缺的认知、工具、权限、调度或验证能力
-> 只补这些缺口
-> 打通完整任务
-> 用真实 E2E 验证最终用户目标
-> 修复过程中暴露的架构问题
-> 再进入下一个更难真实任务
```

不要再按“checkbox、textbox、button、navigation、terminal、UIA 一个个做完”来判断产品进度。这些只是身体动作。

同样，不要因为 coding model 能生成代码、worker 声称 done、模型能给出答案、命令退出码为 0、HTTP 返回 200 或某个 provider 声称成功，就把任务视为完成。真实任务是否完成必须由当前世界中的结果证据来证明。

## E2E 在 ZN 里的定义

E2E（End-to-End）不是“多个 primitive 串起来跑通”，而是 **从用户的真实目标入口一直到用户真正需要的结果被独立验证**。

一个 ZN E2E 必须尽量从普通用户会说的话开始，而不是从内部结构化测试命令开始。例如：

```text
“这个程序启动时报错，帮我找原因、修掉，并确认原功能没有坏。”
```

可能真实经历：

```text
理解目标
-> 找到真实项目和当前仓库状态
-> File/Git/Terminal 建立事实
-> 调 coding model 分析和修改
-> 跑测试 / 启动程序
-> 失败则带 fresh evidence 继续调查和修改
-> 真实运行结果证明 bug 消失且关键功能仍正常
-> 才算 E2E 成功
```

又例如：

```text
“打开我已经登录的网站，查 Alice 最近的订单，再去官网核对规则，然后回来把备注更新好。”
```

E2E 关注的是整个用户目标有没有完成：是否使用了正确已登录 session、是否在页面变化后重新观察、是否能跨 tab/Browser plane 调查、是否回到正确工作上下文、是否真的保存了正确结果、最后是否有独立证据证明完成。

再例如长期调度任务：

```text
“帮我开发一个个人记账产品，你先调研一下，再给我做出能运行的第一版。”
```

E2E 不要求所有工作由同一个模型或同一个 worker 完成，而是要求 ZN 能澄清关键方向、调查、拆 Work、路由模型/工具、监督执行、处理失败、响应用户 steering，并最终拿出真实可运行且经过验证的结果。

因此：

```text
primitive success != E2E success
worker done != E2E success
model answer != E2E success
tool dispatch success != E2E success
CI green != product E2E success
```

## 通用个人助理的 E2E 覆盖面

真实任务验收集不能只偏办公，也不能只偏浏览器或代码。至少持续覆盖并逐步扩展这些普通用户任务族：

- 信息查找、研究、比较、总结和资料整理；
- 用户已登录网站和多步骤网页任务；
- 文档、表格、文件查找、理解、修改和组织；
- 桌面应用连续操作；
- 代码理解、bug 修复、功能修改、测试、Git 和真实 runtime 验证；
- 从模糊产品目标开始，经过调研、拆分、delegation、开发和测试形成真实产物的长任务；
- Terminal / CLI / 本地开发工具 / 合理系统管理任务；
- Browser + File、Browser + Desktop、File + Terminal、Browser + File + Desktop 等跨 surface 任务；
- 单模型、多 worker 的任务调度；
- 多模型、按能力自动 routing 的任务调度；
- 需要专业 cognition + 真实工具联合完成的任务；
- 页面、窗口、文件、程序状态变化后的重新调查；
- worker 失败、输出不合格或模型不可用后的重新分配 / 重路由；
- 任务中断、Resident 重启和跨天继续；
- 用户新指令对 active Work 和 delegated SubWork 的安全 steering；
- 权限拒绝、用户 presence、敏感字段和安全退出；
- 失败后重新观察、寻找替代路径；
- 最终结果的独立验证。

产品成熟度看的是这些任务族里 **普通用户能稳定交给 ZN 办成多少事情**，不是某个垂直 capability 有多少 API，也不是能同时 spawn 多少个 Agent。

## 当前最值得继续闭合的方向

- 页面、窗口、文件或目标变化后，能够重新 Sense / Situation / Thought，而不是脚本失配直接失败。
- 自然语言里的“刚才那个继续”“昨天那个继续”能恢复同一个真实 Work，而不是从零开始。
- active task 收到用户新指示以后，能安全改变当前计划，不重复已经发生的外部副作用。
- Work 能表达真实 SubWork / dependency / delegated execution / blocker / acceptance evidence，使 ZN 可以持续监督复杂任务而不是 fire-and-forget。
- 单模型情况下能有多个隔离 worker；多模型情况下能在用户策略范围内按任务能力路由模型。
- worker 失败、超时、输出不合格或现实变化时，ZN 能重新调查、重分配、换资源或升级认知，而不是根任务直接失败。
- Browser + File + Desktop 这类三 surface 联合任务能完成并独立验证结果。
- specialist cognition 能与 File/Git/Terminal/Browser/Desktop 等真实工具形成完整 resource stack，而不是只有模型建议没有现实执行能力。
- 已经可由 Resident、工具或成熟经验可靠完成的机械步骤不重复烧大模型；真正复杂的 coding/research/reasoning 又不为了省 token 被强行降级。
- 安装后跨版本仍保持身份、Memory、Work、配置和不确定副作用连续性。

## 已废弃方向

专用“自我维护 / 自我修复 / upstream BUG report”路线已经删除，不属于下一阶段，不属于 backlog 优先级，也不属于未来产品路线。

不要恢复专用 maintenance runtime、repair cognition、BUG report transport/intake、maintenance UI/RPC 或特殊仓库权限路径。

需要修改 ZN 自己的代码时，把 ZN 当成普通代码仓库，用通用 Work、File、Terminal、Git、Repo Test 和编码能力处理。

详情见 `docs/ZN-RETIRED-DIRECTIONS.md`。

## 完成一个阶段以后怎么汇报

不要只说：

- 新增多少文件；
- 测试多少个通过；
- CI 是否绿色；
- 合并了几个 PR；
- 同时启动了多少 worker；
- 接入了多少模型。

先说：

- ZN 以前不能完成什么真实任务；
- 现在能完成什么真实任务；
- 用户的成功路径是什么；
- 哪些 cognition + workers + tools + authority + verification 真正参与了闭环；
- ZN 是否能在 worker/model 失败后继续监督和重规划；
- 还有哪些地方会失败；
- 下一项最阻塞真实使用的问题是什么。