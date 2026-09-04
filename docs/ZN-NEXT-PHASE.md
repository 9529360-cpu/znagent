# ZN Next Phase

这份文件只描述下一阶段产品主线，不给 updater、rollback、signing、release trust、credential、identity 或 long-term memory 的高风险改动自动授权。

## 产品目标

ZN 的下一阶段不是继续堆基础设施，而是把已经存在的 Self、Body、Senses、Situation、Thought、Will、Work、Memory、Browser、Desktop、Computer Use 和 Recovery 真正组合成普通用户能长期使用的完整任务闭环。

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
-> 找出完成它真正缺的能力
-> 只补这些缺口
-> 打通完整任务
-> 用真实 E2E 验证
-> 修复过程中暴露的架构问题
-> 再进入下一个更难真实任务
```

不要再按“checkbox、textbox、button、navigation、terminal、UIA 一个个做完”来判断产品进度。这些只是身体动作。

## 当前最值得继续闭合的方向

- 页面、窗口、文件或目标变化后，能够重新 Sense / Situation / Thought，而不是脚本失配直接失败。
- 自然语言里的“刚才那个继续”“昨天那个继续”能恢复同一个真实 Work，而不是从零开始。
- active task 收到用户新指示以后，能安全改变当前计划，不重复已经发生的外部副作用。
- Browser + File + Desktop 这类三 surface 联合任务能完成并独立验证结果。
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
- 还有哪些地方会失败；
- 下一项最阻塞真实使用的问题是什么。
