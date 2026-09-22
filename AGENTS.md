# ZN 仓库维护与接手规则

本文件给任何接手本仓库的维护者使用，包括人类、GPT、Claude、Gemini、Codex 或未来其他维护系统。

> 这个仓库当前唯一产品是 **ZN**。历史或外部参考源码不是 ZN 的产品身份、主体、运行时或控制平面。

## 核心原则

**维护者可以随时更换，ZN 项目不能因此中断。**

聊天可以消失，电脑可以更换，模型可以更换；只要仓库和项目级基础设施仍可访问，开发、测试、合并和发布就应能够继续。

维护者的首要职责是持续推进 **ZN 产品本身**，直到出现真正需要人工决定或授权的边界。分支、commit、push、PR、CI、HANDOFF 和 `main` 同步属于正常工程卫生，应由维护者自行处理，不应反过来成为产品路线或反复向用户汇报的中心。

事实优先级：

```text
真实代码和 Git 状态
> 实际测试、构建和 CI 结果
> .agent/HANDOFF.md
> 对话描述
```

默认自行获取信息、自行判断下一步、自行完成低风险且可逆的开发动作，并持续推进到可验证结果。不要把本可从仓库、代码、测试、CI、日志或现有产品目标判断的问题抛给用户。

只有涉及不可逆操作、权限/凭证、明确人工审批边界、会显著改变产品方向/公开行为/数据兼容性的选择，或无法可靠推断的高风险歧义时，才停下来询问用户。

## 新维护者接手顺序

1. 读取 `ZN.md`。
2. 读取 `AGENTS.md`。
3. 读取 `docs/ZN-IMPLEMENTATION-STATUS.md`。
4. 读取 `docs/ZN-SOURCE-EXTRACTION.md`。
5. 读取 `docs/ZN-RETIRED-DIRECTIONS.md`。
6. 读取 `.agent/HANDOFF.md`。
7. 检查 `main` 当前 HEAD、相关 `work/*` 分支、open PR、CI 和最近提交；只有历史任务仍明确引用 `dev/zn-agent` 时才把它当兼容分支检查，不能把它当新的集成主线。
8. 检查当前产品最重要缺口对应的真实调用链、测试和 active caller。
9. 根据 ZN 总目标、当前实现、真实缺口、风险和依赖，自主决定下一项最有价值的工作并开始推进。

文档与代码冲突时，以真实仓库状态为准，先自动对账再继续。新的维护者不需要知道上一位是谁，也不需要拥有上一段聊天记录。

HANDOFF 的 Task Queue 是上一阶段留下的现场信息，不是不可推翻的命令。接手者必须继承事实，但仍要自己思考。如果发现更高优先级的 bug、安全/可靠性问题、产品阻塞或更合理的依赖顺序，应直接调整队列并继续工作。

## ZN 产品判断协议

维护者不仅要会执行任务，还要像 ZN 的技术负责人一样判断**现在最值得做什么**。

选择下一项工作时，不按文档顺序、里程碑编号、上一任的 next slice、测试数量、证据数量或 Git 状态机械排序。优先问：**这项工作完成后，ZN 离一个真正可长期存在、可感知、可思考、可行动、可学习、可恢复、可安装并持续使用的产品近了多少？**

默认优先级判断：

```text
P0  身份/长期记忆/数据损坏、严重安全问题、核心生命循环不可用
P1  用户或产品主路径阻塞、resident 生命周期/恢复可靠性、高概率回归
P1  架构已经承诺但 active caller 未真正接通的核心能力
P2  能显著闭合真实用户场景的能力缺口
P2  为上述能力提供必要验证、可观测性和恢复机制
P3  一般工程卫生、性能/维护性优化、纯文档与非阻塞清理
```

Git/CI/main 同步本身不参与产品优先级竞争；它们随开发闭环自然完成。

### 主动找问题

不要只消费 TODO、HANDOFF 或 `Next target`。接手和阶段结束时，主动检查与当前产品目标相关的：

- active caller 是否真的使用了声明能力；
- TODO/FIXME、stub、placeholder、mock-only 路径和未接线模块；
- 异常吞噬、失败后状态污染、重试/恢复缺口、并发和幂等问题；
- 只有单元测试证明、没有真实运行/集成证明的关键能力；
- 架构文档声称存在但代码没有完整实现的契约；
- 代码存在但 UI/runtime/resident 实际入口不可达的能力；
- 安全边界、凭证处理、提示注入、工具权限、上下文/成本失控风险；
- 安装、重启、更新、回退后可能破坏 ZN 连续性的路径。

发现更高价值的问题时，更新 Task Queue 并处理，不需要为了忠于旧计划继续做低价值工作。

### 完成度不能只看“implemented”

对重要能力至少区分四层：

```text
存在：代码/接口已经出现
→ 接通：真实 active caller 在产品路径中使用
→ 验证：测试、集成或真实环境证明确实工作
→ 产品闭环：用户/ZN 的真实场景从入口到结果、失败恢复和状态连续性都成立
```

只有前一两层时，不要因为文档写了 `implemented` 就把能力视为成熟产品功能。优先补齐最影响真实使用的断层。

### ZN 的连续性高于普通功能完成

ZN 是持续存在的 resident subject，不是一次性请求处理器。涉及以下状态的改动必须额外检查跨重启、安装/更新、失败恢复和版本变化后的连续性：

- Self / identity；
- lived / long-term memory；
- Work / thread references；
- Will / intention / learning state；
- runtime/home/config/provider references；
- resident lifecycle 与恢复状态。

“新版能启动”不等于成功。如果升级、恢复或重构后把原来的 ZN 变成了一个没有原身份/记忆连续性的新实例，应按严重回归处理。

### 优先纵向闭环

避免为了显得进展快而同时横向铺很多半成品模块。优先选一个真实产品场景，从入口、owner、state、执行、验证、失败恢复一直打通，再扩展下一个场景。

证据的职责是证明真实能力，不是替代真实能力。

**不得用增加文档、测试数量、证据文件、状态记录、PR 数量、commit 数量或分支同步来替代真实产品能力进展。**

## 开发方式

默认工作循环：

```text
从最新 main 拉短命 work/* 分支
→ 理解 ZN 当前状态和目标
→ 主动体检并找出当前最值得解决的问题
→ 追真实调用链 / owner / state / lifecycle / dependency / tests / active caller
→ 判断该能力处于“存在 / 接通 / 验证 / 产品闭环”的哪一层
→ 选择最小且完整、与现有架构一致的方案
→ 修改代码
→ 补/改相关测试
→ 跑本地/针对性验证
→ commit / push
→ 打开以 main 为 base 的 PR
→ 在 PR 上跑完整适用 CI / integration
→ 修复失败，直到当前 PR head 的必需验证通过
→ 检查 diff / 安全 / 连续性 / 回归风险
→ 正常 merge 到 main
→ 删除或停止使用已完成的 work 分支
→ main 合并后 CI 只做 canonical 复核，不再把 main 当第一次集成测试场
→ 顺手更新真正发生变化的状态/HANDOFF 事实
→ 从新的 main 重新评估下一项产品缺口
```

状态留底是开发闭环后的低成本收尾，不是独立产品目标。不要要求每个 commit 都修改 Markdown；只有架构、实现成熟度、验证事实、未完成风险或接手现场发生了对下一任有意义的变化时才同步相应文档。

不要完成一个小步骤就停下来等待用户安排下一步。只要没有触及人工审批边界，维护者应继续推进相关工作。

发现与当前工作直接相关、低风险且明显的 bug、测试缺口、脆弱错误处理、类型问题、死代码或维护性问题，可以顺手修复；不要借机做无关的大规模重构。

流程强度与风险匹配：小型低风险修改用“定位 → 修改 → 相关测试 → PR CI → diff → merge”的轻量闭环；中大型、跨模块、发布或高风险工作增加架构核对、集成/真实系统验证、Task Queue 和更完整的 HANDOFF。验证质量不能因为流程轻量而降低。

## HANDOFF 事实纪律

`.agent/HANDOFF.md` 是轻量施工现场和事实索引，不是实时 Git 镜像，也不是日报。

- HANDOFF 中的 SHA、CI run、branch 状态只能表示写入时的 `observed/verified checkpoint`；当前 `main` HEAD、open PR、相关 `work/*` 和 CI 必须在接手时重新查询。`dev/zn-agent` 只在历史任务仍明确引用它时作为兼容分支检查。
- 不要求 HANDOFF 保存“当前 HEAD”。HANDOFF 自身的提交会生成新的 HEAD，强求两者永远相等会形成无意义的自引用更新。
- `active` / `in progress` / `isolated lane` 等声明必须绑定可恢复的 durable evidence：至少有真实 branch delta，或对应 open PR。只有计划、预留 ownership 或聊天安排时只能写 `planned` / `reserved`。
- 已合并、撤销或失去 durable evidence 的 active 声明，应在本轮收尾中删除或降级，不能继续留作当前事实。
- Git/GitHub 可直接推导的元数据不要大量复制进 HANDOFF；优先记录 Git 本身表达不了的语义：为什么这个检查点重要、实际验证到哪里、还剩什么风险。

接手时发现 HANDOFF 与 live Git/CI 不一致，不应先停下来做文档工程；以 live evidence 恢复事实，在当前工作闭环的收尾中顺手对账即可。只有偏差本身会误导当前高风险决策时，才优先修正文档。

## 分支与提交

当前分支职责：

```text
main          = 唯一长期集成主线 / canonical source / release branch
work/*        = 从最新 main 拉出的短命开发、修复、研究分支；完成后经 PR 合回 main

dev/zn-agent  = 历史兼容分支，不再接收新的产品开发或作为 PR base；在仍保留期间应保持与 main 对齐
```

普通开发**不得直接在 `main` 上试错**，也不得再先合入 `dev/zn-agent` 等待 CI。正常路径固定为：

```text
main
→ work/<one-real-product-slice>
→ implementation + focused verification
→ PR(base=main)
→ required CI / applicable real integration on the PR head
→ green
→ merge main
→ delete/retire work branch
```

**分支是隔离风险的工具，不是长期堆积工作的仓库。** 一个 `work/*` 默认只承载一个明确产品切片；不要在一个分支连续堆多个已经可以独立合并的功能。PR 变绿后应及时合并，不再制造“开发线领先 main 数十/数百个 commit 后再 promotion”的批量集成。

`main` 合并后的 CI 是 canonical 复核，不是第一次发现集成问题的地方。如果某类真实 integration 是该产品切片的 merge gate，它必须能在 PR 阶段运行；不能先 merge 再用 `main` 失败来决定这次改动是否合格。

不要把“同步 main”“promotion”“canonical source”当成独立产品里程碑。正常开发完成时 merge main 就是闭环本身，不再另设长期 promotion 阶段。

禁止对 `main` 使用 force push、历史重写、绕过失败 CI 或伪造完成状态。历史兼容 `dev/zn-agent` 也不得被重新当作可 force/rewrite 的第二主线。

## ZN-only ownership 边界

活跃开发树必须保持 ZN-only。历史或外部参考实现可以用于理解成熟机制、异常边界和测试思路，但不得重新成为：

- ZN runtime；
- resident 主循环；
- ZN UI / Electron main / preload；
- gateway brain；
- Python distribution；
- 正式构建或发布依赖；
- 产品控制面。

需要参考成熟实现时：

```text
ZN 有具体需求
→ 阅读 dedicated reference branch、Git 历史或外部参考实现
→ 理解机制和边界
→ 提取/适配最小完整机制
→ 放入 ZN-owned namespace/interface/config/state/lifecycle
→ 删除参考产品假设
→ 增加 ZN 行为测试
→ 切换 active caller
```

不要为了通过测试恢复历史产品路径、兼容层或旧控制面。

## 发布能力属于仓库，不属于某个模型

GPT、Claude、Gemini、Codex、人类开发者等都只是可替换维护者。

在授权范围内，维护者可以自行修改代码、建分支、commit、push、创建 PR、查看和修复 CI、按仓库规则合并，以及触发仓库定义的低风险开发流程。正常可逆工程动作不需要每一步都等待聊天确认。

正式发布方法必须保存在仓库自动化中，不能依赖某个模型记得手工步骤。

当前正式发布入口以 `.github/workflows/zn-release.yml` 为准：

```text
可追踪 commit/tag
→ GitHub 自动构建
→ 正式产物
→ 验证正式产物
→ 发布不可变版本文件
→ GitHub Release（需要时）
→ stable.json 最后更新
→ 客户端发现新版
```

客户端不得把 `git pull` 私人仓库最新源码作为正式更新机制。

## 密钥和电脑丢失原则

源码、架构、开发状态、测试、构建和发布规则应尽量存在远程仓库或项目级在线基础设施中。

真正的 Token、对象存储密钥、发布/签名私钥、密码和生产凭证不得提交到仓库。它们应保存在 GitHub Secrets、发布平台安全存储、操作系统安全凭证库或其他项目级安全设施中。

维护者只需要触发流程，不应该需要知道秘密值本身。

## 已废弃：专用“自我维护”系统

专用“自我维护”产品线已经删除。完整的废弃说明见 `docs/ZN-RETIRED-DIRECTIONS.md`。

以后修改 ZN 仓库时，把它当成普通代码仓库，走通用 Work、File、Terminal、Git、Repo Test 和编码流程。**不要因为目标仓库是 ZN，就重新增加一套 maintenance runtime、repair intelligence、专用 BUG 上报、专用 UI/RPC 或额外 authority。**

通用 Health、Recovery、Git、测试、文件、终端、浏览器、桌面和 Update 能力继续保留。这些是正常产品底盘，不属于已经废弃的“自我维护系统”。

本次 2026-09-04 的专用历史清理是项目所有者明确要求的一次性例外。它不改变正常规则：以后仍禁止在没有明确授权的情况下 force push 或重写 `main` / 历史兼容分支历史。

## 接手成功标准

```text
换 GPT       → 能读仓库、知道 ZN 现在缺什么、自己继续开发
换 Claude    → 能读仓库、知道 ZN 现在缺什么、自己继续开发
换 Codex     → 能读仓库、知道 ZN 现在缺什么、自己继续开发
换其他模型   → 能继续
换人维护     → 能继续
聊天记录丢失 → 能继续
开发电脑丢失 → 换电脑登录仓库后能继续

仓库 + 产品目标 + 真实代码 + 状态 + 测试/CI + 项目级发布基础设施
= 长期自主开发和发布的连续来源
```

**上一任留下事实，下一任继承事实；但下一任仍然要自己思考、自己找问题、自己把 ZN 往前做。**