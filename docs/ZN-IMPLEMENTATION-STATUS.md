# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Current core direction: [`ZN-NEXT-PHASE.md`](ZN-NEXT-PHASE.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit M10 promotion milestone.

## 1. Current development checkpoint — 2026-08-23

The active development mainline is now:

```text
durable ZN Self
+ mature complex-task execution depth
+ reality-based verification
```

Pure UI/desktop polish is paused. M8/release remains a bounded continuity/release lane.

The active product boundary is ZN-owned across resident runtime, cognition resources, local filesystem/process/terminal/PTTY body, web sensing, communication lifecycle, Electron main/preload/protocol/workbench, runtime distribution and formal desktop package identity.

The resident already has persistent Self/life, Situation/Thought/Will, nervous memory/reconsolidation, durable events/working state, multi-pulse Investigation, native Action/Body movement, bounded external cognition and zero-model continuity.

The remaining gap is practical execution depth: the same resident must sustain unfamiliar multi-step work, recover from contradictions, broaden its Body/Senses, and verify the original goal from current reality rather than treating a successful model/tool/action call as completion.

## 2. Verified core execution spine

### 2.1 Structured read-only Git repository sense

Source includes:

```text
168579604157467bb2384f385849c621ca66cefe  feat: strengthen native Git repository sense
59957637a6840a6ce54e10b67ee5dc7bc0623867  test: isolate Git sense from resident sqlite files
```

Final first-slice CI state:

```text
47ccd5601462641c50c16ec76f2a05085a33f9f3
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32612456040
```

The active embodied path observes Git through `NativeBody.git_state` and returns structured repository evidence:

- repository root;
- branch;
- full/short HEAD;
- detached state;
- upstream;
- ahead/behind;
- dirty state;
- unique changed paths;
- staged / unstaged / untracked / conflicted paths and counts;
- bounded porcelain status.

Embodied Investigation consumes this Body contract directly, including `changed_paths`.

This is read-only repository sense. General Git mutation and GitHub maintenance are not yet claimed.

### 2.2 Action success no longer automatically means task success

Source/test state:

```text
7a30baea6b4a2471479152e2843c50c0c7279997  feat: verify body postconditions before task completion
66f0fecc21b3cd7303c1f01b257095704f3454f4  feat: make post-action verification a resident thought stage
47ccd5601462641c50c16ec76f2a05085a33f9f3  test: require reality verification after native writes
```

CI: run `32612456040`, Kernel/Python and Electron/TypeScript both success.

For exact non-append text mutation:

```text
Investigation
→ NativeActionIntent(write_text)
→ Body write succeeds
→ event remains active
→ durable native_verification stage
→ verify_action Thought
→ Body re-reads current reality
→ compare exact requested text state
→ verified only then complete
```

The verification stage survives resident restart. A contradicted postcondition returns to Investigation and prevents blind replay of the identical movement.

### 2.3 Explicit independent command postconditions

Source/test state:

```text
5cc0b1bccca976a8c635fbf3ddd7f95912a4cdc6  feat: verify explicit command postconditions
8a661a376bd0d24dc2eea5dbe4187a159a8f4df1  feat: surface verification evidence in resident thought
f280c8f68af69dfc2ac10b94d8d83726c10aa14e  test: fix command verification shell contract
```

Real CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32621596489
```

An event may declare a structured `expected_outcome` command check. The primary command returning successfully is action evidence only. The resident later runs an independent verification command through its own Body and compares observed exit code/output against the expected state.

Verified behavior includes:

- expected exit code;
- optional required output fragments;
- verification workdir/timeout/output bounds;
- restart continuity between primary action and verification;
- failed verification returns to native Investigation;
- identical primary action is not blindly replayed;
- verification contradiction enters the next `CognitiveSituation` / Thought immediately.

Generic shell exit `0` still does **not** prove an arbitrary high-level goal.

### 2.4 Compact durable task execution context

Source/test state:

```text
470a8549901fd4201556188ea8276f83ebdb6033  feat: persist compact task execution context
969e07125db396f3f949aaa4d846fb5f8a0fd6bf  feat: bring execution context into situation
aaa6fa55c5c4e1968006f618a37260cb4f41675a  test: cover compact execution context
```

Real CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32621878503
```

Active `WorkingState` now keeps one bounded `execution_context` for the current event. It is deliberately **not** a planner tree or growing task database.

The compact context contains:

```text
goal
stage
current_gap
expected_outcome summary
current_action summary
latest_verification summary
verification_history (bounded to 8)
updated_at
```

The context survives resident restart and enters `CognitiveSituation` / Thought, so the same Self explicitly retains the current goal, blocking gap and completion criterion across pulses.

When a genuinely different action begins, the old active verification verdict is removed from the current slot and archived into bounded verification history. This prevents stale failure evidence from masquerading as current reality while preserving prior evidence for later reasoning.

This closes the earlier active-work-state gap. It does **not** yet provide a first-class completed-task `VerificationReport`/audit object after WorkingState returns to idle.

## 3. Current core capability boundary

### Verified foundations

- persistent Self / zero-model resident life;
- durable event + `WorkingState` continuity;
- Situation / Thought / Will continuity;
- nervous memory, schemas and reality-gated reconsolidation;
- multi-pulse native Investigation with retained hypotheses/evidence/facts;
- native Action intents and Body action results;
- failed Body action evidence;
- structured read-only Git repository sense;
- exact text postcondition verification;
- explicit independent command postcondition verification;
- verification contradiction immediately affects Situation/Thought;
- compact current-event execution context with goal/gap/expected outcome/current action/latest verification/bounded history;
- bounded external cognition returning as input to ZN rather than owning the resident loop;
- ZN-owned local process/terminal/PTTY and web search/extract paths;
- persistent work/thread/workspace/active-run state;
- resident-owned provider/settings/channel lifecycle.

### Still PARTIAL / MISSING

- resident-owned derivation and maintenance of reliable high-level task postconditions;
- multi-step execution that can choose genuinely different tactics over many actions without becoming a model-owned planner;
- robust bounded failed-action history tied to evidence changes, so A → B → A retry loops cannot bypass a single last-failure guard;
- first-class durable completed-task verification/audit evidence;
- broader failure recovery after verification contradiction;
- safe Git mutation + diff/test/reality verification;
- GitHub repository/PR/CI resident-owned read sense;
- clean browser Body/Senses seam;
- mature visual + mouse/keyboard application control;
- real complex-task benchmark suite;
- SM1+ self-maintenance implementation.

## 4. Product/workbench state

### Resident work loop

`ResidentWorkLedger` owns durable threads/messages, workspace association, active work linkage/progress and bounded contextual file/diff/terminal artifacts beside kernel state. Renderer/localStorage is not authority.

Status: **M6 PARTIAL; core execution mainline active**.

### External cognition/settings

ZN-native OpenAI-compatible, Anthropic and Gemini resource adapters plus resident-owned provider/credential configuration remain active. Missing credentials degrade cognition rather than killing the resident.

Status: **M2 complete for active main provider families**.

### Local Body

ZN-owned filesystem/process/terminal/PTTY paths are active. Exact text and explicit command postcondition verification are CI-verified.

Status: **active; practical breadth and long-horizon composition remain incomplete**.

### Web/world sense

ZN-owned search/extract providers and URL/network safety are active.

Browser automation is not yet owned by a clean ZN resident seam.

### Visual sense

Resident-owned visual sensing foundations exist and are tested, including persistence and reality-gated neural use. Mature screen understanding + mouse/keyboard computer-use completion is not claimed.

### Communication

Resident-owned channel lifecycle and Telegram text/inbound media are active. Outbound attachment transport remains pending explicit resident-owned egress nomination; arbitrary local paths are not upload authority.

### Desktop/UI

Independent ZN Electron main, preload, renderer/workbench and `zn://` are active. M4 is complete and M5/M6 are materially advanced.

Pure UI polish is paused during the core-first phase.

## 5. Runtime/package/release evidence

### M1 runtime ownership

Status: **COMPLETE for active packaged resident path**.

The independent `runtime/python` distribution is `znagent`, installed package `zn_agent`, resident entrypoint `zn-resident`. Packaged runtime rejects inherited `hermes_cli` and can boot zero-model.

### M7 formal artifact ownership

Status: **ARTIFACT SHAPE VERIFIED** for currently exercised targets:

```text
Linux   x86_64   AppImage / deb / rpm
Windows x64      NSIS / MSI
macOS   arm64    DMG / ZIP
```

Key real evidence:

```text
Linux artifact source   6219eaa61f6c444feb96864e149f886752b00ffe
Linux integration       46685b66ff1381cb0b41b1e0564cc62ca5e34467
Windows source          2e3cdb0ac893feca86325e19a058c455c906bfd7
Windows smoke run       32590239803
macOS source            518d233eafa39b2d12f2de5835a8c8c1ab7529ab
macOS smoke run         32591343670
```

Artifacts preserve ZN product/protocol/runtime identity and independently bootable zero-model `zn_agent` runtime.

This does not imply signing/notarization or complete release readiness.

### M8 installed Linux + source continuity evidence

Status: **IN PROGRESS / bounded release lane**.

Verified Linux clean install:

```text
source                    6e980ac2fe46a0680751dd55711ac53749419a14
ZN Linux Clean Install    success
run                       32591603017
fresh runner              Ubuntu 24.04.4 LTS
```

The formal deb was handed artifact-only to a fresh runner, installed under `/opt/ZN`, preserved ZN desktop/protocol identity and booted its embedded zero-model resident without source checkout/system Python.

Verified installed Linux autostart:

```text
source                    6cc8becea3d97eea09c0887cd5c70612fc9ee573
normal CI run             32593886005
ZN Linux Autostart Smoke  success
run                       32593886026
```

The installed packaged resident can install an enabled systemd user login entry, start, stop gracefully with endpoint/lease cleanup and return through `default.target`.

Verified source-level N → N+1 continuity:

```text
eb1d1874f1d24dae9ceb74635886615368166ce1  defer handoff for queued work
f0a829b618d931f6f5e40bf314fda592783db6c9  side-by-side runtimes
91a6b500274e0cc0f64be54839e51f5c377a1c16  idle resident continuity
b79c94c67f5ef19af8c0a8e4ba0d9e9877a400f3  align continuity with work snapshot
normal CI run                              32596442626
```

N/N+1 can coexist under one ZN home; queued/claimed work blocks false-idle handoff; idle process replacement preserves living-self identity fields and durable work history.

Still unverified as separate release gates:

- full installed Electron/application updater N → N+1 scenario;
- Windows/macOS clean-install/login continuity for intended release matrix;
- signing/notarization when operationally configured;
- additional architectures if required by eventual release matrix.

## 6. Ownership/behavior contracts currently protected

Among other regressions, current tests protect:

```text
agent/kernel must not import hermes_cli or run_agent
runtime distribution identifies as znagent
packaged runtime rejects hermes_cli
zero-model resident boot succeeds
external model success returns as bounded cognition before resident acceptance
resident event/investigation/action state survives restart
failed body actions return as evidence instead of blind retry
NativeBody Git sense returns structured repository state
changed-path answers use active embodied Git evidence
successful write movement does not imply task completion
write postconditions survive restart and are independently re-observed
contradicted write postconditions return to investigation
explicit command expected_outcome is independently verified
command verification survives restart without replaying primary command
failed command verification becomes immediate Situation/Thought evidence
compact execution context survives restart and remains bounded
new action cycles archive old verification without current-state pollution
provider secrets/settings remain resident-owned and sanitized
work/thread/workspace/progress remain resident authority
ZN desktop main/preload/renderer do not delegate to inherited control planes
formal package metadata/protocol identify ZN only
real packaged runtime boots across exercised Linux/Windows/macOS artifacts
fresh Linux install/autostart continuity works from packaged artifacts
queued resident work prevents false-idle runtime handoff
idle N → N+1 preserves living-self/work continuity
```

## 7. Milestone snapshot

```text
M0  blueprint/reset ownership contract                     COMPLETE
M1  independent ZN Python resident runtime                 COMPLETE for active packaged path
M2  ZN-native bounded provider cognition                   COMPLETE for active main provider families
M3  ZN-owned local terminal + web paths                    COMPLETE for active local/web paths
M4  independent Electron main + preload + zn://            COMPLETE
M5  content-first ZN workbench                             IN PROGRESS; pure polish paused
M6  resident work/artifact/execution loop                  PARTIAL; core execution mainline active
M7  formal packaging around owned product                  ARTIFACT SHAPE VERIFIED on exercised targets
M8  clean-machine/continuity multi-OS validation           IN PROGRESS; bounded release lane
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## 8. Immediate next development sequence

1. continue the resident execution spine; do not return to cosmetic UI;
2. replace the single last-failed-action guard with bounded failure records tied to the evidence state, preventing A → B → A retry loops while still permitting a retry after genuinely new evidence;
3. extend verification-failure recovery so new evidence can produce a genuinely different next action rather than only truthful failure;
4. then build conservative practical Git mutation behind ZN Body with workspace/branch/diff/test/reality-verification boundaries;
5. add GitHub repository/PR/CI read-only resident sense before any remote write capability;
6. establish browser interaction only through a clean ZN-owned Body/Senses seam;
7. drive breadth using real benchmark tasks such as:

```text
unfamiliar repo + failing CI
→ inspect repository/Git/CI
→ identify gap
→ inspect code/tests/logs
→ form hypothesis
→ modify through ZN Body
→ run tests
→ observe result
→ verify diff/repository state
→ revise if contradicted
→ report concrete evidence
```

8. keep remaining M8 updater/multi-OS/signing work explicit as bounded release debt and fix it when it exposes a real continuity/security/data-integrity problem.

The architecture driver remains:

> **The same persistent ZN Self must be able to finish hard work and prove from current reality that it is finished.**
