# ZN Implementation Status

这是一份当前实现事实表，不是 roadmap。真实代码、真实 Git、真实测试和真实 CI 高于本文件。

## 仓库状态规则

- 主开发分支：`dev/zn-agent`
- canonical / release 分支：`main`
- 文档里的 SHA 和 CI run 只能当历史检查点，接手时必须重新查询。
- Git/CI/main 同步属于工程卫生，不是产品里程碑。

## 已废弃方向

专用“自我维护 / 自我修复 / upstream BUG report”产品路线已经明确废弃并从当前代码树中移除。

它不再属于 ZN 的现役能力，不再属于产品缺口，不再属于后续优先级。

不要重新增加 maintenance runtime、maintenance cognition、maintenance repair、专用 BUG report transport/intake/reconcile、maintenance UI/IPC/RPC，或任何因为目标仓库是 ZN 就自动扩大权限的特殊路径。

详细说明见 `docs/ZN-RETIRED-DIRECTIONS.md`。

通用 Health、Recovery、Work、Memory、File、Terminal、Git、Browser、Desktop、Computer Use 和 Update 架构继续保留。

## 当前能力事实

| 区域 | 当前状态 | 还缺什么 |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | 已接通并有多轮验证 | 真实任务广度仍需继续扩大 |
| Durable Work / restart recovery | 已接通并验证 | 需要继续转化成普通用户可感知的长期连续性 |
| Managed Browser | 多个受限语义动作已验证 | 更广泛页面变化、弹窗、frame、下载上传等仍不完整 |
| User Browser Bridge | 已有真实 existing-session 授权路径和语义控制基础 | 仍需扩大真实网站覆盖、权限 UX、漂移后的稳定重规划 |
| File / workspace tasks | 已有自然语言文件任务和跨 surface 闭环证据 | 歧义来源、复杂整理和更广任务类型仍需加强 |
| Desktop computer use | 多个窄场景已真实验证 | 通用跨应用连续任务、窗口变化和目标漂移仍需加强 |
| Browser + File / Browser + Desktop | 已有代表性真实闭环 | 三个 surface 联合、复杂重规划仍是缺口 |
| Work continuity | 有 durable ledger 和恢复基础 | “刚才那个继续”“昨天那个继续”以及 active task steering 仍需产品化 |
| Autonomous Investigation / replanning | 已有基础机制和部分语义 re-ground | 仍偏已知模式驱动，需要更通用地处理目标不存在、状态冲突和替代路径 |
| Installed N -> N+1 continuity | 不完整 | 真实升级过程中身份、数据、Work 和不确定副作用连续性尚未产品闭环 |

## 当前产品缺口

当前优先级只围绕“普通用户真实任务能不能完成”排序：

1. **真实任务自主闭环还不够广。** ZN 已经能完成多个真实 E2E，但仍不能稳定覆盖更多普通用户的模糊、多步骤、会变化的任务。
2. **自主 Investigation / replanning 仍不够通用。** 页面、文件、窗口、目标或环境变化时，部分路径仍容易依赖既有模式，而不是主动重新调查。
3. **长期 Work 连续性还没成为完整用户体验。** Durable state 已存在，但自然引用、active task steering、跨重启继续仍需闭合。
4. **多 surface 联合任务仍不够强。** Browser + File、Browser + Desktop 已有验证，下一步要继续向 Browser + File + Desktop 等真实任务扩展。
5. **安装后长期连续性仍未闭环。** N -> N+1 时身份、Memory、Work、配置和不确定外部副作用需要真实环境证明。

## 判断产品完成的标准

不要把下面这些当成“产品已经完成”：

- 有代码；
- 有测试；
- CI green；
- 有 installer；
- 有 recovery module；
- 有新的抽象或 provider；
- 某个 primitive 单独 verified。

真正要看的是：

```text
普通用户给正常人类任务
-> ZN 自己理解
-> 自己 Sense 当前电脑状态
-> 自己选择 Browser / Desktop / File / Terminal / 网络资源
-> 自己拆解并执行
-> 状态变化后重新观察和判断
-> 保留 authority / fresh evidence / non-replay
-> 独立验证真实结果
-> 中断后能继续
```

## 当前开发原则

选择一个高价值真实用户任务，找到它真正缺的能力，只补这些缺口，打通完整 E2E，再进入下一个更难任务。

不要重新回到“单个 capability -> 大量 contract/test/CI -> 下一个 capability”的开发方式。
