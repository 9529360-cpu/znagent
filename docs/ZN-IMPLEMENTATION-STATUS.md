# ZN Implementation Status

这是一份当前实现事实表，不是 roadmap。真实代码、真实 Git、真实测试和真实 E2E 高于本文件。

Updated: 2026-09-11

## 仓库状态规则

- 唯一长期集成 / canonical / release 分支：`main`。
- 新开发从最新 `main` 拉短命 `work/*`，PR 以 `main` 为 base；适用 CI/E2E 在 PR 阶段通过后再合并。
- `dev/zn-agent` 仅为历史兼容，不再接收新产品开发。
- 文档里的 SHA 和 CI run 只能当历史 evidence；接手时必须重新查询 current `main`。
- Git/CI/main 合并属于工程证据，不等于产品能力自动闭环。

## 状态语言

本文件继续区分：

```text
Exists
Connected
Verified
Product-closed
```

`VERIFIED NARROW` / `representative path closed` 表示真实代表性路径已经验证，但不代表整个 capability 类别已经 product-closed。

## 已废弃方向

专用“自我维护 / 自我修复 / upstream BUG report”产品路线已经废弃并从当前代码树移除。不要重新增加 maintenance runtime、专用 maintenance cognition/repair、专用 BUG-report control plane 或因为目标仓库是 ZN 就自动扩大权限的特殊路径。

通用 Health、Recovery、Work、Memory、File、Terminal、Git、Browser、Desktop、Computer Use 和 Update 架构继续保留。

## 当前能力事实

| 区域 | 当前状态 | 当前边界 / 仍需扩大 |
| --- | --- | --- |
| Resident Self / Body / Senses / Situation / Thought / Will | CONNECTED + VERIFIED | 真实任务广度仍需扩大 |
| Durable Work / restart recovery | CONNECTED + VERIFIED | 更长周期、跨天和更多真实任务上的连续体验仍需扩大 |
| Research & Information Work | VERIFIED NARROW; E2E-01/02/03 representative paths closed | bounded public-web multi-source search→extract、source identity/provenance/freshness/conflict、evidence-grounded cognition、same-Work restart continuation、optional exact-workspace Markdown fresh reread 已验证；不是 arbitrary Deep Research/authenticated-browser research/general citation engine/knowledge graph/vector DB/recursive swarm |
| Uncertain outside-world side effects | VERIFIED NARROW; E2E-36 representative path closed | exact replay-sensitive attempt 跨 restart 保持 fail closed；显式 user resolution 与 machine evidence 分离，retry authority 只终结一个旧 attempt 并要求 fresh guarded attempt；不是通用 exactly-once 或任意第三方 recovery |
| Work continuity / steering | VERIFIED NARROW; E2E-27/33/35 representative paths closed | natural-language same-Work steering、plan-version replan、stale old-worker gating、restart continuation，以及 bounded next-day status-first reconstruction/continue 已验证；更广长期使用仍开放 |
| Managed Browser / BrowserScene | CONNECTED + VERIFIED NARROW | 已有 bounded BrowserScene、tab/history、exact scene actions、causal popup、file transfer、stateless/stateful control clicks；复杂 frames/dialogs/general keyboard/OCR/任意网页仍未覆盖 |
| User Browser Bridge | CONNECTED + VERIFIED NARROW | E2E-05 authenticated research→mutation、E2E-07 causal child-tab、E2E-08 OTP user-presence representative paths 已关闭；真实网站和更复杂认证/导航仍需扩大 |
| File / workspace tasks | CONNECTED + VERIFIED NARROW | 歧义来源、复杂整理和更广任务类型 |
| Local Documents & Spreadsheet Work | VERIFIED NARROW; E2E-09/10 representative paths closed | bounded real DOCX payment-date edit + real XLSX exact-dedup/amount-format cleanup 已验证；复杂 Office package/公式/表格/图表/宏/任意文档编辑仍开放；不是 Word complete / Excel complete / Office Suite complete |
| Document Research Completion | VERIFIED NARROW; E2E-12 representative path closed | one exact attached-workspace real DOCX、1–3 explicit placeholders、existing public WebResource search→extract、prompt-safe evidence screening、two-source replacement support、deterministic omitted-conflict blocking、new-copy mutation 与 fresh reopen verification 已验证；不是 arbitrary DOCX completion、arbitrary Deep Research、general prompt-injection solution 或 Word/Office complete |
| Windows machine/application awareness | CONNECTED + VERIFIED NARROW | inventory/identity/launch/fresh verification 与 exact admitted existing-window activation 已有；任意应用生命周期/窗口拓扑仍未 product-close |
| Windows unexpected-modal recovery | VERIFIED NARROW; E2E-15 representative path verified | exact same-process directly owned UIA modal、blocked parent、唯一 deterministic safe defer/continue action、input 前 fresh revalidation、单次 side effect、modal absence + exact parent readiness、old RuntimeId rejection + fresh re-ground 已在真实 WinForms `ShowDialog()` path 验证；任意 dialog/UAC/credentials/save-discard/file-picker/payment/installer/update decisions 不在 closure 内 |
| Desktop computer use | CONNECTED + VERIFIED NARROW | 通用跨应用连续任务、目标漂移和更复杂应用语义 |
| Browser + File + Desktop | VERIFIED NARROW; E2E-24 representative path closed | same-Root exact business identity、USER Browser authority、exact workspace target、fresh file reread、exact foreground HWND/PID、UIA re-ground 与 final app verification 已在一个 bounded path 中验证；更复杂三-surface task/recovery 仍需扩大 |
| Cognitive resources | CONNECTED + VERIFIED | ZN-owned provider seam、多 route、热重配、provenance 已存在；更广 provider/product coverage 继续扩大 |
| Model routing hard eligibility | CONNECTED + VERIFIED NARROW | route/privacy policy、pin/deny/locality、dynamic health-aware routing 已接入；E2E-30/42 closure 包含 environment waiver，不等于双真实 provider family 生产证据 |
| Dynamic provider health -> routing | VERIFIED NARROW; E2E-28/34 representative path closed | `ResidentHealthJournal` 动态 observation 已进入 routing；更广 provider failures/长期运行仍需扩大 |
| Delegation admission | CONNECTED + VERIFIED NARROW | 更多真实任务上继续证明何时 direct、何时 delegated；避免 pointless delegation |
| Delegated Work coordinator | CONNECTED + VERIFIED NARROW | durable bounded delegation、routing、supervision、restart reconciliation 已接通；不是 general scheduler / recursive orchestration runtime |
| WorkerRun lifecycle | CONNECTED + VERIFIED NARROW | durable queued/running/completed/failed/stale、progress、bounded retry/reassign、restart reconcile 已存在；无限期/通用调度不在当前声明内 |
| Long-task supervision | VERIFIED NARROW; E2E-28/34 representative path closed | heartbeat/no-progress/stall detection、bounded retry、health-aware fallback/reassignment、restart reconcile 已验证；更长、更复杂任务仍需扩大 |
| One-model multi-worker | VERIFIED; E2E-29 CLOSED | 一个实际 route 服务多个隔离 WorkerRun 已证明；不是 worker/model 数绑定 |
| Strict WorkerContextPack | CONNECTED + VERIFIED NARROW | 未来 worker 类型继续审计；不是完整 DLP |
| Worker action authority | CONNECTED + VERIFIED NARROW | Body action admission，不是任意命令 OS sandbox |
| Worker completion verification | VERIFIED NARROW | worker `done` 仍只是 candidate result；Root completion 由 ZN 独立验收 |
| Stale delegated result protection | VERIFIED NARROW | plan-version stale gating 与 old-worker protection 已验证；更多任务继续覆盖 |
| Delegated user progress | CONNECTED + VERIFIED NARROW / PARTIAL UX | durable delegated facts 投影到既有 `work_progress` 与 Resident UI；复杂 multi-workstream UX/解释质量继续扩大 |
| WorkItem dependency/readiness | CONNECTED + VERIFIED NARROW | bounded flat current-plan sibling dependency/readiness、fan-in、restart durability、corrupt/cyclic/dangling fail closed 已实现；不是 general DAG scheduler |
| Autonomous Investigation / replanning | CONNECTED + VERIFIED NARROW | 已有代表性 re-ground/replan；更通用冲突、复杂跨 surface recovery 仍需扩大 |
| Resident local control plane | CONNECTED + HARDENED NARROW | loopback-only authenticated endpoint + per-process secret + endpoint ACL；更终局 Windows transport 仍可继续收敛 |
| Installed N -> N+1 continuity | PARTIAL / OPEN | 真实升级过程中 identity、data、Work 和 uncertain side effects 的全链路连续性尚未 product-close |

## Delegated Work 当前主链

当前 `main` 的 delegated-work 主链不是独立 multi-agent 平台，而是现有 Resident/Work/Router/Body 的纵向扩展：

```text
Root Work
-> BoundedDelegationPlanner
-> DelegatedWorkCoordinator (same Resident)
-> durable short-lived WorkerRun
-> strict WorkerContextPack
-> existing ModelRouter hard eligibility + health-aware scoring
-> existing Body action-authority gate
-> durable progress / supervision / restart reconciliation
-> fresh verification
-> Root completion remains ZN-owned
```

### Admission 与 context boundary

小而确定的目标可以走 direct path。WorkerContextPack 维持递归 fail-closed boundary：depth/node/item/string/final-size limits、nested sensitive-key rejection、secret-like token rejection、provenance/classification hook、plan-version validation。

`private` 不自动等于 cloud forbidden；route locality 以显式 `local_only` / `cloud_denied` / `cloud_forbidden` 等策略为准。

### Action authority

WorkerRun authority 在真实 Body effect 前从 durable Work/WorkerRun state 重新验证。review/research 不因 delegation 获得 workspace mutation；coding write 受 attached workspace 约束；stale plan 被拒绝。

这是 **action admission boundary**，不是进程级或命令级 OS sandbox。

### ModelRouter hard eligibility + dynamic health

现有单一 `ModelRouter` 先 hard-filter，再 soft-score。hard gates 已覆盖 required capability、retry/runtime exclusion、pin/deny provider/model、declared availability、locality/privacy、policy tags、authority scopes 与 malformed-policy fail closed。无 eligible route => `NoRouteAvailable`，不违规 fallback。

2026-09-07 的 E2E-28/34 closure 已把 `ResidentHealthJournal` 的动态运行 observation 接入 health-aware routing，并验证 bounded retry/fallback/reassignment 与 restart-safe reconciliation 的代表性路径。

不要再写“dynamic ResidentHealthJournal 尚未进入 router”。

## Durable dependency/readiness

`WorkItem.dependency_ids` 已 durable persistence。当前 substrate 的准确范围是：

- bounded dependency list；
- same Root / work thread / current plan validation；
- immutable dependency edges；
- readiness 由 durable Work truth **derived**，不持久化第二套 readiness truth；
- WorkerRun creation、coordinator cognition binding 与 child completion 都受 readiness gate；
- restart durability 与 fan-in；
- dangling/corrupt/cyclic/cross-root/cross-plan graph fail closed；
- dependency 不继承 authority/tool scope。

这不是 general-purpose DAG scheduler、recursive delegation、critical-path scheduler、resource-pool scheduler 或 generic dependency UX。

## Delegated user progress

Delegated progress 已从 durable delegated Work facts 投影到既有 `work_progress` contract 和 Resident UI，采用 bounded privacy-safe normalization，并覆盖 restart / steering。

它没有创建第二套 progress truth。当前状态是：

```text
CONNECTED + VERIFIED NARROW / PARTIAL UX
```

复杂 multi-workstream 展示、长期任务解释质量、面向普通用户的阻塞/完成依据表达仍需扩大。

## 代表性 E2E closure

### E2E-01 / E2E-02 / E2E-03 — Research & Information Work 1.0

2026-09-10 已验证并合并一个 bounded representative path。普通用户 research language 进入 active product Resident 后，复用 existing configured `WebResource` 做 multi-source search→extract；search candidate/snippet/provider answer 不被当作证据，只有 successfully extracted source-document content 进入 bounded Evidence Pack。

source identity 通过 canonical HTTP(S) URL 统一，保留 requested/observed URL、provider provenance、captured/published freshness 与 extraction failure；同 canonical source 通过多个 provider 只计一个独立 source，unexpected cross-host drift 以 identity mismatch 拒绝。跨来源冲突保持为 first-class structured conflict，不做静默平均/选择。

model synthesis 只产生 candidate claims。promoted finding/recommendation 必须携带 exact source ID + exact observed excerpt；numeric/date/price anchors 额外做本地支持检查，unsupported claim 被拒绝。all providers unavailable、no cognition 或少于两个独立 readable sources 都 block，不回退到 model memory。

ambiguity 只在 same-Work bounded context 下处理：唯一 referent 可直接继续；0/多个 plausible referents 必须先问用户且 zero search。research bundle 持久化在 existing Work ledger；restart 后可从 still-fresh evidence 继续 synthesis，不重复 acquisition。

E2E-02 只在唯一 attached Work workspace 写真实 UTF-8 Markdown；写后通过 existing Body + `observe_file_identity` fresh observe、exact reread、再次 identity compare 和 required section/source-ID/content verification 才完成。多个 plausible destination 时 fail closed 且 zero mutation。

实现通过 PR #246 squash merge 到 canonical `main`，merge SHA `f77e5f5d6b93af04f0bbb974dedea6529dbc9934`。最终 PR head `66526479b4e205a2123476375d5602b097748bb5` 的 applicable workflows 全绿：ZN CI #1784、Research E2E #14、Work Recovery #406、Managed Browser #344、Windows Interactive Desktop #363、Memory & Learned Behavior #41、E2E28-34 #120、E2E25 #55。

明确边界：这是 `VERIFIED NARROW / representative path closed`，不是 arbitrary-internet Deep Research、authenticated-browser research、arbitrary PDF/DOCX/XLSX/slides/multimedia research、general citation engine、knowledge graph/vector DB、recursive research swarm 或 cross-device research sync。

### E2E-09 / E2E-10 — Local Documents & Spreadsheet Work 1.0

2026-09-11 已验证并合并两个 bounded representative paths。实现 PR #248 final head 为 `37a7c2c975525ab01ba101ef6708d04bdd43a0b4`，已 squash merge 到 canonical `main`，merge SHA `22a0537ffe082a695355da42fde9a09d576916a8`。

E2E-09 从普通自然语言进入现有 Product Resident / Work / Body，在显式授权 source workspace 与 attached project workspace 内 bounded 枚举昨天 DOCX。只有唯一候选、唯一付款日期目标和当前 Work 中唯一已确认日期时才允许修改；真实 `python-docx` / WordprocessingML 解析后按 visible-text-to-run offsets 只修改 touched `Run.text`，不使用 `Paragraph.text` 重建段落。保存新 DOCX 后 reopen 并验证日期、结构/run formatting 和 source identity；源文件保持不变。两份 plausible DOCX、缺约定日期、0/多个付款日期、source drift 或 unsupported OOXML package 均 fail closed / zero mutation。

E2E-10 同样进入现有 Resident/Work/Body，但是 deterministic zero-model path：真实 XLSX 只在 one-sheet、rectangular scalar-data、唯一 exact `金额` / `Amount` header 范围内处理。duplicate 定义为 normalized read 后全部业务单元格完全相同，保留首行且稳定顺序；numeric amount cells 保持 numeric type/value，只把 `number_format` 统一成 `#,##0.00`。输出新 XLSX，源 byte identity 不变，并 reopen 验证 headers/rows/order/types/formats/other columns/source。多候选、金额列歧义、formula-heavy/complex workbook、source drift、output collision 均 fail closed。

exact-head applicable gates 全绿：Local Documents and Spreadsheet Work E2E #9、ZN CI #1796、Research and Information Work E2E #26、ZN Work Recovery E2E #416、ZN Managed Browser E2E #354、ZN Windows Interactive Desktop E2E #372、Memory and Learned Behavior E2E #53。Office workflow 中 Python 3.11/3.12/3.13 dependency+core compatibility、E2E-09、E2E-10、natural-file、Research Resident 和 Work Recovery regression 都实际 success，关键 steps 未 skip。

这两个 closure 没有增加 WordAgent/ExcelAgent/OfficeAgent、第二 Resident、Office GUI automation、第二 file truth 或 TXT package hack。依赖仅新增 `python-docx==1.2.0` 与 `openpyxl==3.1.5`。准确状态是 **VERIFIED NARROW / representative paths closed**，明确不是 Word complete、Excel complete、Office Suite complete，也不代表任意 DOCX/XLSX/PDF/PPT、宏、字段、嵌入对象、公式、表、图表、pivot/Power Query/external links 已支持。

### E2E-12 — Document Research Completion 1.0

2026-09-11 已验证一个 bounded representative path。普通用户自然语言进入同一 active Product Resident / Root Work / Body；只接受 exact Root Work attached workspace 内一个真实 `.docx`，第一版只处理 1–3 个显式 `【待补充：...】` placeholder。target identity 由 deterministic DOCX inspection 绑定，模型不能选择 document path、destination、Body action、tool、permission、mutation scope 或 completion truth。

Research 复用 existing configured `WebResource` search→extract 和已有 source identity / exact quote / anchor validation。Search snippet/provider answer 只作 discovery；successfully extracted source-document observations 才是 evidence，至少需要两个独立 readable sources。retrieved content 在 synthesis 前经过 deterministic instruction-like prompt-injection source screening；被拒绝来源保留 source ID/canonical URL/evidence fingerprint/reason provenance，但不进入 synthesis evidence pack。模型 synthesis 仍只是 candidate。

mutation 前还必须经过本地 safety gate：每个 replacement 至少由两个独立 prompt-safe extracted sources 支持，support quote 必须是该 source 的 exact observed substring，并对 replacement 中 price/date/percentage anchors 逐来源一致校验；此外 deterministic target-relevant source-anchor consistency 会扫描 readable evidence，所以即使模型返回合法 schema 和 `conflicts: []`，只要同目标存在矛盾 price/date/percentage anchor 也会以 `source_conflict` 阻断 mutation。两个 merge blocker 都有反例：模型漏报 `$99` vs `$129` source conflict，以及恶意 retrieved content 诱导出完全合法 schema replacement；两者在 `write_docx_completion_copy` 前停止，completed-copy mutation count 为 0。

成功路径只写新的 `-completed.docx`；source bytes 保持不变，run-aware span replacement 不使用 `Paragraph.text` 重建段落，并验证 non-target text、run topology、run formatting、all placeholders replaced。随后 fresh reopen source/destination，重新比较 identity、source target set、structure fingerprint 和 destination placeholder count；只有全部现实验证成立才把 Root Work 标记完成。unknown、insufficient prompt-safe sources、invalid schema/support、source/target drift、unsupported OOXML 和 output collision 都 all-or-nothing fail closed。

PR #250 implementation exact-head `65d5ec40f705f4e6e4c624b4a3287f27a949d8dc` 的 applicable workflows 最终全部 success：Document Research Completion E2E #5、ZN CI #1804、Research and Information Work E2E #34、Local Documents and Spreadsheet Work E2E #17、ZN Windows Interactive Desktop E2E #378、Memory and Learned Behavior E2E #61。E2E-12 #5 实际跑了 Python 3.11/3.12/3.13 dependency/core compatibility、merge-blocker counterexamples、real localhost HTTP + real DOCX E2E-12、E2E-01 和 E2E-09 regressions；ZN CI 的 Python core、Electron/TypeScript 和 source-boundary jobs 全部 success。

准确状态是 **VERIFIED NARROW / representative path closed**。这不代表 arbitrary DOCX completion、arbitrary document structures、arbitrary-internet Deep Research、authenticated-browser research、universal prompt-injection detection、general citation/reconciliation、Word complete 或 Office Suite complete。

### E2E-36 — uncertain side effect across restart

2026-09-10 已验证 bounded representative path。对 replay-sensitive mutation，Resident 在 dispatch 前先持久化 exact side-effect attempt；当 crash/restart 后结果仍不确定时继续 `user_decision_required`，不会把 timeout/中断解释成普通失败，也不会 blind replay。

显式控制只有两个 effect-resolution 结论：`effect_happened` 与 `retry_authorized`。前者把旧 attempt 记录为 audit-distinct `user_confirmed_effect`，不再次 dispatch mutation；后者记录为 `user_authorized_retry`，只终结该 exact 旧 attempt 并把 checkpoint 送回普通 `native_action`，下一次真实 dispatch 仍必须经过既有 `SideEffectAwareBody.act()` guard 并生成 fresh attempt。若 fresh attempt 再次变成 uncertain，旧授权不会继承。machine `verified_effect` / `verified_absent` 语义完全保留，不被人工判断冒充。

Store 在同一 SQLite transaction 中验证并更新 exact event/attempt/WorkingState recovery ownership；stale attempt、cross-thread/event、non-recovery 或 conflicting decision 均 fail closed 且不产生部分状态。Work control 与 `work_resolve_uncertain` RPC 只投影 bounded decision/attempt 信息，不暴露 action arguments。

PR-head representative evidence：Windows `ZN Work Recovery E2E` 实跑 `170/170 OK`，三条 restart E2E 分别证明 effect-happened no replay、retry 形成一个 fresh attempt/一个真实 effect、第二次 uncertain 不继承旧 authority；ZN Kernel 全量 core 回归也通过。merge 后 canonical main SHA / post-merge CI 必须重新查询，不把 PR head 当永久证据。

这不是 arbitrary third-party exactly-once guarantee，也不表示所有 outside-world side effect 都可以自动判断或恢复；它关闭的是 exact attempt-bound、Resident-owned、fail-closed 的代表性 restart/user-resolution 路径。

### E2E-35 — next-day product continuation/status-first inspection

2026-09-09 已验证 bounded representative path：用户从新的 UI ingress 只说 `昨天那个产品继续，先看看做到哪了。`，Resident 从 durable yesterday Work 唯一解析到原 WorkThread，复用同一 Root Work、current plan 和已有 Resident event；status projection 直接从 durable WorkItems/blockers/artifacts/delegated facts 派生，并对 attached workspace、Git 与最多 4 个 Work-owned artifacts 做 bounded fresh read-only Body Sense。

验收硬事实：`new_event_count=0`、`model_invocation_delta=0`、`worker_run_delta=0`、`mutation_action_delta=0`，Root/plan/WorkItem statuses 不变；happy path 能恢复 root goal、2 个 completed children、1 个 blocked child、2 个 artifacts，workspace/Git current evidence 存在。overnight 修改/删除 artifact 的对抗路径分别报告 `modified` / `missing` 并置 `drift_detected=true`，但 historical artifact evidence 与 completed Work truth 不被改写。

inspection 只追加 durable user inspection message，明确 `execution_permission=false`；Desktop 的 `inspection_complete` 结束的是这次只读 interaction，不 terminalize/finalize 原 Work。随后 exact current thread 的 `继续`/`那继续吧` 只在最新 durable message 为 inspection 时复用同一 active event，包括 restart 后；completed Work 可检查，但 bare replay 继续 fail closed；zero/multiple yesterday candidates fail closed。

PR-head 验证证据：`ZN Work Recovery E2E #336`、`E2E27-33 Real Steering Replan Acceptance #9`、`ZN CI #1703` 均为 success。merge 后 canonical main SHA / post-merge CI 必须重新查询，不把 PR head 当永久证据。

这只是 next-day status-first 的窄代表性 closure，不代表 arbitrary history search、多周/多月项目重建、跨设备 continuity、通用 project dashboard、general long-horizon orchestrator、general DAG scheduler 或 recursive multi-agent runtime 已完成。

### E2E-15 — bounded Windows unexpected-modal recovery

2026-09-09 已验证一个 bounded representative path：同一 Root Work 在真实 Desktop 任务中已经 grounded 原始 UIA target 后，真实 WinForms fixture 通过 `ShowDialog()` 打开同进程 blocking modal。Resident 不接收 harness 提供的 modal HWND/RuntimeId/action，而是从 fresh foreground + Win32 owner + UIA `IsModal` + parent `BlockedByModalWindow` 建立 exact modal authority，在 exact dialog subtree 中只允许唯一 deterministic safe defer/continue/close-notice action。

input 前必须 fresh revalidate exact dialog/Button authority；stale/ambiguous/cross-process/wrong-owner evidence fail closed。实际验收只 dispatch 一次 `稍后继续`，`立即更新` side effect 为 0；modal 消失后，只有 exact parent HWND/PID/process、visible/enabled/foreground、UIA `ReadyForUserInteraction` 都成立才恢复原 Work，旧 Desktop observation/action cycle 被丢弃并 fresh re-ground。旧/新 Edit RuntimeId 不同，最终 title `ZN 对应订单记录已打开` 独立证明原任务完成。

成功实跑中 `wait_for_input_idle=false`。它只保留为 telemetry，不参与 hard readiness gate；权威恢复证据来自 exact Win32/UIA identity、modal absence 和 parent readiness。该 closure 不包括 credentials/UAC/elevation/security/save-discard/delete/overwrite/file-picker/payment/purchase/installer/restart/update decision 或 arbitrary Windows dialogs；不允许 blind replay。

### E2E-24 — Browser + File + Desktop

2026-09-09 已关闭一个 bounded representative path：普通自然语言任务保持同一 Root Work，从已经登录且显式授权的 USER Browser 当前 tab 识别随机异常客户，选择唯一符合“昨天修改 + 名称语义”的 workspace 文件，写入一次并 fresh reread exact target；随后从当前 foreground app 重新建立 exact HWND/PID 与 UIA semantic authority，把同一客户记录标记待跟进一次，并用 fresh application title 独立证明最终状态。

对抗性覆盖包括：Desktop target 在 grounding 后被真实重建并产生新 RuntimeId，旧 UIA evidence 必须被拒绝后 fresh re-ground；两个同等候选文件时 fail closed，不能产生 file/desktop side effect。该 closure 不等于 arbitrary Browser/File/Desktop task、generic cross-surface workflow engine、general RPA 或 general DAG scheduler。

### E2E-29 — one model, multiple WorkerRuns

2026-09-06 已有真实模型代表性验收：一个实际 route 可连续服务隔离 research/coding/review WorkerRun；worker completion 不夺取 Root completion。

### E2E-30 / E2E-42 — route policy/privacy

按仓库当前 acceptance policy 已关闭。已验证 durable Work route/privacy policy、ModelRouter hard eligibility、route/provider provenance 与 guarded multiroute policy path。

该 closure 明确包含 **owner-approved environment waiver**：验收环境当时缺少第二个真实 provider family。因此：

```text
representative acceptance = closed
actual two-real-provider-family production evidence = not claimed
```

guarded two-provider acceptance 保留；真正配置两个 provider family 时要求无 skip / fail closed。

### E2E-28 / E2E-34 — supervision / dynamic health / restart

代表性真实路径已关闭：durable progress supervision、heartbeat/no-progress/stall detection、dynamic health-aware routing、bounded retry、policy-safe fallback/reassignment、restart reconciliation 和 no-replay recovery。

不代表无限期通用 long-task scheduler 已完成。

### E2E-27 / E2E-33 — steering / continuation

代表性真实路径已关闭：natural-language same-Work steering、current plan replanning、plan-version stale gating、old-worker result protection、restart continuation，以及 completed historical effect 不 replay。

不代表所有跨天/长期 continuity 场景都已解决。

### E2E-05 — authenticated research mutation

已有真实 USER Browser authenticated research -> persisted mutation representative closure。

### E2E-07 — causal USER Browser child tab

已有 task-scoped causal child-tab attribution、causal popup handling、authorization generation binding、fresh opener reread、child -> root return 与 unverified causal click no-replay 的真实 interactive representative closure。

### E2E-08 — OTP/MFA user-presence representative path

已验证：standard HTML `autocomplete="one-time-code"`、same explicitly authorized USER-browser tab、same authorization generation、same origin、`waiting_for_user` 非终态、用户手工完成 OTP、fresh Sense/re-ground 后同一 Work resume。

安全边界：ZN 不读取或自动输入 OTP；blocker 期间 model/Body 不继续；OTP 不进入 cognition、Work progress、Body history 或 durable SQLite；authorization generation 变化时 fail closed。

未支持：CAPTCHA solving、WebAuthn/passkey automation、cross-origin IdP handoff、password automation、payment-field automation。

## Browser Body V2 / Windows 当前边界

Browser 近期 verified narrow slices 包括：

- bounded `BrowserScene` sensing；
- tab lifecycle/history；
- exact BrowserScene focus/type/check/uncheck/navigation；
- managed causal popup attribution；
- authority-safe causal upload/download；
- stateless `target_absent_equals` command clicks；
- bounded stateful `aria-pressed` / `aria-expanded` / `aria-selected` clicks。

这些都坚持 exact current target、fresh revalidation、authority 和 independent postcondition。不要扩张成任意 popup/frame/dialog/site、general keyboard、OCR/visual fallback 或完整 web automation。

Windows 当前已有 Machine Capability / Application Awareness V1、exact admitted existing-window activation，以及 E2E-15 bounded unexpected-modal recovery。应用 inventory/identity、Installed/Running/Window/Foreground facts、identity-bound launch、fresh process/window verification、Resident-admitted app/HWND/PID revalidation 都已有代表性验证；blocking modal 代表性路径还增加了 exact direct-owner/UIA modal semantics、single safe action、non-replay 和 fresh re-ground。不要扩张成全 Windows application lifecycle、任意窗口拓扑或 arbitrary dialog automation。

## 当前主要剩余产品缺口

下面是仍然真实存在的“广度/产品体验”缺口，不再把已经关闭的代表性 E2E 当新开发任务：

1. **Research breadth**：E2E-01/02/03 与 E2E-12 bounded closures 之外的 authenticated research、PDF/复杂 source extraction、citation UX、更多 surface 组合和更长周期 evidence refresh。
2. **Local Office breadth**：E2E-09/10/12 bounded closures 之外的复杂 DOCX/XLSX 结构、更广文档/表格操作、Browser/Research/Desktop 与 Office 的更广组合；不得把这些 closures 扩写成 Word complete / Excel complete / Office Suite complete。
3. **Cross-surface real tasks**：在 E2E-24 bounded closure 之外，Browser + Desktop + File/Terminal/Application 更复杂任务的连续完成率和 recovery。
4. **Browser/User Browser breadth**：真实站点变化、复杂 frame/dialog/navigation、更多授权/用户在场边界；E2E-08 只覆盖代表性 OTP path。
5. **Long-horizon experience**：在现有 E2E-27/33/35 continuity、E2E-28/34 supervision substrate 上扩大超过 bounded yesterday reference 的跨天/长周期、多 workstream 真实使用与 progress/explanation UX。
6. **Windows/application breadth**：在 E2E-15 bounded same-process safe modal closure 和当前 machine/application substrate 之外，由真实 E2E 暴露的应用语义、跨进程/system dialog、复杂窗口/系统能力缺口。
7. **Upgrade continuity**：installed N -> N+1 的身份、数据、Work、rollback/uncertain-effect 连续性仍未 product-close。

如果 current main 不能从真实 E2E 唯一确定下一开发任务，应按真实用户任务阻塞程度选择，而不是凭空新增 roadmap。

## 不要误判为完成

当前实现不等于：

- arbitrary-internet Deep Research / authenticated-browser research / general citation engine；
- arbitrary DOCX completion / universal prompt-injection defense；
- Word complete / Excel complete / Office Suite complete / arbitrary Office automation；
- 完整 multi-agent orchestration 平台；
- general-purpose DAG scheduler / recursive delegation；
- 所有 MFA；
- 任意网页或任意 popup/frame/dialog；
- arbitrary Windows dialog recovery、UAC/credential/security/save-discard/file-picker/payment/installer/update decisions；
- arbitrary Browser/File/Desktop automation 或 general RPA；
- arbitrary third-party exactly-once semantics 或所有 outside-world side effect 自动恢复；
- 完整 DLP / OS sandbox；
- 所有长期任务已解决；
- arbitrary history search / 多周多月 project reconstruction / cross-device continuity；
- 双真实 provider family 已有完整生产证据；
- Memory、credential、installer/updater/release trust 已因此获得自动扩张授权。

## 判断产品完成的标准

代码、单测、CI、installer、provider、worker 或模型数量都不是 product closure。真正要看：

```text
普通用户给正常人类任务
-> ZN 保持 Root Work
-> Sense 当前电脑状态
-> 判断 direct / delegated
-> 选择 cognition + tools + authority + verification
-> 状态变化/失败/用户改方向后重新观察和判断
-> 保留 authority / fresh evidence / non-replay
-> 独立验证关键结果和最终目标
-> 中断、重启、跨天后在足够当前证据下继续
```

每次只补高价值真实 E2E 真正缺的能力，不回到“先造完整 multi-agent/router/framework，再很久以后验证用户任务”的路线。

<!-- memory-learned-behavior-1.0-closure -->
## 2026-09-10 — Memory & Learned Behavior 1.0

Status: **VERIFIED NARROW / representative path closed** for E2E-37, E2E-38 and E2E-39.

Implementation facts:

- active construction in `runtime/python/zn_agent/core/provider_bridge.py` now composes `MemoryLearnedBehaviorResidentRuntime` over the existing current Resident inheritance chain;
- `runtime/python/zn_agent/core/learned_behavior_resident.py` adds bounded provenance-bearing prior working context and one L4 fast-path policy; it does not add a second planner, memory database, action registry, capability registry or skill executor;
- `runtime/python/zn_agent/core/procedural_tendency.py` now includes the already-privacy-safe `workdir_fingerprint` in compatibility identity when present, separating same-procedure competence between projects while still allowing different targets inside one project to reinforce each other;
- the maturity threshold remains deterministic and existing: one success cannot create a candidate, two distinct supports form `candidate`, three can become `supported`, and four distinct supports with reliability >= 0.80 can become `practiced`; model-only text and unverified actions still have no positive learning authority;
- the representative L4 path may skip one `native_deliberation` pulse only after current Investigation has already formed current safe intents and existing applicability checks select a `practiced` tendency;
- existing current Sense, user/event authority, Body arguments, side-effect attempt ownership, anti-replay and independent postcondition verification remain authoritative;
- existing durable contradicted `VerifiedExperience` aggregation supplies L5 downgrade/inhibition/relearning: repeated contradiction can inhibit, restart preserves it, and later verified events must rebuild reliability rather than one success immediately restoring maturity.

Acceptance coverage:

- `tests/zn_agent/core/test_learned_behavior_resident.py`
- `tests/zn_agent/core/test_project_scoped_procedural_learning.py`
- `tests/zn_agent/e2e/test_e2e37_preferred_working_style.py`
- `tests/zn_agent/e2e/test_e2e38_learned_verified_workflow.py`
- `tests/zn_agent/e2e/test_e2e39_learned_path_drift.py`
- `.github/workflows/memory-learned-behavior-e2e.yml`

No destructive `StructuredMemory` or identity migration was required. Provenance for this trust-bearing slice comes from the existing durable verified-experience store; `StructuredMemory` is not upgraded into an action-authority source.

Explicit remaining boundary: no general multi-step procedure engine, general personal memory UI, cross-device memory, arbitrary skill code generation, or universal provider-independent open-ended reasoning is claimed.

<!-- e2e11-browser-spreadsheet-closure -->
## 2026-09-11 — E2E-11 Browser data into spreadsheet

Status: **VERIFIED NARROW / CLOSED representative path on PR #251 exact-head `f2d408a3980ce2f862503aa77faf021c4c5b1050`; not merged to `main` yet**.

The implemented path reuses the existing Product Resident / Root Work / Body / BrowserScene / file identity / spreadsheet owners. It requires exact `browser_session_id`, `page_id`, attached `workspace_path` and explicit source `spreadsheet_path`; source discovery or guessing is not allowed. The current page must expose exactly one main-frame simple table. Table sensing is structured and bounded (64 total rows including header, 32 cells per row, 512 characters per cell), exports no HTML/page-wide text, and rejects stale/detached evidence, multiple tables, spans, malformed/partial materialization and ARIA row/column mismatches.

The first row is the exact ordered header and later rows are rectangular string cells. Before mutation the Browser table is freshly re-observed and fingerprint-matched. XLSX append-copy is independently conservative: one worksheet, nonempty unique stable string headers, header-only or rectangular scalar data; formulas, macros, merges, tables, charts/drawings, pivots, external links and other complex structures fail closed. Browser values are appended as strings with no type inference. Source identity must remain exact and unchanged; destination is a new `<source-stem>-webdata.xlsx`, never overwritten, temp-saved/reopened/verified and then freshly reopened again after publish.

Durable Work evidence uses `browser_spreadsheet_import:v1`; success requires fresh Browser + source XLSX + destination XLSX verification and `model_invocations == 0`. Real Chromium + real openpyxl acceptance is green on ZN Managed Browser E2E #359, including the explicit E2E-11 step. The same exact head also passed Local Documents and Spreadsheet Work #27, ZN CI #1814, Research #44, E2E05 #65, E2E06 #8, Document Research #15, Memory #71 and Windows Interactive #388.

This section supersedes earlier statements in this file that omit E2E-11 from closed representative paths. It does not claim arbitrary website tables, virtualized grids, multi-table choice, complex workbook mutation, Excel complete, Office Suite complete or general Browser→Office automation. PR #251 remains open and unmerged, so no canonical merge SHA is claimed.

<!-- e2e11-browser-spreadsheet-repair-closure -->
## 2026-09-12 — E2E-11 merge-blocker repair acceptance

This repair section supersedes every earlier E2E-11 “current exact-head” reference in this file. The earlier `f2d408a3980ce2f862503aa77faf021c4c5b1050` is historical pre-review evidence only.

Status: **VERIFIED NARROW / CLOSED representative path on repair implementation checkpoint `9ac5f403f17d85834e3a300e1065fc85f5747cb2`; PR #251 remains open and unmerged**.

The repair closes the three pre-merge findings without broadening scope. `observe_scene_table()` accepts only a session whose `BrowserSessionIdentity.plane` is `MANAGED`, and the Product behavior independently requires both a MANAGED adapter plane and exact MANAGED session plane before Browser capture; USER Browser inheritance therefore grants no E2E-11 authority. Simple-table extraction requires `checkVisibility()`-backed layout visibility for the table and every materialized row/cell and separately rejects ancestor `aria-hidden=true`; hidden regions fail closed, not silently filtered. XLSX append-copy inspection uses `rich_text=True` and rejects `CellRichText` as unsupported, avoiding lossy flattening while leaving E2E-10’s loader semantics unchanged.

Repair-checkpoint acceptance is all green: ZN Managed Browser E2E #373 with the explicit non-skipped E2E-11 Chromium→XLSX step, Local Documents and Spreadsheet Work #41, ZN CI #1828, Research #58, E2E05 #79, E2E06 #22, Document Research #29, Memory #85 and Windows Interactive #402. Real Chromium covers hidden-layout and ancestor-`aria-hidden` rows; openpyxl 3.1.5 rich-text rejection is exercised across Python 3.11/3.12/3.13. Source preservation, no-overwrite output, fresh Browser/source/destination verification, browser/source drift protection, literal-string append and zero-model completion remain intact.

The subsequent documentation-only synchronization creates a later live PR head; merge readiness must be judged from that head’s applicable CI. The repair checkpoint is durable evidence, not a self-referential permanent HEAD. No canonical merge SHA is claimed. USER Browser table import, arbitrary website tables, multi-table guessing, grids/treegrids, pagination/virtualization, cross-origin iframe tables, complex Excel, rich-text support and general Office automation remain outside this closure.
