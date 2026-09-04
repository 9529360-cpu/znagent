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
-> 状态变化后重新 Sense / Situation / Thought
-> 独立验证用户真正要的结果
-> 保持后续连续性
```

复杂编码可以主要依赖强 coding model；深度研究可以依赖 research model 和 Web；视觉任务可以依赖 vision model；电脑操作依赖真实 Browser/Desktop/File/Terminal 等工具。模型和工具都是资源，ZN 继续拥有用户目标、Durable Work、权限边界、现实证据、任务连续性和最终 completion judgment。

判断下一项工作，只问一件事：

**这个改动能不能直接提高 ZN 在真实用户电脑上自主完成真实任务的能力？**

如果不能，默认不是当前主线，除非它正在直接阻塞主线。

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
-> 找出完成它真正缺的认知、工具、权限或验证能力
-> 只补这些缺口
-> 打通完整任务
-> 用真实 E2E 验证最终用户目标
-> 修复过程中暴露的架构问题
-> 再进入下一个更难真实任务
```

不要再按“checkbox、textbox、button、navigation、terminal、UIA 一个个做完”来判断产品进度。这些只是身体动作。

同样，不要因为 coding model 能生成代码、模型能给出答案、命令退出码为 0、HTTP 返回 200 或某个 provider 声称成功，就把任务视为完成。真实任务是否完成必须由当前世界中的结果证据来证明。

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

因此：

```text
primitive success != E2E success
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
- Terminal / CLI / 本地开发工具 / 合理系统管理任务；
- Browser + File、Browser + Desktop、File + Terminal、Browser + File + Desktop 等跨 surface 任务；
- 需要专业 cognition + 真实工具联合完成的任务；
- 页面、窗口、文件、程序状态变化后的重新调查；
- 任务中断、Resident 重启和跨天继续；
- 用户新指令对 active Work 的安全 steering；
- 权限拒绝、用户 presence、敏感字段和安全退出；
- 失败后重新观察、寻找替代路径；
- 最终结果的独立验证。

产品成熟度看的是这些任务族里 **普通用户能稳定交给 ZN 办成多少事情**，不是某个垂直 capability 有多少 API。

## 当前最值得继续闭合的方向

- 页面、窗口、文件或目标变化后，能够重新 Sense / Situation / Thought，而不是脚本失配直接失败。
- 自然语言里的“刚才那个继续”“昨天那个继续”能恢复同一个真实 Work，而不是从零开始。
- active task 收到用户新指示以后，能安全改变当前计划，不重复已经发生的外部副作用。
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
- 合并了几个 PR。

先说：

- ZN 以前不能完成什么真实任务；
- 现在能完成什么真实任务；
- 用户的成功路径是什么；
- 哪些 cognition + tools + authority + verification 真正参与了闭环；
- 还有哪些地方会失败；
- 下一项最阻塞真实使用的问题是什么。