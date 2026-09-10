# ZN Maintainer Handoff

> Updated: 2026-09-10
>
> Canonical branch: `main`
>
> This is a current-work-site summary, not a changelog. Real code, Git state, tests and CI remain authoritative.

## 接手先恢复现场

真实代码、真实 Git、真实测试和真实 CI 高于这份文档。接手时必须重新查询 `main`、相关 `work/*`、open PR 和 CI；只有历史任务仍明确引用 `dev/zn-agent` 时才把它作为兼容分支检查，不能再把它当新的开发主线。

当前已核实的检查点（不是永久 HEAD）是：

```text
historical checkpoint: PR #238 merged as 8cd2ff73038bbdba33017f71d91893296b7c082c
E2E-15 final PR head: f1513a34b798fbb07cfc2d903f63d621c085e90e
E2E-15 PR #237 merged as: d5a5be80d6d35328685be07fc54be76d1bcc955c
verified main checkpoint after E2E-15 merge: d5a5be80d6d35328685be07fc54be76d1bcc955c
ZN CI #1694: success
ZN Windows Interactive Desktop E2E #293: success
ZN Work Recovery E2E #329: success
ZN Managed Browser E2E #279: success
```

PR #237 已通过正常 GitHub 路径合并，且上述 merge SHA 上的 post-merge canonical checks 已完成并通过；E2E-15 因此已达到 `CLOSED representative path`。`d5a5be80...` 只是写入本 HANDOFF 时重新核实的 checkpoint，不是永久 HEAD。

如果 `main` 已前进，以新代码和新验证为准。

## 当前已经落地的 Delegated Work 基线

ZN 仍是唯一 Resident、唯一 Root Work owner。worker/model 仍是可替换的受限执行/认知资源，worker `done` 不是 Root completion。

当前 `main` 已经具备：

- durable Work thread / WorkItem / WorkerRun / artifact facts；
- per-WorkItem bounded delegation 和 worker context/tool/authority scoping；
- existing `ModelRouter` 下的 task-capability routing、route/provider provenance、cost/latency/reliability accounting；
- durable Work route/privacy policy 进入 ModelRouter hard eligibility，policy/privacy fail closed；
- `ResidentHealthJournal` 动态运行健康观测进入 health-aware routing；
- durable worker progress supervision，包括 heartbeat / no-progress / stall detection；
- bounded retry、policy-safe fallback/reassignment；
- delegated restart reconciliation、no-replay recovery；
- natural-language same-Work steering、plan-version replan、stale old-worker result gating；
- restart continuation，已经完成的 historical effects 不盲目 replay；
- durable delegated facts 向既有 `work_progress` contract 和 Resident UI 的 privacy-safe bounded projection；
- bounded flat current-plan sibling dependency/readiness substrate：durable `WorkItem.dependency_ids`、same Root/thread/current plan validation、immutable dependency edges、derived readiness、WorkerRun/cognition/completion gates、restart durability、fan-in，以及 corrupt/cyclic/dangling graph fail closed。

这些能力是 Resident-owned 的 bounded substrate，不是通用 long-task scheduler、递归 agent tree 或 general DAG runtime。

## 已关闭的代表性 E2E

### E2E-29

一个真实 cognitive route 可以承载多个 independent WorkerRun；worker 数和模型数不绑定。Root completion 仍由 ZN 根据 acceptance/evidence 决定。

### E2E-30 / E2E-42

已经按仓库当前 acceptance policy 关闭：durable route/privacy policy、hard eligibility、route/provider provenance 与 guarded multiroute acceptance 已落地。

重要边界：该 closure 包含明确记录的 **owner-approved environment waiver**，因为当时环境缺少第二个真实 provider family。不得把它写成已经获得两个真实 provider family 的完整生产证据。

保留的 guarded two-provider acceptance 会在真正配置两个 provider family 时要求无 skip 并 fail closed；不要删除或弱化这个 guard。

### E2E-28 / E2E-34

已经通过 guarded real-model acceptance 关闭代表性路径：durable progress supervision、dynamic health-aware routing、bounded stall retry、restart reconciliation、no-replay recovery 与 policy-safe fallback/reassignment 已接上真实 Delegated Work 路径。

2026-09-09 暴露过一个 guarded acceptance timing flake：测试把 `health_backoff_seconds=300` 当成硬等待窗口，但 Router 的真实契约会把动态 health backoff 封顶 60 秒后允许 HALF_OPEN probe。PR #238 只把 pinned-policy fail-closed 断言移到 breaker 明确 OPEN 的确定窗口，未修改 Router/health semantics，并通过真实 E2E-28/34 acceptance + ZN CI 后单独合并到 `main`。

这不等于无限期后台执行、任意调度策略或所有长任务场景都已经 product-closed。

### E2E-27 / E2E-33

已经关闭代表性真实路径：natural-language same-Work steering、current-plan replanning、plan-version stale gating、old-worker result protection、restart continuation，以及 completed historical effects 不 replay。

更广任务类型、跨天和更长期真实使用覆盖仍需继续扩大。

### E2E-36

2026-09-10，PR #244 已完成 exact attempt-bound uncertain-side-effect restart resolution 的 representative closure。replay-sensitive Body action 在 dispatch 前持久化 attempt；restart 后如果 outside-world outcome 仍不确定，Work 保持 `user_decision_required`，既不把中断当普通失败，也不 blind replay。

显式 user resolution 只允许当前 exact attempt 的 `effect_happened` 或 `retry_authorized`。前者写入 audit-distinct `user_confirmed_effect` 并禁止再次 dispatch；后者写入 `user_authorized_retry`，只终结旧 attempt，再回到普通 Body guard，真正重试必须生成 fresh attempt。fresh attempt 如果再次 uncertain，旧授权不能继承。machine `verified_effect` / `verified_absent` 保持独立机器证据语义。

Store 以单一 SQLite transaction 绑定 event/attempt/WorkingState/recovery/native-intent identity；stale/cross-thread/non-recovery/conflicting control fail closed 且不产生部分状态。Work control 与 `work_resolve_uncertain` 只公开 bounded recovery metadata，不把原 action args 变成 control-plane authority。

PR-head evidence 已实跑：`ZN Work Recovery E2E` 为 `170/170 OK`，E2E-36 三条真实 restart 路径均通过；ZN CI、Windows Interactive Desktop E2E、Managed Browser E2E 也通过。最终 merge SHA 与 post-merge canonical checks 必须在 merge 后重新查询，不能把 PR head 当 permanent main identity。

边界：这不是任意第三方 exactly-once guarantee，不表示所有 outside-world effects 都可自动恢复，也不把用户确认冒充 independent machine evidence。

## User Browser / Browser / Windows 当前事实

### E2E-05

已有真实 USER Browser authenticated research -> persisted mutation 的代表性 closure。它证明 existing authenticated session 可以参与受限 research/return/mutation 路径，不代表任意登录网站都已经支持。

### E2E-07

已有 task-scoped causal USER Browser child-tab attribution：causal popup handling、authorization generation binding、fresh opener reread、child -> root context return，以及 unverified causal click 不 replay。该 bounded representative path 有真实 interactive acceptance。

不要再笼统写“popup support 尚缺”；正确边界是：causal popup/new-tab representative paths 已验证，任意 popup/frame/site complexity 仍然更广。

### E2E-08

已经验证的范围是：

```text
standard HTML autocomplete="one-time-code"
same explicitly authorized USER-browser tab
same authorization generation
same origin
non-terminal waiting_for_user
user manually completes OTP
fresh Sense / re-ground
same Work resumes
```

安全事实：ZN 不读取 OTP、不自动输入 OTP；blocker 期间模型/Body 不继续执行；OTP 不进入 cognition、Work progress、Body history 或 durable SQLite；authorization generation 改变时 fail closed。

明确没有声称支持：CAPTCHA solving、WebAuthn/passkey automation、cross-origin IdP handoff、password automation、payment-field automation。

### E2E-15

PR #237 的 final PR head `f1513a34b798fbb07cfc2d903f63d621c085e90e` 已完成真实 Windows interactive representative acceptance，并于 2026-09-09 通过正常 GitHub 路径合并为 `d5a5be80d6d35328685be07fc54be76d1bcc955c`。历史上更早的 pre-documentation verified head `ab441f0e6c25634e0e9a099a23a70fd9a26e6e95` 仍只是过程证据，不再代表 current state。merge 后 current-main canonical checks 也已通过。

真实 WinForms fixture 在原 Desktop target 已 grounding 后通过 `ShowDialog()` 打开同进程 modal；harness 不向 Resident 提供 modal HWND、RuntimeId 或恢复 action，也不替 Resident 关闭 modal。

Resident 仍是同一个 Resident、同一 Root Work、同一 pointer lifecycle。admission 需要 exact parent HWND/PID/process、foreground topology change、同进程 dialog、`GW_OWNER(dialog)==parent`、UIA `IsModal=true`、parent `BlockedByModalWindow`，并且 exact dialog subtree 里只能存在一个 deterministic safe defer/continue/close-notice action。input 前 fresh revalidate exact modal/Button authority；stale/ambiguous/wrong-owner/cross-process evidence fail closed。

真实证据：`dialog_dispatch_count=1`、safe action=`稍后继续`、`unsafe_update_count=0`、`modal_absent=true`、`parent_ready=true`、`same_root_work=true`、旧/新 Edit RuntimeId 不同，最终 title=`ZN 对应订单记录已打开`。成功实跑里 `wait_for_input_idle=false`，因此它只保留为 telemetry；hard readiness 来自 exact Win32/UIA identity、modal absence、visible/enabled/foreground 与 UIA `ReadyForUserInteraction`。

不要把该 closure 扩张成 arbitrary Windows dialog automation。credentials/password、UAC/elevation/security、save/discard/delete/overwrite、file picker、payment/purchase、installer/restart/update decision、跨进程或歧义 dialog 都不在 autonomous safe slice；modal side effect 不 blind replay。

### E2E-24

PR #236 已完成真实 Windows interactive representative acceptance：一个自然语言任务保持同一 Root Work，从已经登录且显式授权的 USER Browser 当前 tab 识别随机异常客户，写入唯一 exact yesterday workspace target 一次并 fresh reread，随后从当前 Desktop foreground 重新建立 exact HWND/PID + UIA semantic authority，把同一客户记录标记待跟进一次，并用 fresh app title 独立验证。

对抗性路径会在 Desktop grounding 后真实重建目标控件并改变 RuntimeId；旧 UIA evidence 必须被拒绝、重新从当前 automation tree re-ground。两个同等文件候选时必须 fail closed，不得写文件或改桌面记录。

该 closure 只证明 bounded same-Work USER Browser -> File -> Desktop customer-record path。不要扩张成 arbitrary website/file/app automation、generic cross-surface workflow engine、general RPA、second orchestrator 或 general DAG scheduler。

为让真实 interactive acceptance 稳定反映产品而不削弱生产安全边界，Windows Interactive runtime 显式安装 Playwright Chromium；Edge ephemeral test profile snooze developer-mode extension warning；共用 isolated USER Browser fixture 的 `activate()` 必须确认 exact HWND 已成为 foreground 后才继续。生产侧 exact foreground HWND/PID fail-closed 校验没有被放宽。

### Browser Body V2 bounded substrate

近期已经有经过验证的窄切片：

- bounded `BrowserScene` sensing foundation；
- tab open/switch/close 与 back/forward/reload lifecycle/history；
- exact BrowserScene focus/type/check/uncheck/navigation actions；
- causal popup attribution；
- authority-safe causal file upload/download；
- verified stateless command clicks；
- verified stateful `aria-pressed` / `aria-expanded` / `aria-selected` control clicks。

这些路径坚持 exact target、fresh revalidation、authority 和 independent postcondition。它们不等于任意网页、任意 frame/dialog、任意下载上传流程、OCR/vision fallback 或所有 UI control 已经完成。

### Windows Machine Capability / Application Awareness

当前已有 Windows Machine Capability / Application Awareness V1：多源应用 inventory、deterministic identity resolution、Installed/Running/Window/Foreground 分离事实、bounded machine facts、identity-bound launch，以及 fresh process/window verification。

随后 existing-app activation 已收紧为 safe exact admitted application/HWND/PID path：minimized restore / foreground request 后必须 fresh exact foreground proof；replacement/PID/topology drift 在 native side effect 前 fail closed。

E2E-15 在此之上增加的是一个 bounded same-process safe-modal interruption slice，不是第二个 DialogAgent/OS Agent，也不是任意窗口自动化 framework。

这仍不是任意应用生命周期、任意窗口拓扑或全 Windows automation 的 product closure。

## 用户可见 Delegated progress

旧的 `OPEN / INTERNAL FOUNDATIONS` 已过时。当前 delegated progress 已经：

- 从 durable delegated Work facts 投影；
- 复用既有 `work_progress` contract，没有第二套 progress truth；
- 做 bounded privacy-safe normalization；
- 进入 Resident UI；
- 覆盖 restart / steering 场景。

状态应理解为 `CONNECTED + VERIFIED NARROW / PARTIAL UX`。长期任务表达、解释质量、复杂 multi-workstream UX 仍有产品空间。

## 当前不要重复开发的东西

不要再把下面这些当成尚未接线的默认任务：

```text
E2E-30/42 route/privacy acceptance
dynamic ResidentHealthJournal -> routing
E2E-28/34 systematic stall/no-progress supervision
restart-safe delegated reconciliation
E2E-27/33 active steering + natural continuation
delegated progress projection
bounded flat WorkItem dependency/readiness
E2E-05 representative authenticated research mutation
E2E-07 representative causal child-tab path
E2E-08 representative OTP user-presence handoff
E2E-15 bounded same-process safe modal recovery representative path
E2E-24 bounded same-Root USER Browser -> File -> Desktop representative path
E2E-36 exact attempt-bound uncertain-side-effect restart resolution
```

如果新的真实任务仍在这些区域失败，应先确认是覆盖广度/新边界问题，而不是重新造一套已经存在的机制。

## 仍然必须保留的边界

- Resident owns Root Work；没有第二个 Resident。
- model/worker 是 replaceable cognition/execution resource，不拥有 ZN identity、Memory、authority 或 completion truth。
- worker `done` != Root completion。
- real-world effect 必须通过 authority + fresh evidence；completed effects 不盲目 replay。
- 只有一个 ModelRouter；不要增加第二套路由控制面。
- 只有一个 durable Work/progress truth；不要增加第二套 orchestration ledger。
- bounded flat dependency/readiness != general-purpose DAG scheduler。
- E2E-30/42 waiver != two-real-provider production proof。
- E2E-08 representative OTP handoff != all MFA support。
- E2E-15 representative same-process safe modal recovery != arbitrary Windows dialogs / UAC / credential or business decisions。
- E2E-24 representative three-surface closure != arbitrary cross-surface automation / general RPA。
- E2E-36 representative uncertain-side-effect closure != arbitrary exactly-once / generic third-party recovery。
- Browser Body V2 representative slices != arbitrary web automation。
- current delegated supervision != unlimited/general background scheduler。
- 没有完整 DLP、OS sandbox 或 blanket credential authority。

## 下一阶段如何选任务

不要恢复 2026-09-06 的三组“下一阶段”顺序。它们已经形成代表性 closure。

从 current main 继续时，优先在 `docs/ZN-REAL-TASK-E2E-CATALOG.md` 和真实产品路径里选择仍然失败/覆盖不足的普通用户任务，尤其是：

- E2E-24 bounded closure 之外更复杂的真实 cross-surface task（Browser + Desktop + File/Terminal/Application）；
- Browser/User Browser 在真实站点、frame/dialog/复杂 navigation 等更广场景的可靠性；
- 现有 supervision/steering 基础上的更长周期真实连续体验与 progress/explanation UX；
- E2E-15 bounded modal slice 之外，由当前真实应用/OS capability 缺口导致的具体 E2E 阻塞。

不要因为“下一阶段”这个词自动授权 Memory、credential、installer/updater/release trust 等高风险大改；不要把 general DAG scheduler、recursive delegation 或 multi-agent platform 当默认路线。

## E2E-35 — next-day product continuation/status-first inspection

2026-09-09，PR #240 的 bounded representative path 已通过真实 PR-head 验证：`ZN Work Recovery E2E #336`、`E2E27-33 Real Steering Replan Acceptance #9`、`ZN CI #1703` 均为 success。最终合并 SHA 必须在 merge 后重新查询，不能把当前 PR head 当 canonical main。

用户代表句保持为：`昨天那个产品继续，先看看做到哪了。`。当前实现解析唯一 yesterday Work，复用同一 WorkThread、Root Work、current plan 和既有 Resident event，以现有 durable Work truth 派生 root goal、plan、completed/blocked items、blockers、artifacts 与 delegated progress；当前 workspace/Git/artifact 只通过 bounded read-only Body Sense 重新检查。inspection 不创建新 Resident event、不调用模型、不创建 WorkerRun、不改变 WorkItem status/plan，也不给执行授权。历史 artifact evidence 与当前 `unchanged`/`modified`/`missing` observation 分开保存/展示，当前漂移不会改写历史完成事实。

Desktop 把 `inspection_complete` 当成一次只读交互结束，而不是 Work terminal/finalized，因此输入框立即可继续使用；随后同一 thread 的 `继续`/`那继续吧` 只在最新 durable message 确认为 inspection 时复用同一 active event，包含 restart 后场景。已完成 Work 可以只读检查，但 bare replay 仍 fail closed；zero/multiple yesterday candidates 也 fail closed。

边界：这是一个 next-day product continuation/status-first 的窄代表性 closure，不代表 arbitrary history search、多周/多月项目重建、跨设备 continuity、通用项目管理 dashboard、general long-horizon orchestrator、general DAG scheduler 或 recursive multi-agent runtime 已完成。新的 continuity 失败应先判断是否超出这条 bounded slice，而不是重新造第二套 Work/progress truth。