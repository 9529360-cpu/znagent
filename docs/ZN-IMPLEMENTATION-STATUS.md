# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Current core direction: [`ZN-NEXT-PHASE.md`](ZN-NEXT-PHASE.md)
>
> Memory/learning architecture: [`ZN-MEMORY-LEARNING.md`](ZN-MEMORY-LEARNING.md)
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
+ resident-owned learning / procedural competence
```

Pure UI/desktop polish is paused. M8/release remains a bounded continuity/release lane.

The resident already owns persistent Self/life, Situation/Thought/Will, nervous memory/reconsolidation, durable events/working state, multi-pulse Investigation, native Action/Body movement, bounded external cognition and zero-model continuity.

The execution spine now also has structured read-only Git sense, exact text and explicit command postcondition verification, compact durable execution context, evidence-bound failed-action history, bounded restart-safe `VerifiedExperience` records grounded only in independent Body verification, transparent L2 candidate-procedural-tendency aggregation over repeated compatible episodes, and the first read-only L3 current-reality applicability evaluator.

The memory/learning direction now has CI-verified L1, L2 and the first observational L3 slice. Repeated compatible independently verified events can form a non-executable candidate with explicit support, contradiction, reliability, maturity/inhibition state and privacy-safe applicability features. Current Investigation evidence can now classify such a candidate as `supported`, `mismatch` or `untested`; request shape alone cannot make it supported, incomplete evidence fails closed, and the result is surfaced into Situation/Thought without moving Body.

This still does **not** mean candidate tendencies can influence Body action. The next learning gap is bounded low-risk action influence through existing ZN-owned structured action formation, with mismatch/untested candidates retaining zero authority.

The active transition is therefore:

```text
verified lived experience
→ repeated compatible evidence
→ candidate resident-owned tendency
→ current Situation applicability test        FIRST READ-ONLY SLICE VERIFIED
→ reality-gated action influence              NEXT
→ mature procedural competence
→ familiar low-latency execution
→ prediction-error interrupt / relearning
```

Stronger alternative-action recovery remains important, but it should become an early consumer of this learning path rather than a disconnected tactic generator.

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

The active embodied path observes Git through `NativeBody.git_state` and returns structured repository evidence including root, branch, HEAD, upstream/ahead/behind, dirty state, staged/unstaged/untracked/conflicted paths and bounded porcelain status.

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

Verified behavior includes expected exit code, optional required output fragments, workdir/timeout/output bounds, restart continuity, contradiction recovery to Investigation, and immediate verification evidence in Situation/Thought.

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

Active `WorkingState` keeps one bounded `execution_context` for the current event. It is deliberately **not** a planner tree or growing task database.

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

The context survives resident restart and enters `CognitiveSituation` / Thought. When a genuinely different action begins, the old active verification verdict is removed from the current slot and archived into bounded history.

### 2.5 Evidence-bound failed-action history

Final code/test state for this slice:

```text
227c26a3c47389a842967bee1efc7e28cba5b9a5  feat: bind failed actions to investigation evidence
8bd88ac55d6c0bf6a26bd98c3294f6d15f420e81  fix: do not complete on blocked failed action
82952bf07904bba11d60f4f39c0e2f4e52226125  test: reject cognitive false completion after failure
2010ff8ab6d056cee11e6596dfc9e263cc2455b9  test: assert evidence ledger after text contradiction
23ce3b42aad2d730afae4d60eb6af5d5b4bd1399  test: assert evidence ledger after command contradiction
```

Real CI for final code/test SHA `23ce3b42aad2d730afae4d60eb6af5d5b4bd1399`:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32635668910
```

The final implementation lives inside the existing `EmbodiedResidentRuntime`; the active product constructor remains the existing `WorldAwareTransferResidentRuntime` chain. No extra planner/manager/final-runtime shim was retained.

`WorkingState.data.native_action_failure_records` is now a bounded resident execution record rather than one last-failure slot. Current behavior:

- each failed movement stores a SHA-256 action signature hash, action kind, evidence fingerprint, failure source/summary and timestamp;
- records are bounded to 16 and same-action/same-evidence duplicates are coalesced;
- the evidence fingerprint is derived from stable `Investigation.facts`, not round count or observation clocks;
- volatile timestamp fields are excluded, so merely re-running a probe without new facts does not unlock the action;
- A failing, then B failing, does not make A eligible again while reality evidence is unchanged;
- substantively revised Investigation facts create a new evidence version and may requalify a prior movement;
- records survive resident restart;
- old persisted `native_action_failure_signature` state has a one-time read migration path, but new execution does not use that single slot as authority;
- compact `execution_context.failed_actions` exposes total/current-evidence counts and bounded summaries without copying full commands/content;
- external cognition text is not reality evidence and cannot by itself unlock a failed action;
- if accepted external cognition still leads to the same movement contradicted by unchanged reality, the event now fails truthfully instead of falling through to a false `complete` result.

This closes the A → B → A blind-replay gap and one false-completion path. It does **not** yet mean ZN can always generate a useful alternative tactic after a movement is blocked.

### 2.6 First independently verified experience record

Final code/test state for this first L1 slice:

```text
ee287a41873eb9340406aa95a56961b42127296c  feat: add deterministic body result semantics
1130148205471a14c964cc080ea481d6f72c3a93  feat: add bounded verified experience store
b04a35356181abb86eb228cc7f963ebd01ca1653  feat: record independently verified resident experience
20a3ffa9236e9de4279ef64e766d02f8cdce5988  fix: treat known swallowed failures as masked success
474f636cd8dedeeb23c5997ad45e07a7d224136f  fix: fingerprint capability domains in learned episodes
80292975264df35ff3a999ed32c7973cdd3514f5  test: cover private capability labels in learning
```

Real CI for final code/test SHA `80292975264df35ff3a999ed32c7973cdd3514f5`:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32639405457
```

The active embodied verification path now creates one resident-owned `VerifiedExperience` only after an independent Body observation actually occurs. The record connects stable Situation evidence, goal/gap fingerprints, concrete action signature, privacy-safe expected-outcome features, normalized primary result features, independent verification features and a `verified` or `contradicted` verdict.

Current guarantees:

- exact text verification and explicit command verification can create causal experience records;
- Body return success alone does not create a record;
- generic command exit `0` without a postcondition does not create a record;
- model/reported text without an independent observation cannot create a record;
- unsupported verification contracts do not create a record;
- contradicted postconditions create negative experience rather than being discarded;
- verification commands with shell-masked success plus deterministic visible failure evidence cannot become positive learning;
- normalized terminal semantics include bounded failure categories plus timeout/not-executable/killed/nonzero-exit classes;
- raw task/gap text, commands, verification commands, paths/workdirs, output text/output fragments and caller-supplied capability labels are not persisted in the learning episode; stable fingerprints/counts/categories are retained instead;
- records share the resident kernel SQLite lifecycle, survive restart, deduplicate deterministically and are bounded to 2048;
- L2-aware retention now reserves recent contradiction evidence and, when capacity permits, the two distinct verified events needed to preserve an already-supported candidate before singleton representatives and generic recency;
- the learning store is distinct from `native_action_failure_records`; the latter remains immediate execution anti-replay state.

This is the first verified causal episode substrate, not procedural competence.

### 2.7 Transparent candidate procedural tendency aggregation

Final code/test state for this first L2 slice:

```text
3f00dbc884a899626fba7d32c6f2130a0f11ce0d  feat: derive candidate procedural tendencies
3c989a077152a5c28757ff1891fb393ebe0d10bb  feat: expose bounded procedural candidate retrieval
f0f5ba49d3d4b9a152a05e9d3e0f056667351162  fix: retain repeated support for procedural candidates
25ff0ada9efc8e8d830d085856edca7ea772a696  test: preserve candidate support under retention
```

Real CI for final code/test SHA `25ff0ada9efc8e8d830d085856edca7ea772a696`:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32640409344
```

`VerifiedExperienceStore.candidate_tendencies()` now derives a bounded non-executable procedural view from retained L1 episodes. The first transparent baseline deliberately stays simple and inspectable:

- one verified event never creates a candidate;
- duplicate records from the same event cannot satisfy the repetition threshold;
- at least two distinct independently verified events in one compatibility group are required;
- compatibility uses only L1 privacy-safe group/domain/action/expected-result/effect/failure features;
- support and contradiction are counted separately and a reliability ratio remains visible;
- repeated support progresses only through candidate-level states (`candidate`, `supported`, `practiced`); no state is called mature/procedural yet;
- contradiction can move a tendency to `contested`; repeated/recent contradiction can mark it `inhibited`;
- applicability remains descriptive only: stable fingerprints and variant counts for target/workdir/verification signature plus goal/situation/action-signature diversity;
- raw command, action args, path, content, task text, model text and caller capability labels are not copied into the candidate;
- candidate evidence references and recent verdict history are bounded;
- candidates are derived from retained causal evidence, so restart reconstructs the same candidate ID/state without a second mutable skill database;
- the implementation does **not** connect candidates to `_deliberation_step`, `NativeBody`, capability loading or nervous-system `activate()`.

This closes the first L2 aggregation/retrieval slice only. A candidate, even `practiced`, currently has zero authority to move the Body.

### 2.8 Read-only current-reality procedural applicability

Final code/test state for the first L3 slice:

```text
cf2c270f3619e566cd0c07f81e6a2c5f59697cad  feat: add reality-gated procedural applicability
87d5d9a6a46b0b9f94061502bbcb24752e9643f7  feat: surface procedural applicability from investigation
2404825f971b2deb252db16ac5ae3ecded17a5db  feat: expose procedural applicability to thought
4300d0bc7cdca615d75ed362156dd5bf8dda787e  fix: derive applicability from durable reality evidence
f36db4de98c75f200459f9a0a62d05509bd12e29  fix: fail closed on untested applicability fields
ad415dc897c7f3d5bbbaab6d8201a4ce660e4a1a  test: keep incomplete applicability contracts untested
f876eb5641c82f3cab79c5ba2b7f0e5deb55dbc6  test: diagnose resident applicability at reality boundary
202b69e947db6c178d821c27e51fc1e61a90ce82  fix: preserve applicability in active world investigator
```

Real CI for final code/test SHA `202b69e947db6c178d821c27e51fc1e61a90ce82`:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32642408966
```

The first L3 implementation is intentionally read-only. `procedural_applicability.py` compares an L2 candidate with current structured task context plus independently observed Investigation facts and returns only `supported`, `mismatch` or `untested`.

Current guarantees:

- task/request structure can disqualify or compare a candidate but cannot by itself prove applicability;
- `supported` requires at least one stable candidate reality anchor to be independently observed now, and every compared contract field must be tested;
- matching stable filesystem target can be supported only after the target appears in current `paths` observation;
- matching command/workdir applicability can be supported only after current Git observation confirms the stable repository root and the current command verification contract is complete and compatible;
- a different target/workdir/verification contract is a `mismatch`;
- missing evidence or incomplete contract is `untested`, including the case where a repository root matches but the current verification contract is absent;
- generalized candidates without a stable target/workdir reality anchor fail closed as `untested`;
- inhibited candidates cannot qualify;
- output is bounded and privacy-safe: hashes, candidate IDs, status and compared field names are retained, not raw task/path/content/command values;
- the evaluation is derived from persisted L1/L2 evidence plus current persisted Investigation facts, so Situation can reconstruct it after resident restart without a second mutable skill/evaluation database;
- applicability is **not** written into `Investigation.facts`; this deliberately avoids feeding a derived L3 judgment back into the L1 reality evidence fingerprint used by failed-action anti-replay and verified experience;
- Investigation retains only bounded observational evidence text, while `CognitiveSituation` derives a bounded structured view and Thought can acknowledge it;
- `supported` does not change Thought's existing stage-derived chosen action, does not populate `native_action_result`, and does not call Body, capability loading or `_deliberation_step` as action authority.

Two real CI failures were intentionally retained as development evidence rather than hidden:

- run `32641858655`: Python failed because the integration test incorrectly assumed a fixed number of resident pulses before the path probe;
- run `32642032803`: after fixing that timing assumption, Python still failed and proved the active product caller bypassed `EmbodiedInvestigator.investigate()`;
- direct safe diagnostic evaluation then showed the actual candidate/current facts were correctly `supported`; the active `WorldAwareEmbodiedInvestigator` was calling `NativeInvestigator.investigate()` directly to avoid duplicate schema feedback;
- the final one-line active-caller fix invokes the same read-only applicability hook in that world-aware path, after which run `32642408966` is fully green.

This closes only the read-only L3 applicability slice. Candidate influence on action selection, mature procedural skill state, fast path and activated-route de-proceduralization remain unimplemented.

## 3. Verified memory / nervous-system foundations

Current code/test evidence already supports the following foundations:

- `StructuredMemory` provides resident-owned durable structured facts with normalized key/alias recall;
- `PersistentNervousSystem` stores persistent `NeuralTrace` records instead of transcript entries;
- repeated matching experience strengthens one trace rather than appending endless duplicates;
- co-active traces build associations that can spread activation;
- visual/world/action/outcome/will experiences share the same nervous substrate;
- trace activation considers cue overlap plus strength, salience, recency, repetition and associative gain;
- persistent affective state survives restart;
- consolidation can stabilize recurring structure, form schema traces, fade weak detail and prune sufficiently weak isolated traces;
- lived traces and consolidated schemas can enter Situation/Thought locally;
- private lived/schema details are not automatically dumped into external cognition context;
- current reality gates transfer/reconsolidation rather than treating old memory as eternal truth;
- repeated independently verified episodes can form transparent non-executable procedural candidates;
- current independent Investigation evidence can now classify candidate applicability without granting action authority.

Representative test coverage includes `tests/agent/kernel/test_nervous_system.py`, `tests/agent/kernel/test_neural_cognition_boundary.py`, `tests/agent/kernel/test_procedural_tendency.py`, `tests/agent/kernel/test_procedural_applicability.py` and `tests/agent/kernel/test_procedural_applicability_contract.py`.

### Not yet implemented / not yet claimed

The project does **not** yet claim:

- candidate procedural tendencies influencing native action selection or deliberation;
- resident-owned mature skills that execute locally without external model interpretation;
- procedural fast paths that reduce explicit Thought for familiar low-risk work;
- prediction-error-driven de-proceduralization/relearning of an activated procedural route beyond the current candidate inhibition baseline;
- measurable learned computer-use competence;
- measurable learned engineering competence;
- benchmarks proving external cognition use falls for familiar task classes while verification quality remains intact.

Those are future implementation targets defined by `ZN.md` and `docs/ZN-MEMORY-LEARNING.md`.

## 4. Current core capability boundary

### Verified foundations

- persistent Self / zero-model resident life;
- durable event + `WorkingState` continuity;
- Situation / Thought / Will continuity;
- nervous memory, schemas and reality-gated reconsolidation;
- multi-pulse native Investigation with retained hypotheses/evidence/facts;
- native Action intents and Body action results;
- structured read-only Git repository sense;
- exact text postcondition verification;
- explicit independent command postcondition verification;
- verification contradiction immediately affects Situation/Thought;
- compact current-event execution context with goal/gap/expected outcome/current action/latest verification/bounded verification history;
- bounded failed-action ledger tied to stable Investigation evidence state;
- A → B → A replay suppression under unchanged reality with retry eligibility after changed facts;
- blocked post-cognition movement cannot falsely complete the task;
- bounded restart-safe privacy-safe `VerifiedExperience` records created only from independent Body verification;
- deterministic masked-success/failure semantics prevent visible swallowed failures from becoming positive command-verification learning;
- repeated compatible verified episodes can be retrieved as transparent non-executable candidate tendencies with bounded support/contradiction/reliability/applicability state;
- candidate evidence survives restart through resident-owned L1 causal storage and L2-aware retention;
- read-only L3 applicability compares candidates with current Investigation reality, fails closed on missing/mismatched evidence, survives restart through derivation, and surfaces into Situation/Thought without changing Body authority;
- bounded external cognition returning as input to ZN rather than owning the resident loop;
- ZN-owned local process/terminal/PTTY and web search/extract paths;
- persistent work/thread/workspace/active-run state;
- resident-owned provider/settings/channel lifecycle.

### Still PARTIAL / MISSING

- bounded low-risk candidate influence on existing ZN-owned structured action formation;
- mature/procedural skill state beyond the transparent L2 candidate/practiced baseline and read-only L3 applicability;
- resident-owned derivation and maintenance of reliable high-level task postconditions;
- multi-step execution that can choose genuinely different tactics over many actions without becoming a model-owned planner;
- stronger alternative-action recovery after evidence blocks a movement;
- first-class durable completed-task verification/audit evidence beyond the current bounded learning records;
- safe Git mutation + diff/test/reality verification;
- GitHub repository/PR/CI resident-owned read sense;
- clean browser Body/Senses seam;
- mature visual + mouse/keyboard application control;
- learned computer-use procedural competence;
- learned engineering procedural competence;
- real complex-task and learning-growth benchmark suites;
- SM1+ self-maintenance implementation.

## 5. Product/workbench state

### Resident work loop

`ResidentWorkLedger` owns durable threads/messages, workspace association, active work linkage/progress and bounded contextual file/diff/terminal artifacts beside kernel state. Renderer/localStorage is not authority.

Status: **M6 PARTIAL; core execution mainline active**.

### External cognition/settings

ZN-native OpenAI-compatible, Anthropic and Gemini resource adapters plus resident-owned provider/credential configuration remain active. Missing credentials degrade cognition rather than killing the resident.

Status: **M2 complete for active main provider families**.

### Local Body

ZN-owned filesystem/process/terminal/PTTY paths are active. Exact text and explicit command postcondition verification are CI-verified. Failed-action replay is evidence-bound rather than controlled by one last signature, independently verified action episodes enter the bounded learning store, repeated compatible episodes can form observational candidates, and current Investigation reality can now classify candidate applicability. Candidates still do not control Body action.

Status: **active; practical breadth, long-horizon composition and reality-gated procedural action influence remain incomplete**.

### Web/world sense

ZN-owned search/extract providers and URL/network safety are active. Browser automation is not yet owned by a clean ZN resident seam.

### Visual sense

Resident-owned visual sensing foundations exist and are tested, including persistence and reality-gated neural use. Mature screen understanding + mouse/keyboard computer-use completion is not claimed.

### Communication

Resident-owned channel lifecycle and Telegram text/inbound media are active. Outbound attachment transport remains pending explicit resident-owned egress nomination; arbitrary local paths are not upload authority.

### Desktop/UI

Independent ZN Electron main, preload, renderer/workbench and `zn://` are active. M4 is complete and M5/M6 are materially advanced. Pure UI polish is paused during the core-first phase.

## 6. Runtime/package/release evidence

### M1 runtime ownership

Status: **COMPLETE for active packaged resident path**.

The independent `runtime/python` distribution is `znagent`, installed package `zn_agent`, resident entrypoint `zn-resident`. Packaged runtime rejects inherited `hermes_cli` and can boot zero-model. `runtime/python/pyproject.toml` maps `zn_agent.core` directly to the owned `agent/kernel` source, so the verified-experience, candidate-tendency and applicability implementation is part of the packaged Python distribution rather than a second unsynchronized copy.

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

Artifacts preserve ZN product/protocol/runtime identity and independently bootable zero-model `zn_agent` runtime. This does not imply signing/notarization or complete release readiness.

### M8 installed Linux + source continuity evidence

Status: **IN PROGRESS / bounded release lane**.

Verified Linux clean install:

```text
source                    6e980ac2fe46a0680751dd55711ac53749419a14
ZN Linux Clean Install    success
run                       32591603017
fresh runner              Ubuntu 24.04.4 LTS
```

Verified installed Linux autostart:

```text
source                    6cc8becea3d97eea09c0887cd5c70612fc9ee573
normal CI run             32593886005
ZN Linux Autostart Smoke  success
run                       32593886026
```

Verified source-level N → N+1 continuity:

```text
eb1d1874f1d24dae9ceb74635886615368166ce1  defer handoff for queued work
f0a829b618d931f6f5e40bf314fda592783db6c9  side-by-side runtimes
91a6b500274e0cc0f64be54839e51f5c377a1c16  idle resident continuity
b79c94c67f5ef19af8c0a8e4ba0d9e9877a400f3  align continuity with work snapshot
normal CI run                              32596442626
```

Still unverified as separate release gates:

- full installed Electron/application updater N → N+1 scenario;
- Windows/macOS clean-install/login continuity for intended release matrix;
- signing/notarization when operationally configured;
- additional architectures if required by eventual release matrix.

## 7. Ownership/behavior contracts currently protected

Current regressions protect, among other things:

```text
agent/kernel must not import hermes_cli or run_agent
runtime distribution identifies as znagent
packaged runtime rejects hermes_cli
zero-model resident boot succeeds
external model success returns as bounded cognition before resident acceptance
resident event/investigation/action state survives restart
NativeBody Git sense returns structured repository state
successful write movement does not imply task completion
write and command postconditions survive restart and are independently re-observed
verification contradiction returns to Investigation and becomes immediate Thought evidence
compact execution context survives restart and remains bounded
failed-action records survive restart and remain bounded
A -> B -> A is blocked under unchanged Investigation facts
changed facts can requalify a prior action
timestamp-only observation noise does not requalify a failed movement
accepted external cognition cannot falsely complete the same still-blocked movement
new action cycles archive old verification without current-state pollution
independently verified action/outcome episodes persist across restart
Body success, naked exit 0 and model/report text alone cannot create positive learned experience
postcondition contradiction creates negative verified-experience evidence
verified-experience storage is bounded and excludes raw task/content/path/command/output/capability-label payloads
shell-masked command success with visible deterministic failure evidence cannot positive-verify
one verified event cannot create a procedural candidate
duplicate same-event evidence cannot fake repeated candidate support
two distinct compatible verified events can form one non-executable candidate
candidate support/contradiction/reliability/applicability remain inspectable and bounded
contradiction can contest or inhibit a candidate
candidate reconstruction survives resident restart without a second skill database
retention preserves minimum repeated support for existing candidates when capacity permits
candidate serialization does not restore raw task/content/path/capability-label data
candidate aggregation does not activate Body, deliberation, capability loading or nervous action selection
matching task/request context without independent current observation remains untested
matching observed stable target can support a candidate
other-target or incompatible current contract produces mismatch
inhibited candidate cannot qualify
generalized candidate without a stable reality anchor remains untested
matching repository root without a complete current verification contract remains untested
applicability output excludes raw path/content/task/command values
applicability is reconstructed after restart from durable evidence rather than a second mutable database
applicability is not stored in Investigation facts and therefore does not perturb L1 reality fingerprints
active WorldAwareEmbodiedInvestigator preserves the read-only applicability hook
supported applicability does not execute Body or change stage-derived action selection
persistent nervous traces survive restart
repeated experience strengthens one trace instead of appending endless duplicates
co-active experience builds associative activation
consolidation can form schema and prune weak isolated detail
private neural/schema evidence is not automatically dumped into external model context
provider secrets/settings remain resident-owned and sanitized
work/thread/workspace/progress remain resident authority
ZN desktop main/preload/renderer do not delegate to inherited control planes
formal package metadata/protocol identify ZN only
real packaged runtime boots across exercised Linux/Windows/macOS artifacts
fresh Linux install/autostart continuity works from packaged artifacts
queued resident work prevents false-idle runtime handoff
idle N -> N+1 preserves living-self/work continuity
```

Current regressions now prove the first causal L1 episode, the transparent L2 candidate aggregation/retrieval baseline, and the first read-only reality-gated L3 applicability slice. They do **not** prove candidate-driven action influence, mature resident-owned skills or learned skill fast-path behavior; those remain future tests.

## 8. Milestone snapshot

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

Learning architecture is tracked separately in `docs/ZN-MEMORY-LEARNING.md`: L0 is defined, L1 independently verified experience is CI-verified, the transparent L2 candidate aggregation/retrieval baseline is CI-verified, and the first read-only L3 current-reality applicability slice is CI-verified. L3 action influence and later procedural maturity/fast-path work remain unimplemented.

## 9. Immediate next development sequence

1. keep `VerifiedExperience`, transparent candidate evidence and current independent Investigation facts as the source of procedural-learning truth; candidate state must never bypass current reality;
2. build the smallest **bounded low-risk L3 action-influence slice**: only a `supported`, non-inhibited candidate may bias existing ZN-owned structured action formation, never supply raw commands/args or become a replay engine;
3. `mismatch` or `untested` must have zero positive action influence and must leave control with current Investigation/Thought;
4. preserve independent post-action verification even for a supported candidate; procedural familiarity must not lower truth requirements;
5. ensure later contradiction/prediction error immediately inhibits/deproceduralizes the candidate route and returns control to Investigation before any fast path is claimed;
6. use stronger alternative-action recovery as an early concrete learning consumer: verified success of genuinely different B after A fails should become reusable causal evidence rather than an isolated tactic rule;
7. then build practical Git mutation + diff/test/reality verification and GitHub repo/PR/CI sense as a strong engineering-competence benchmark;
8. establish browser/visual/mouse/keyboard Body/Senses before claiming learned computer-use competence;
9. add growth benchmarks that prove familiar tasks become less model-dependent without lowering verification quality;
10. keep remaining M8 updater/multi-OS/signing work explicit as bounded release debt and fix it when it exposes a real continuity/security/data-integrity problem.

The architecture driver remains:

> **The same persistent ZN Self must be able to finish hard work, prove from current reality that it is finished, and gradually internalize repeatedly verified competence so models become advisers for novelty rather than permanent owners of ability.**