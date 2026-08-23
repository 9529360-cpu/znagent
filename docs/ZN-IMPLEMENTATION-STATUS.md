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
> This file is the current implementation ledger. Real code, Git state and CI remain authoritative over this document.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit M10 promotion milestone.

## 1. Current development checkpoint — 2026-08-23

The active core mainline is:

```text
durable ZN Self
+ mature complex-task execution depth
+ reality-based verification
+ resident-owned learning / procedural competence
```

Pure UI polish is paused. M8/release remains a bounded continuity/release lane.

The resident already owns persistent Self/life, Situation/Thought/Will, nervous memory/reconsolidation, durable events/working state, multi-pulse Investigation, native Action/Body movement, bounded external cognition and zero-model continuity.

The execution/learning spine has real CI verification for:

- structured read-only Git repository sense;
- exact text and explicit command postcondition verification;
- compact durable execution context;
- evidence-bound failed-action anti-replay;
- bounded restart-safe privacy-safe `VerifiedExperience` L1 records grounded only in independent Body verification;
- transparent L2 candidate procedural-tendency aggregation;
- read-only L3 current-reality applicability (`supported | mismatch | untested`);
- the first bounded L3 action-influence slice, where a sufficiently mature, non-inhibited, currently supported low-risk tendency may bias among action choices that current ZN state already formed, without supplying arguments or weakening verification;
- bounded **native structured-choice recovery**: when an explicit current choice set already exists and current evidence blocks an earlier choice, the resident can continue to the first later unblocked choice without requiring procedural memory.

The active transition is therefore:

```text
verified lived experience
→ repeated compatible evidence
→ candidate resident-owned tendency
→ current Situation applicability test        VERIFIED FIRST SLICE
→ bounded reality-gated action influence       VERIFIED FIRST SLICE
→ consume bounded structured alternatives      VERIFIED RECOVERY SLICE
→ resident-owned choice formation from Will/Investigation
→ mature procedural competence
→ familiar low-latency execution
→ prediction-error interrupt / relearning
```

The latest recovery slice is a prerequisite/consumer capability. It is **not** resident-owned generation of useful alternatives, a mature skill, a replay engine, a fast path, or a model-owned planner.

## 2. Verified core execution and learning spine

### 2.1 Structured read-only Git repository sense

Representative source:

```text
168579604157467bb2384f385849c621ca66cefe  feat: strengthen native Git repository sense
59957637a6840a6ce54e10b67ee5dc7bc0623867  test: isolate Git sense from resident sqlite files
```

Final first-slice CI:

```text
code/test SHA           47ccd5601462641c50c16ec76f2a05085a33f9f3
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32612456040
```

`NativeBody.git_state` returns structured root, branch, HEAD, upstream/ahead/behind, dirty state and bounded staged/unstaged/untracked/conflicted path evidence. This remains read-only repository sense; general Git mutation and GitHub maintenance are not claimed.

### 2.2 Action result is evidence, not task completion

Representative source/test state:

```text
7a30baea6b4a2471479152e2843c50c0c7279997  feat: verify body postconditions before task completion
66f0fecc21b3cd7303c1f01b257095704f3454f4  feat: make post-action verification a resident thought stage
47ccd5601462641c50c16ec76f2a05085a33f9f3  test: require reality verification after native writes
```

For exact non-append text mutation:

```text
Investigation
→ NativeActionIntent(write_text)
→ Body movement
→ durable native_verification stage
→ verify_action Thought
→ independent Body read
→ exact current-reality comparison
→ complete only if verified
```

The verification stage survives restart. Contradiction returns control to Investigation and records failure evidence rather than silently completing.

### 2.3 Explicit independent command postconditions

Representative source/test state:

```text
5cc0b1bccca976a8c635fbf3ddd7f95912a4cdc6  feat: verify explicit command postconditions
8a661a376bd0d24dc2eea5dbe4187a159a8f4df1  feat: surface verification evidence in resident thought
f280c8f68af69dfc2ac10b94d8d83726c10aa14e  test: fix command verification shell contract
```

Real CI: run `32621596489`, Python and Electron both success.

A structured `expected_outcome` command check is executed independently after the primary movement. Generic shell exit `0` still does not prove an arbitrary high-level goal.

### 2.4 Compact durable execution context

Representative source/test state:

```text
470a8549901fd4201556188ea8276f83ebdb6033  feat: persist compact task execution context
969e07125db396f3f949aaa4d846fb5f8a0fd6bf  feat: bring execution context into situation
aaa6fa55c5c4e1968006f618a37260cb4f41675a  test: cover compact execution context
```

Real CI: run `32621878503`, Python and Electron both success.

`WorkingState.execution_context` is bounded and carries the active goal, stage, current gap, expected-outcome summary, current-action summary, latest verification, bounded verification history and failed-action summaries. It is not a plan tree.

### 2.5 Evidence-bound failed-action history

Final code/test SHA:

```text
23ce3b42aad2d730afae4d60eb6af5d5b4bd1399
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32635668910
```

`native_action_failure_records` stores bounded action-signature hashes tied to stable Investigation evidence fingerprints. Same-action replay stays blocked under unchanged reality; A → B → A does not reopen A merely because B was attempted; substantive new facts can requalify prior movement; timestamps alone cannot; records survive restart; accepted external cognition text is not world evidence and cannot unlock a failed movement by itself.

This is anti-replay and causal recovery infrastructure, not a tactic generator.

### 2.6 L1 independently verified resident experience

Final code/test SHA:

```text
80292975264df35ff3a999ed32c7973cdd3514f5
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32639405457
```

A `VerifiedExperience` is created only after independent Body verification. Positive and contradicted episodes are retained. Naked Body success, naked exit `0`, model text, report text and unsupported verification contracts cannot create positive learning. Raw task/gap text, commands, verification commands, paths/workdirs, content, output fragments and caller capability labels are excluded from persisted learned evidence.

### 2.7 L2 transparent candidate procedural tendencies

Final code/test SHA:

```text
25ff0ada9efc8e8d830d085856edca7ea772a696
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32640409344
```

`VerifiedExperienceStore.candidate_tendencies()` derives bounded non-executable candidate state from L1 episodes. One event or same-event duplicates cannot fake repetition; support, contradiction, reliability, maturity and inhibition remain explicit; raw action arguments are not reconstructed; candidate state is derived rather than maintained as a second mutable skill database.

### 2.8 L3 read-only current-reality applicability

Final code/test SHA:

```text
202b69e947db6c178d821c27e51fc1e61a90ce82
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32642408966
```

`procedural_applicability.py` returns only `supported`, `mismatch` or `untested`. Positive support requires a current independent stable reality anchor and no untested compared field. Request shape alone cannot create support. Applicability is reconstructed from L1/L2 plus current Investigation facts and is not written back into Investigation facts, so it cannot contaminate failed-action evidence identity.

### 2.9 L3 bounded low-risk action influence

Final code/test SHA:

```text
aec75ec2b2a2e37eae57a4a26011f324c1a823ff
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32643849526
```

The active constructor returns `ProcedurallyInfluencedResidentRuntime`, which remains inside the full `WorldAwareTransferResidentRuntime` hierarchy.

Authority remains deliberately small:

- ordinary heuristic action formation remains historical single-choice behavior;
- multiple choices exist only through explicit bounded `native_action_options`;
- valid `body_action` / `native_action` remains exclusive;
- free-text multi-clause tasks are not reinterpreted as alternatives;
- procedural evidence may only reorder current intents and never create or modify their args;
- only supported/practiced, non-inhibited, reliability `>= 0.75`, currently `supported` candidates can positively influence;
- mismatch/untested/immature/inhibited/revoked candidates have zero positive authority;
- the first positively influenced shape is exact non-append `write_text` with resident-owned `text_equals` verification;
- commands, append writes and direct structured-event actions receive no positive procedural influence in this slice;
- evidence-bound anti-replay outranks familiarity;
- Body and independent verification ownership remain unchanged;
- failure/contradiction returns to Investigation and revokes the influenced route for the current event.

The integration path proves three independently verified writes can create a supported candidate that biases an already-present `[command, write_text]` current choice toward the exact write; Body performs it and independently verifies it. A later verification contradiction revokes that influenced route.

### 2.10 Bounded native structured-choice recovery

Final code/test SHA:

```text
2632bcb2a6738c79a250205374d45a0d34bbad36
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32645416634
Container / Runtime Smoke  skipped on normal push
Publish commit statuses success
```

Source/test commits for this slice:

```text
3d1d7ebdce9c02224d4e836ef6c4c4d6df2758f7  feat: recover across bounded native choices
2632bcb2a6738c79a250205374d45a0d34bbad36  test: cover bounded native choice recovery
```

The active resident can now consume an explicit structured choice set correctly after reality rejects an earlier option:

```text
current explicit choices [A, B, ...]
→ A is recorded failed under current evidence fingerprint
→ deliberation re-observes the same current choice set
→ anti-replay blocks A
→ resident selects first later unblocked structured choice
→ existing Body / verification path remains owner
```

Guarantees:

- recovery requires at least two intents and every intent must be `source == structured_choice`;
- no alternatives are inferred from free text, memory, model output or failed-action arguments;
- no procedural candidate is required to move from blocked A to explicit B;
- if the first choice is not blocked, historical declared order remains unchanged;
- a single explicit `body_action` / `native_action` cannot trigger this recovery path;
- current option args remain authoritative; failed history cannot supply replacement args;
- if all choices are blocked, recovery fails closed and existing deliberation/impasse behavior remains owner;
- bounded recovery metadata records only selected index/count, blocked-prior count, action kind and a truncated evidence version;
- the recovery marker is visible to Thought and cleared before a later deliberation cycle;
- the active runtime still contains the full `WorldAwareTransferResidentRuntime` chain;
- independent verification remains mandatory wherever the selected action requires a postcondition contract.

This closes a consumer-side prerequisite for future resident-owned choice formation. `native_action_options` is still an explicit structured event seam; ZN does **not** yet autonomously generate useful alternatives from Will/Investigation.

The validated SHA also included unrelated concurrent channel/Telegram branch changes that were already present when this slice was committed. CI validated the combined branch state; this section makes no new product-capability claim from those concurrent files.

### 2.11 Resident-owned outbound channel media seam

Final code/test SHA:

```text
018af2ec18abbac2a74e33f471101cb6a4308f36
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32645243684
```

`ResidentChannelSupervisor.nominate_outbound_media()` records a bounded, JSON-safe media nomination only for an existing pending resident `channel_message` route. The intent is stored in the channel delivery SQLite ledger and survives supervisor restart. Delivery consumes this structured state; it never scans response text or inbound attachments for upload paths.

`TelegramBotApiChannel` authorizes every nominated file against explicit resolved ZN-owned roots at the adapter send boundary before any network request, then uploads authorized files as multipart `sendDocument`. The first slice preserves thread/reply routing, supports attachment-only delivery, sanitizes filenames, applies the existing transport size limit, and keeps bot tokens out of errors. An unauthorized nomination rejects the entire delivery before text or file transmission begins.

This completes the durable nomination → authorization → first transport seam, not autonomous media judgment. No current Thought/Will/Investigation owner yet decides that a produced artifact should be nominated, and photo/audio/video-specific Telegram methods remain pending.

## 3. Verified memory / nervous-system foundations

Current foundations include:

- `StructuredMemory` durable facts with normalized key/alias recall;
- persistent `NeuralTrace` nervous memory rather than transcript storage;
- repeated experience strengthening one trace;
- associative co-activation;
- visual/world/action/outcome/will traces in one resident substrate;
- persistent affective state;
- consolidation, schema formation, weak-detail fade and bounded pruning;
- local lived/schema evidence entering Situation/Thought without automatically dumping private detail into external cognition;
- reality-gated transfer/reconsolidation;
- L1 verified causal episodes;
- L2 transparent candidate tendencies;
- L3 current-reality applicability;
- first bounded L3 positive action influence;
- bounded native recovery across an already-formed structured choice set.

Representative tests include:

- `tests/agent/kernel/test_nervous_system.py`
- `tests/agent/kernel/test_neural_cognition_boundary.py`
- `tests/agent/kernel/test_procedural_tendency.py`
- `tests/agent/kernel/test_procedural_applicability.py`
- `tests/agent/kernel/test_procedural_applicability_contract.py`
- `tests/agent/kernel/test_procedural_influence.py`
- `tests/agent/kernel/test_native_action_alternatives_contract.py`
- `tests/agent/kernel/test_native_choice_recovery.py`

### Not yet implemented / not yet claimed

The project does **not** yet claim:

- resident-owned generation of useful structured action alternatives from Will/Investigation;
- broad candidate influence over commands or arbitrary side effects;
- procedural replay of raw commands/paths/content;
- mature resident-owned skills;
- procedural fast paths that reduce explicit Thought for familiar work;
- autonomous de-proceduralization beyond candidate inhibition + event-local route revocation;
- learned engineering competence;
- learned computer-use competence;
- growth benchmarks proving lower model dependence without lower verification quality.

## 4. Current core capability boundary

### Verified foundations

- persistent Self / zero-model resident life;
- durable event + `WorkingState` continuity;
- Situation / Thought / Will continuity;
- nervous memory, schemas and reality-gated reconsolidation;
- multi-pulse native Investigation with retained hypotheses/evidence/facts;
- native Action intents and Body action results;
- structured read-only Git repository sense;
- exact text and explicit independent command postcondition verification;
- compact bounded current-event execution context;
- evidence-bound failed-action ledger and A → B → A replay suppression under unchanged reality;
- bounded native recovery to a later explicit structured choice after earlier choices are blocked under current evidence;
- blocked post-cognition movement cannot falsely complete;
- bounded restart-safe privacy-safe L1 `VerifiedExperience`;
- transparent L2 candidate tendencies;
- L3 current-reality applicability;
- bounded L3 bias among explicitly current choices for verified low-risk exact writes;
- contradiction revokes active event-local procedural influence and returns to Investigation;
- bounded external cognition returns as input to ZN rather than owning the resident loop;
- ZN-owned local process/terminal/PTTY and web search/extract paths;
- persistent work/thread/workspace/active-run state;
- resident-owned provider/settings/channel lifecycle;
- durable explicit outbound-media nomination plus policy-authorized Telegram document delivery.

### Still PARTIAL / MISSING

- resident-owned structured alternative formation from current Will/Investigation;
- learned formation/recovery of genuinely different tactics rather than consumption of caller-provided options;
- mature/procedural skill state and fast path;
- resident-owned reliable high-level postcondition derivation;
- multi-step execution with genuinely different tactics over long horizons without a model-owned planner;
- durable completed-task verification/audit beyond current bounded learning evidence;
- safe Git mutation + diff/test/reality verification;
- GitHub repository/PR/CI resident-owned sense;
- clean browser Body/Senses seam;
- mature visual + mouse/keyboard application control;
- autonomous outbound artifact nomination from current Thought/Will/Investigation;
- Telegram photo/audio/video-specific outbound transports;
- learned computer-use and engineering competence;
- complex-task/learning-growth benchmarks;
- SM1+ self-maintenance implementation.

## 5. Product/workbench state

### Resident work loop

`ResidentWorkLedger` owns durable threads/messages, workspace association, active-work linkage/progress and bounded contextual file/diff/terminal artifacts beside kernel state. Renderer/localStorage is not authority.

Status: **M6 PARTIAL; core execution mainline active**.

### External cognition/settings

ZN-native OpenAI-compatible, Anthropic and Gemini resource adapters plus resident-owned provider/credential configuration remain active. Missing credentials degrade cognition rather than killing the resident.

Status: **M2 complete for active main provider families**.

### Local Body

Filesystem/process/terminal/PTTY paths are ZN-owned. Verification, failed-action anti-replay and L1/L2/L3 learning evidence are active. Supported low-risk write evidence may bias an already-current choice, and the resident can now recover across an already-formed explicit choice set when earlier options are blocked. Candidates still cannot invent actions or replay stored args.

Status: **active; practical breadth, resident-owned alternative formation and mature procedural competence remain incomplete**.

### Web/world sense

ZN-owned search/extract providers and URL/network safety are active. Browser automation is not yet owned by a clean resident seam.

### Visual sense

Resident-owned visual sensing foundations exist and are tested. Mature screen understanding plus mouse/keyboard completion is not claimed.

### Communication

Resident-owned channel lifecycle and Telegram text/inbound media are active. The first outbound-media slice is also active: a pending resident channel event may durably nominate a bounded local artifact, restart preserves that intent, and Telegram authorizes the resolved file through `OutboundMediaPathPolicy` before any network request. Authorized files are uploaded with `sendDocument`; attachment-only outcomes are supported, and response text or inbound attachments never become upload authority.

This is not yet autonomous artifact selection. Current cognition does not independently decide when to nominate an artifact, and the first transport slice deliberately uses Telegram document delivery rather than selecting richer media-specific methods.

### Desktop/UI

Independent ZN Electron main, preload, renderer/workbench and `zn://` are active. M4 is complete and M5/M6 are materially advanced. Pure UI polish remains paused during the core-first phase.

## 6. Runtime/package/release evidence

### M1 runtime ownership

Status: **COMPLETE for active packaged resident path**.

The independent `runtime/python` distribution is `znagent`, installed package `zn_agent`, entrypoint `zn-resident`. Packaged runtime rejects inherited `hermes_cli` and boots zero-model. `runtime/python/pyproject.toml` maps `zn_agent.core` directly to `../../agent/kernel`, so current kernel code is the packaged runtime source rather than a second copy.

Normal CI run `32645416634` installed the isolated runtime distribution, booted it without a model, compiled the resident kernel and ran the full kernel test suite successfully.

### M7 formal artifact ownership

Status: **ARTIFACT SHAPE VERIFIED** on exercised targets:

```text
Linux   x86_64   AppImage / deb / rpm
Windows x64      NSIS / MSI
macOS   arm64    DMG / ZIP
```

Representative evidence:

```text
Linux artifact source   6219eaa61f6c444feb96864e149f886752b00ffe
Linux integration       46685b66ff1381cb0b41b1e0564cc62ca5e34467
Windows source          2e3cdb0ac893feca86325e19a058c455c906bfd7
Windows smoke run       32590239803
macOS source            518d233eafa39b2d12f2de5835a8c8c1ab7529ab
macOS smoke run         32591343670
```

This does not imply signing/notarization or complete release readiness.

### M8 continuity evidence

Status: **IN PROGRESS / bounded release lane**.

Verified Linux clean install: run `32591603017`.

Verified installed Linux autostart: run `32593886026`.

Verified source-level N → N+1 continuity: normal CI run `32596442626`.

Real AppImage successor run `32645354818` includes the outbound-media kernel code and completed both N and N+1 AppImage builds. At this documentation checkpoint its installed continuity step had exceeded the workflow's declared outer 15-minute command timeout without returning a final conclusion. It is therefore **not** recorded as success and remains an M8/updater-lane investigation item.

Still separate release gates:

- installed Electron/application updater N → N+1;
- Windows/macOS clean-install/login continuity for intended release matrix;
- signing/notarization when operationally configured;
- any additional architectures required by the eventual release matrix.

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
successful movement does not automatically imply task completion
write and explicit command postconditions are independently re-observed
verification contradiction returns to Investigation
failed-action records survive restart and stay evidence-bound
A -> B -> A is blocked under unchanged Investigation facts
changed facts can requalify a prior action
timestamp-only noise does not requalify a failed action
accepted external cognition cannot falsely complete the same still-blocked movement
verified experiences require independent Body verification
Body success, naked exit 0 and model/report text alone cannot create positive learned experience
postcondition contradiction creates negative learned evidence
learned storage excludes raw task/content/path/command/output/capability-label payloads
one event or same-event duplicates cannot fake repeated procedural support
candidate support/contradiction/reliability/applicability remain explicit and bounded
candidate reconstruction survives restart without a second skill database
candidate aggregation itself does not activate Body
request-only applicability remains untested
current matching stable target can support applicability
mismatch/incomplete evidence fails closed
applicability is not stored in Investigation facts
active world-aware Investigation preserves applicability observation
ordinary heuristic action formation remains historical single-choice behavior
ordinary multi-clause task text is not reinterpreted as an alternative set
explicit body_action/native_action remains exclusive
native_action_options preserves declared order while its first choice remains admissible
blocked earlier structured choices may be skipped only under the same current evidence-bound anti-replay contract
structured-choice recovery never invents alternatives or action args from memory/failure history
single explicit actions cannot use multi-choice recovery
outbound channel media requires an explicit durable nomination on a pending resident route
response text and inbound attachments never become outbound upload authority
Telegram authorizes every nominated file before any delivery network request
outbound paths outside explicit resolved ZN roots fail closed
only supported/practiced non-inhibited reliable current-reality-supported low-risk write candidates can positively bias
mismatch/untested/immature/inhibited/revoked/unsafe candidate routes have zero positive influence
procedural influence never supplies action args
influenced write still requires independent text_equals verification
verification contradiction revokes the event-local influenced route and returns to Investigation
active runtime still includes the full WorldAwareTransferResidentRuntime chain
persistent nervous traces and schema consolidation survive restart
private neural/schema evidence is not automatically dumped into external cognition
provider secrets/settings remain resident-owned and sanitized
work/thread/workspace/progress remain resident authority
ZN desktop main/preload/renderer do not delegate to inherited control planes
formal package metadata/protocol identify ZN only
```

These regressions prove the first causal L1 episode, transparent L2 aggregation, read-only L3 applicability, a narrowly bounded L3 positive influence seam, and correct native consumption/recovery across an explicitly current structured choice set. They do **not** prove autonomous choice generation, mature skills or fast-path behavior.

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

Learning architecture is tracked separately in `docs/ZN-MEMORY-LEARNING.md`: L0 is defined; L1 verified experience, L2 candidate aggregation, read-only L3 applicability, bounded L3 influence and bounded structured-choice recovery are CI-verified. Autonomous resident-owned choice formation, mature procedural competence and fast-path work remain incomplete.

## 9. Immediate next development sequence

1. keep `VerifiedExperience`, transparent candidate evidence and current independent Investigation facts as procedural-learning truth; current reality always outranks familiarity;
2. implement the first **resident-owned bounded structured-choice formation** from current Will/Investigation state, now that the consumer can correctly recover across blocked explicit choices;
3. require a semantic proof that candidates are genuine alternatives for the same current goal; do not infer alternatives merely because free text contains several action clauses;
4. do not let external model output or stored procedural memory become the owner of the choice set;
5. keep memory from supplying raw commands/args/path/content; action arguments must come from current resident-owned state;
6. preserve current influence gates and mandatory independent verification;
7. use a real learned recovery pattern as a consumer benchmark: A fails → genuinely different B succeeds → B independently verifies → later comparable reality may support B-pattern, without hardcoding an A/B tactic rule;
8. then build practical Git mutation + diff/test/reality verification and GitHub repo/PR/CI sense as an engineering-competence benchmark;
9. establish browser/visual/mouse/keyboard Body/Senses before claiming learned computer-use competence;
10. add growth benchmarks proving familiar tasks reduce external cognition dependence without lowering verification quality;
11. keep M8 updater/multi-OS/signing work explicit as bounded release debt until a real continuity/security/data-integrity need makes it the active lane.

The architecture driver remains:

> **The same persistent ZN Self must be able to finish hard work, prove from current reality that it is finished, and gradually internalize repeatedly verified competence so models become advisers for novelty rather than permanent owners of ability.**
