# ZN 自主组队（M-12）

ZN 自己判断"这个任务值得拆成并行团队"，而不是只等用户说"组个团队"。

## 决策流（`runtime/python/zn_agent/core/self_team.py`）

每个 Work 事件只决策一次，结论记在 working state（`self_team_decision`，跨 pulse 持久）：

1. **确定性预筛**（不烧模型调用）：空任务 / 用户明确不组队 / 用户已明确要求组队（走用户触发路径）/ 小任务且无并行结构 → 直接 `no_team`。
2. **一次有界认知调用**：`kernel.run_goal(..., max_attempts_override=1)` 问模型是否值得组队；回答是严格 JSON契约（`assemble/reason/project_title/role_keys/subtasks/parallel`），逐项校验——角色必须在 `ROLE_TEMPLATES` 内、数量 2–6 且不重复、subtasks 一一对应。任何不可信回答 fail closed 为 `no_team`。
3. **审批/预算包络**：敏感任务（`detect_sensitive_step`）或团队规模超包络（默认 4 人，可配）→ `needs_approval`，开审批卡（kind=`team_assembly`），批了才建队、拒绝/过期则单人继续。

## 接入点（`team_work_resident.py`）

`_deliberation_step` 里 disband 检查之后、团队分支之前：非团队事件跑一次 `SelfTeamDriver.step`。

- `assemble` → 把**用户路径同款** `team_request` payload 注入内存事件（含 `self_team` 标记与分解出的 subtasks），落入已有的团队分支：`TeamWorkOwner`/`TeamRunner`/CP-3 判定全部复用，团队状态机零改动。
- `pending_approval` → 事件保持 alive 等审批卡（`_block_on_self_team_approval`），下一 pulse 重新 poll。
- `no_team`/`not_applicable` → 原样走正常单人路径。

`SelfTeamWorkOwner(TeamWorkOwner)` 只做一件事：`resolve_team` 复用父类全流程后，按模型的分解重写 plan——subtasks 变成各 plan item 的 objective；`parallel=true` 时去掉 item 间依赖，runner 当 pulse 全量并行派工。重建是确定性的（payload → 同一团队），跨 pulse 一致。

## 不做什么

- 不新增控制面、不改团队状态机、不改 `assemble_team`（重复角色仍拒绝）。
- 无工作区的事件不参与（团队分支无工作区会直接 terminal-fail，自主决策不制造这种失败）。
- 决策异常永远回退到单人路径，不破坏正常 Work。
