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

The execution/learning spine now has CI-verified:

- structured read-only Git repository sense;
- exact text and explicit command postcondition verification;
- compact durable execution context;
- evidence-bound failed-action anti-replay;
- bounded restart-safe privacy-safe `VerifiedExperience` L1 records grounded only in independent Body verification;
- transparent L2 candidate procedural-tendency aggregation;
- read-only L3 current-reality applicability (`supported | mismatch | untested`);
- the first **bounded L3 action-influence slice**: a sufficiently mature, non-inhibited, currently supported low-risk procedural tendency may bias among action choices that the current event already formed explicitly, without supplying action arguments or weakening verification.

The active transition is therefore:

```text
verified lived experience
→ repeated compatible evidence
→ candidate resident-owned tendency
→ current Situation applicability test        VERIFIED FIRST SLICE
→ bounded reality-gated action influence       VERIFIED FIRST SLICE
→ resident-owned choice formation from Will/Investigation
→ mature procedural competence
→ familiar low-latency execution
→ prediction-error interrupt / relearning
```

The latest slice is intentionally narrow. It is **not** a mature skill, a replay engine, a fast path, or proof that ZN can yet derive useful alternatives on its own.

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

`NativeBody.git_state` returns structured root, branch, HEAD, upstream/ahead/behind, dirty state and bounded staged/unstaged/untracked/conflicted path evidence. Embodied Investigation consumes the same Body contract. This remains read-only repository sense; general Git mutation and GitHub maintenance are not claimed.

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

Real CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32621596489
```

A structured `expected_outcome` command check is executed independently after the primary movement. Exit code, optional output fragments, workdir, timeout and output bounds are compared against current observation. Generic shell exit `0` still does not prove an arbitrary high-level goal.

### 2.4 Compact durable execution context

Representative source/test state:

```text
470a8549901fd4201556188ea8276f83ebdb6033  feat: persist compact task execution context
969e07125db396f3f949aaa4d846fb5f8a0fd6bf  feat: bring execution context into situation
aaa6fa55c5c4e1968006f618a37260cb4f41675a  test: cover compact execution context
```

Real CI: run `32621878503`, Python and Electron both success.

Active `WorkingState.execution_context` is bounded and contains goal, stage, current gap, expected-outcome summary, current-action summary, latest verification, bounded verification history and failed-action summaries. It is not a plan tree or a growing task database.

### 2.5 Evidence-bound failed-action history

Final code/test SHA for this slice:

```text
23ce3b42aad2d730afae4d60eb6af5d5b4bd1399
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32635668910
```

`native_action_failure_records` stores bounded action-signature hashes tied to stable Investigation evidence fingerprints. Current behavior includes:

- same action under unchanged evidence stays blocked;
- A → B → A does not reopen A merely because B was attempted;
- substantive new Investigation facts can requalify a prior movement;
- observation timestamps alone do not requalify it;
- records survive restart;
- accepted external cognition text is not current-world evidence and cannot unlock a failed movement by itself;
- blocked post-cognition movement cannot fall through to false completion.

This is anti-replay and causal recovery infrastructure, not a tactic generator.

### 2.6 L1 independently verified resident experience

Final code/test SHA:

```text
80292975264df35ff3a999ed32c7973cdd3514f5
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32639405457
```

A `VerifiedExperience` is created only after independent Body verification. Positive and contradicted episodes are both retained. Naked Body success, naked exit `0`, model text, report text and unsupported verification contracts cannot create positive learning.

The record is bounded, restart-safe and privacy-safe. Raw task/gap text, commands, verification commands, paths/workdirs, content, output fragments and caller capability labels are not persisted; fingerprints/counts/categories are retained instead. Storage is bounded to 2048 with L2-aware retention.

### 2.7 L2 transparent candidate procedural tendencies

Final code/test SHA:

```text
25ff0ada9efc8e8d830d085856edca7ea772a696
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32640409344
```

`VerifiedExperienceStore.candidate_tendencies()` derives bounded non-executable candidate state from retained L1 episodes:

- one event cannot create a repeated candidate;
- duplicate same-event records cannot fake repetition;
- at least two distinct compatible verified events are required;
- support, contradiction, reliability, maturity and inhibition remain explicit;
- current states are candidate-level (`candidate`, `supported`, `practiced`, contested/inhibited variants), not mature executable skills;
- raw command/args/path/content/task/model text are not restored into candidates;
- candidate identity/state is reconstructed from L1 evidence rather than a second mutable skill database.

### 2.8 L3 read-only current-reality applicability

Final code/test SHA:

```text
202b69e947db6c178d821c27e51fc1e61a90ce82
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32642408966
```

`procedural_applicability.py` compares candidate evidence with current task contract plus independently observed Investigation facts and returns only `supported`, `mismatch` or `untested`.

Key guarantees:

- request shape can disqualify or compare, but cannot alone make a candidate supported;
- `supported` requires current independent reality evidence for a stable applicability anchor and no untested compared field;
- different target/workdir/verification contract produces mismatch;
- incomplete or missing evidence fails closed as untested;
- generalized candidates without a stable current-reality anchor remain untested;
- inhibited candidates cannot qualify;
- output is bounded and privacy-safe;
- evaluation is reconstructed from persistent L1/L2 + current Investigation facts after restart;
- derived applicability is not written into `Investigation.facts`, so it cannot contaminate the L1 reality fingerprint used for failed-action anti-replay or experience identity;
- Situation/Thought can observe applicability, but this first slice alone does not move Body.

Relevant development evidence was retained rather than hidden: run `32641858655` failed on a brittle fixed-pulse integration assumption; run `32642032803` then exposed the real active `WorldAwareEmbodiedInvestigator` caller bypassing the parent hook. The active-caller fix produced fully green run `32642408966`.

### 2.9 L3 bounded low-risk action influence

Final code/test SHA:

```text
aec75ec2b2a2e37eae57a4a26011f324c1a823ff
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32643849526
```

The active constructor now returns `ProcedurallyInfluencedResidentRuntime`, which subclasses the full `WorldAwareTransferResidentRuntime` chain. The layer does not replace the resident loop, Body, verification, world-aware Investigation or transfer/reconsolidation owners.

The first influence slice deliberately has a small authority boundary:

- normal heuristic action formation remains historical **single-choice** behavior;
- a multi-choice set exists only when the current event explicitly provides bounded `native_action_options`;
- an explicit `body_action` / `native_action` remains exclusive and cannot be overridden by learning;
- ordinary multi-clause task text is not reinterpreted as alternatives, because clauses may represent sequential obligations rather than a choice;
- procedural evidence can only reorder intents already present in that current structured choice set; it cannot create an intent or alter its args;
- only candidate maturity `supported` or `practiced`, non-inhibited state, reliability `>= 0.75`, and current L3 applicability exactly `supported` can create positive influence;
- `mismatch`, `untested`, candidate-level immaturity, inhibition, event-local revocation or insufficient reliability create zero positive influence;
- the first eligible action shape is deliberately only exact non-append `write_text` with the resident-owned automatic `text_equals` postcondition;
- commands, append writes and directly explicit structured actions receive zero positive procedural influence in this slice;
- privacy-safe influence metadata stores candidate/evaluation IDs, maturity/reliability/support and reality-matched field labels, never raw task/path/content/command values;
- existing evidence-bound failed-action anti-replay remains stronger than procedural familiarity;
- Body execution remains the existing Body path;
- independent post-action verification remains mandatory and unchanged;
- Body failure or postcondition contradiction revokes the active candidate for the current event and returns control to Investigation through the existing failure path;
- Thought can observe that a candidate biased an already-formed choice and that it did not supply arguments or waive verification;
- `runtime/python` packages the same `agent/kernel` source directly, so there is no second procedural runtime copy to synchronize.

The real integration test proves the behavioral boundary rather than only the pure selector:

```text
3 independently verified writes
→ one L2 candidate reaches supported
→ current Investigation re-observes the same stable target
→ current event explicitly offers [command, write_text]
→ historical default remains command
→ supported candidate biases to the already-specified write_text option
→ Body performs write_text
→ Body independently read-verifies text_equals
→ command is never executed
```

A second integration path changes reality after the influenced write and before verification. Verification fails, the event returns to `native_investigation`, and the active tendency is event-locally revoked with `verification_contradiction`.

This is **not** yet resident-owned autonomous procedural choice generation. The current choice-set seam is explicit structured event state. The next core gap is for ZN's own Will/Investigation/deliberation to form bounded alternatives from current facts without becoming a model-owned planner or a raw procedural replay system.

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
- first bounded L3 positive action influence under the explicit structured-choice contract.

Representative tests include:

- `tests/agent/kernel/test_nervous_system.py`
- `tests/agent/kernel/test_neural_cognition_boundary.py`
- `tests/agent/kernel/test_procedural_tendency.py`
- `tests/agent/kernel/test_procedural_applicability.py`
- `tests/agent/kernel/test_procedural_applicability_contract.py`
- `tests/agent/kernel/test_procedural_influence.py`
- `tests/agent/kernel/test_native_action_alternatives_contract.py`

### Not yet implemented / not yet claimed

The project does **not** yet claim:

- resident-owned generation of useful structured action alternatives from Will/Investigation;
- broad candidate influence over commands or arbitrary side effects;
- procedural replay of raw commands/paths/content;
- mature resident-owned skills;
- procedural fast paths that reduce explicit Thought for familiar work;
- autonomous de-proceduralization beyond current candidate inhibition + event-local influenced-route revocation;
- learned engineering competence;
- learned computer-use competence;
- benchmarks proving familiar task classes become less model-dependent while independent verification quality remains intact.

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
- blocked post-cognition movement cannot falsely complete;
- bounded restart-safe privacy-safe L1 `VerifiedExperience`;
- transparent L2 candidate tendencies;
- L3 current-reality applicability;
- bounded L3 bias among explicitly current structured choices for verified low-risk exact writes;
- contradiction revokes active event-local procedural influence and returns control to Investigation;
- bounded external cognition returns as input to ZN rather than owning the resident loop;
- ZN-owned local process/terminal/PTTY and web search/extract paths;
- persistent work/thread/workspace/active-run state;
- resident-owned provider/settings/channel lifecycle.

### Still PARTIAL / MISSING

- resident-owned structured alternative formation from current Will/Investigation;
- stronger learned alternative-action recovery after evidence blocks a movement;
- mature/procedural skill state and fast path;
- resident-owned reliable high-level postcondition derivation;
- multi-step execution with genuinely different tactics over long horizons without a model-owned planner;
- durable completed-task verification/audit beyond current bounded learning evidence;
- safe Git mutation + diff/test/reality verification;
- GitHub repository/PR/CI resident-owned sense;
- clean browser Body/Senses seam;
- mature visual + mouse/keyboard application control;
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

Filesystem/process/terminal/PTTY paths are ZN-owned. Verification, failed-action anti-replay and L1/L2/L3 learning evidence are active. A supported low-risk write tendency can now bias an explicitly current structured choice, but candidates still cannot invent actions or replay stored args.

Status: **active; practical breadth, resident-owned alternative formation and mature procedural competence remain incomplete**.

### Web/world sense

ZN-owned search/extract providers and URL/network safety are active. Browser automation is not yet owned by a clean resident seam.

### Visual sense

Resident-owned visual sensing foundations exist and are tested. Mature screen understanding plus mouse/keyboard completion is not claimed.

### Communication

Resident-owned channel lifecycle and Telegram text/inbound media are active. Outbound attachment transport remains pending explicit resident-owned egress nomination; arbitrary local paths are not upload authority.

### Desktop/UI

Independent ZN Electron main, preload, renderer/workbench and `zn://` are active. M4 is complete and M5/M6 are materially advanced. Pure UI polish remains paused during the core-first phase.

## 6. Runtime/package/release evidence

### M1 runtime ownership

Status: **COMPLETE for active packaged resident path**.

The independent `runtime/python` distribution is `znagent`, installed package `zn_agent`, entrypoint `zn-resident`. Packaged runtime rejects inherited `hermes_cli` and boots zero-model. `runtime/python/pyproject.toml` maps `zn_agent.core` directly to `../../agent/kernel`, so current L1/L2/L3 code is the packaged runtime source rather than a second copy.

The latest normal CI `32643849526` also successfully installed the isolated runtime distribution and booted it without a model before running the full kernel tests.

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

Verified source-level N → N+1 continuity: normal CI run `32596442626` after side-by-side runtime, queued-work handoff and idle continuity fixes.

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
native_action_options preserves current declared order when there is no qualifying influence
only supported/practiced non-inhibited reliable current-reality-supported low-risk write candidates can positively bias
mismatch/untested/immature/inhibited/revoked/unsafe candidate routes have zero positive influence
procedural influence never supplies action args
influenced write still requires independent text_equals verification
verification contradiction revokes the event-local influenced route and returns to Investigation
influence metadata excludes raw task/path/content/command values
active runtime still includes the full WorldAwareTransferResidentRuntime chain
persistent nervous traces and schema consolidation survive restart
private neural/schema evidence is not automatically dumped into external cognition
provider secrets/settings remain resident-owned and sanitized
work/thread/workspace/progress remain resident authority
ZN desktop main/preload/renderer do not delegate to inherited control planes
formal package metadata/protocol identify ZN only
```

These regressions prove the first causal L1 episode, transparent L2 aggregation, read-only reality-gated L3 applicability, and a narrowly bounded L3 positive action-influence seam. They do **not** prove autonomous procedural choice generation, mature skills or fast-path behavior.

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

Learning architecture is tracked separately in `docs/ZN-MEMORY-LEARNING.md`: L0 is defined; L1 verified experience, L2 candidate aggregation, read-only L3 applicability and the first bounded L3 action-influence slice are CI-verified. Autonomous resident-owned choice formation, mature procedural competence and fast-path work remain incomplete.

## 9. Immediate next development sequence

1. keep `VerifiedExperience`, transparent candidate evidence and current independent Investigation facts as procedural-learning truth; current reality always outranks familiarity;
2. make the next slice **resident-owned structured choice formation** from current Will/Investigation state, without letting models or stored procedures become a planner and without inferring false alternatives from free-text multi-clause tasks;
3. preserve the current influence gates: only supported/practiced, non-inhibited, reliable and currently `supported` candidates may positively bias; mismatch/untested remain zero-authority;
4. keep candidate memory from supplying raw commands/args/path/content; action arguments must come from current resident-owned state;
5. keep independent post-action verification mandatory for every influenced route;
6. use the first real learned alternative-action recovery path as a concrete consumer: A fails → genuinely different B succeeds → B independently verifies → later comparable reality may support B's pattern, but do not hardcode an A/B tactic rule;
7. then build practical Git mutation + diff/test/reality verification and GitHub repo/PR/CI sense as a strong engineering-competence benchmark;
8. establish browser/visual/mouse/keyboard Body/Senses before claiming learned computer-use competence;
9. add growth benchmarks proving familiar tasks reduce external cognition dependence without lowering verification quality;
10. keep remaining M8 updater/multi-OS/signing work explicit as bounded release debt and address it when a real continuity/security/data-integrity need appears.

The architecture driver remains:

> **The same persistent ZN Self must be able to finish hard work, prove from current reality that it is finished, and gradually internalize repeatedly verified competence so models become advisers for novelty rather than permanent owners of ability.**
