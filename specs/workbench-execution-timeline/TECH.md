# Workbench Execution Timeline 技术设计

<!-- SPEC LABELS: ready-to-implement -->

## 方案
将动作投影保留在现有 ResidentWorkLedger.progress()，提取单一、只读、限制数量/长度的 _recent_public_body_actions()，复用现有 privacy_choke.strip_tags() 做敏感值过滤。finalize 时把同样的最多六条动作快照纳入当前 activity 消息的 detail.body_actions。沿用原有 JSON-RPC 消息映射，无新增存储、执行或重放路径。

## 改动点
1. `runtime/python/zn_agent/core/work.py`：共用的 Body 行为公开投影；在 finalize 写入受限投影。忽略无关 event id，永不写入参数、完整 stdout 或堆栈。
2. `apps/desktop/src/zn/execution-timeline.ts`：Node 可测试的历史动作解析，过滤伪造/损坏数据并做上限。
3. `apps/desktop/src/zn/execution-timeline.tsx`：语义化时间线、状态、可展开结果；当前工作与历史共用组件。
4. `apps/desktop/src/zn/workbench.tsx`：运行中展示，历史 activity 默认折叠；不改变 Resident 权限控制。
5. 样式与 en-US/zh-CN 本地化使用现有 ZN 主题 Token；不引入前端依赖或危险 HTML 渲染。

## 验收
新增 Python 测试覆盖过滤、保留最近六条、完成时持久化与重启可回放；Vitest 测试覆盖解析、恶意字段、不完整时间和数量限制，加入仓库固定 Electron CI 测试清单；执行现有相关 Work / Desktop 测试并验证 PR 头状态。

## 风险
- 原 Resident 只保存最新六个动作；UI 必须明确“最近”而非宣称完整审计。
- 对旧历史 activity 缺少 body_actions 时只保留原有执行证据，不伪造数据。
- 原始 Body 审计另有安全责任；本任务只给 Work UI 的输出新增单点过滤，不改动既有 Body 真实性。
- 当前环境不能进行正式 Electron 图形 E2E，必须在 PR 中如实注明，不能以静态断言替代视觉 QA。
