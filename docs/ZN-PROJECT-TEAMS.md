# ZN Project Teams（项目团队）

> 设计文档。目标：用户一句话——"XXX 项目太慢了，给这个项目组个专业团队"——ZN
> 拉起一支长期存在的多智能体团队（架构、调研、开发、测试），并行推进，
> 用户只在关键节点拍板。

## 红线（继承 ZN-ORCHESTRATION-RESEARCH）

- **不建第二控制平面**：团队跑在现有 Work / WorkItem / WorkerRun 授权体系里。
  模型不选自己（ModelRouter 仍是 kernel-owned），副作用必须挂在 Work 授权下。
- **不引入新的 resident / orchestrator 身份**：coordinator 就是 resident 自己
  （或它委派的一个 worker），不是新主体。
- **不用 workflow 框架替换 Work**：任务编排只用 `WorkItem.dependency_ids`
  这一套已有机制。

## 模型

- **Team**：挂在一个 `work_thread`（项目）下，有 `team_id`、项目目标、roster。
- **Specialist（专员）**：durable 身份——有名字（如"阿建·架构"）、角色、职责、
  prompt 片段、**项目内记忆命名空间**。跨会话存在，不是用完即焚的 worker。
- **ProjectJournal（项目共享日志）**：append-only，所有成员写进展、交接、阻塞；
  coordinator 读它来调度。这是"共享记忆板"，对标外部产品的轮询式共享记忆，
  但用 ZN 已有的 journal/message 机制实现。
- **任务**：`WorkItem`，加 `assignee`（specialist 名字），`dependency_ids`
  表达"设计 → 开发 → 测试"的先后。验收标准写在 `acceptance_criteria`。
- **执行**：每个 WorkItem 的实际干活是一个 `WorkerRun`，挂在 Work 授权下；
  验收走 `verification_status`（fresh observation 验证），沿用现有"不许假装做完"机制。
- **升级**：成员卡住（blocked / stalled）→ 写 journal → coordinator 接管或拉用户拍板。
  用户永远只在判断点出现，不被细节打扰。

## 组建流程

1. 用户："给 XXX 项目组个开发团队"。
2. resident 选角色模板（architect / researcher / developer / tester，可扩展）。
3. 建 `work_thread` + roster + 初始 WorkItems（含验收标准与依赖链）。
4. coordinator 按 readiness 派活（依赖满足的 WorkItem → 对应 specialist 的 WorkerRun）。
5. 成员进展/交接写 journal；WorkItem 完成需验收；项目结束归档（记忆命名空间保留，可复用）。

## 切片

- **Slice 1（本分支）**：数据模型 + journal 消息格式 + 组建逻辑 + 到 WorkItem 的映射。
  纯加法：一个新模块、一个测试文件，不动任何现有文件。
- **Slice 2**：coordinator loop——按 `DependencyReadiness` 派活、读 journal 调度、
  验收交接、blocked 升级。只接现有 Work/WorkerRun 接口。
- **Slice 3**：成员长期记忆（project-scoped remember/recall）与项目复盘
 （把 journal 沉淀为可复用的团队经验）。

## 与外部产品的差异

Grok Bot 之类是云端多 Bot、按月收费、数据在人家电脑上跑。
ZN 的团队是**本机、用户私有、数据不出门**的同一套机制——这是产品定位差异，
不是功能差距。
