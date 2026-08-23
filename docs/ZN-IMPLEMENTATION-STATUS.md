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

The resident owns persistent Self/life, Situation/Thought/Will, nervous memory/reconsolidation, durable events/working state, multi-pulse Investigation, native Action/Body movement, bounded external cognition and zero-model continuity.

The execution/learning spine now has real CI verification for:

- structured read-only Git repository sense;
- exact text and explicit command postcondition verification;
- compact durable execution context;
- evidence-bound failed-action anti-replay;
- bounded restart-safe privacy-safe `VerifiedExperience` L1 records grounded only in independent Body verification;
- transparent L2 candidate procedural-tendency aggregation;
- read-only L3 current-reality applicability (`supported | mismatch | untested`);
- bounded L3 low-risk action influence over choices current ZN state already formed;
- bounded recovery across explicit structured alternatives after current evidence blocks an earlier option;
- the first **resident-owned bounded structured-choice formation** slice: for an append text movement, current Investigation may form a direct exact-state replacement alternative when the exact final text is semantically proven from current state;
- caller-free narrow exact-text postcondition derivation for append writes when Investigation has a complete current file observation;
- learning across that resident-formed choice, with append and replace evidence kept as distinct privacy-safe action variants so procedural evidence cannot silently cross the movement boundary.

The current transition is therefore:

```text
verified lived experience
→ repeated compatible evidence
→ candidate resident-owned tendency
→ current Situation applicability test             VERIFIED FIRST SLICE
→ bounded reality-gated action influence            VERIFIED FIRST SLICE
→ consume bounded structured alternatives           VERIFIED
→ form a narrowly proven resident-owned choice      VERIFIED FIRST SLICE
→ derive a narrow current postcondition              VERIFIED FIRST SLICE
→ learn from verified recovery                      VERIFIED FIRST SLICE
→ broader resident-owned tactic formation
→ mature procedural competence
→ familiar low-latency execution
→ prediction-error interrupt / relearning
```

The current choice/postcondition slice is deliberately narrow. It is not a general planner, free-text tactic inference, stored-action replay, mature skill system, broad autonomous alternative generator or general high-level postcondition synthesizer.

## 2. Verified core execution and learning spine

### 2.1 Structured read-only Git repository sense

Representative source:

```text
168579604157467bb2384f385849c621ca66cefe  feat: strengthen native Git repository sense
59957637a6840a6ce54e10b67ee5dc7bc0623867  test: isolate Git sense from resident sqlite files
```

Final first-slice CI: code/test SHA `47ccd5601462641c50c16ec76f2a05085a33f9f3`, run `32612456040`, Python and Electron success.

`NativeBody.git_state` returns structured root, branch, HEAD, upstream/ahead/behind, dirty state and bounded staged/unstaged/untracked/conflicted path evidence. This remains read-only repository sense; general Git mutation and GitHub maintenance are not claimed.

### 2.2 Reality-based postcondition verification

Representative source/test state:

```text
7a30baea6b4a2471479152e2843c50c0c7279997  feat: verify body postconditions before task completion
66f0fecc21b3cd7303c1f01b257095704f3454f4  feat: make post-action verification a resident thought stage
5cc0b1bccca976a8c635fbf3ddd7f95912a4cdc6  feat: verify explicit command postconditions
```

Exact non-append writes and explicit command postconditions are independently re-observed before completion. Verification survives restart; contradiction returns control to Investigation and records failure evidence. Command verification CI run `32621596489`: Python and Electron success.

The active runtime accepts explicit typed `text_equals` task postconditions and, in the narrow append slice described in 2.11, can also consume an exact-text postcondition derived by the resident from complete current file evidence. Neither path treats Body success as task proof; the final text is independently re-read.

### 2.3 Compact durable execution context

Code/test SHA `aaa6fa55c5c4e1968006f618a37260cb4f41675a`, run `32621878503`, Python and Electron success.

`WorkingState.execution_context` is bounded and carries active goal, stage, current gap, expected-outcome summary, current-action summary, latest verification, bounded verification history and failed-action summaries. It is not a plan tree.

### 2.4 Evidence-bound failed-action history

Code/test SHA `23ce3b42aad2d730afae4d60eb6af5d5b4bd1399`, run `32635668910`, Python and Electron success.

`native_action_failure_records` stores bounded action-signature hashes tied to stable Investigation evidence fingerprints. Same-action replay stays blocked under unchanged reality; A → B → A does not reopen A merely because B was attempted; substantive new facts can requalify prior movement; timestamps alone cannot; records survive restart; accepted external cognition text is not world evidence and cannot unlock a failed movement by itself.

### 2.5 L1 independently verified resident experience

Code/test SHA `80292975264df35ff3a999ed32c7973cdd3514f5`, run `32639405457`, Python and Electron success.

A `VerifiedExperience` is created only after independent Body verification. Positive and contradicted episodes are retained. Naked Body success, naked exit `0`, model text, report text and unsupported verification contracts cannot create positive learning. Raw task/gap text, commands, verification commands, paths/workdirs, content, output fragments and caller capability labels are excluded from persisted learned evidence.

### 2.6 L2 transparent candidate procedural tendencies

Code/test SHA `25ff0ada9efc8e8d830d085856edca7ea772a696`, run `32640409344`, Python and Electron success.

`VerifiedExperienceStore.candidate_tendencies()` derives bounded non-executable candidate state from L1 episodes. One event or same-event duplicates cannot fake repetition; support, contradiction, reliability, maturity and inhibition remain explicit; raw action arguments are not reconstructed; candidate state is derived rather than maintained as a second mutable skill database.

### 2.7 L3 read-only current-reality applicability

Code/test SHA `202b69e947db6c178d821c27e51fc1e61a90ce82`, run `32642408966`, Python and Electron success.

`procedural_applicability.py` returns only `supported`, `mismatch` or `untested`. Positive support requires a current independent stable reality anchor and no untested compared field. Request shape alone cannot create support. Applicability is reconstructed from L1/L2 plus current Investigation facts and is not written back into Investigation facts.

### 2.8 L3 bounded low-risk action influence

Code/test SHA `aec75ec2b2a2e37eae57a4a26011f324c1a823ff`, run `32643849526`, Python and Electron success.

The active constructor returns `ProcedurallyInfluencedResidentRuntime`, which remains inside the full `WorldAwareTransferResidentRuntime` hierarchy.

Authority remains deliberately small:

- procedural evidence only reorders current resident-owned intents; it does not construct or mutate args;
- only supported/practiced, non-inhibited, reliability `>= 0.75`, currently `supported` candidates can positively influence;
- mismatch/untested/immature/inhibited/revoked candidates have zero positive authority;
- the first positively influenced shape is exact non-append `write_text` with `text_equals` verification;
- commands, append writes and direct `structured_event` actions receive no positive procedural influence in this slice;
- evidence-bound anti-replay outranks familiarity;
- Body and independent verification ownership remain unchanged;
- failure/contradiction returns to Investigation and revokes the influenced route for the current event.

### 2.9 Bounded native structured-choice recovery

Code/test SHA `2632bcb2a6738c79a250205374d45a0d34bbad36`, run `32645416634`, Python and Electron success; container smoke skipped on normal push; status publisher success.

Source/test commits:

```text
3d1d7ebdce9c02224d4e836ef6c4c4d6df2758f7  feat: recover across bounded native choices
2632bcb2a6738c79a250205374d45a0d34bbad36  test: cover bounded native choice recovery
```

For an already-formed bounded choice set, current evidence may block earlier A and let deliberation continue to the first later unblocked B. No alternative or args are inferred from memory, free text, model output or failed-action history. Single explicit actions do not enter this path; all blocked choices fail closed.

### 2.10 Resident-owned exact-text structured-choice formation and learning

Final code/test SHA:

```text
920bd70814e44d9b62b6ba5159e264ab442470a3
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped on normal push
Publish commit statuses    success
run                         32647895984
```

Source/test commits:

```text
1cb9d6f3d716fadb9f4c1379c955d2284d901b0f  feat: form resident exact-text action choices
2da38f014f73f9f51224f5784fbc1e8853587a24  feat: align procedural applicability with exact-text goals
0d566d04f55dff7d9e967c49bf901c0d90dfce60  feat: recover resident-formed exact-text choices
5f10a4f5d60fb9c801ce53d400cba13ca1addee8  test: cover resident exact-text choice formation
920bd70814e44d9b62b6ba5159e264ab442470a3  test: prove resident choice learning loop
```

The first resident-owned choice-forming contract was introduced with an explicit exact-text task contract:

```text
current task already implies append write authority
+ typed expected_outcome(kind=text_equals, path, expected_text)
+ Investigation has complete, untruncated current file text
+ current_text + append_content == expected_text
→ current ZN cognition can form:
   A = incumbent append movement
   B = direct exact-state replace movement
```

Guarantees:

- both choices come from current event state plus current Investigation evidence;
- both are marked `resident_choice` and serve one exact final-state contract;
- free-text clauses do not create alternatives;
- a missing, truncated or mismatching file preview yields historical single-action behavior;
- a missing/mismatched target or incompatible path fails closed;
- the direct replacement content comes from current task/evidence, never from learned procedure arguments;
- `body_action` / `native_action` remains exclusive and caller-provided `native_action_options` still keeps its explicit contract;
- current declared/incumbent priority remains first until reality actually blocks it, unless a separately qualifying L3 tendency biases an already-formed alternative;
- failed-action anti-replay can move from failed resident A to resident B under the same evidence contract;
- selected B still goes through the existing Body and independent `text_equals` verification path;
- the learning store remains privacy-safe: candidate serialization does not contain raw target path or learned file contents.

The end-to-end regression proves a genuine learning consumer loop without a model planner:

```text
resident forms [append A, exact-replace B]
→ A fails in current environment
→ current evidence blocks A
→ resident recovers to B
→ Body performs B
→ independent read verifies exact final text
→ L1 VerifiedExperience
→ repeat across distinct events
→ supported L2 write/text_equals tendency
→ later comparable current file reality forms [A, B] again
→ L3 may bias current B
→ B still uses current path/content and independent verification
```

This is the first verified resident-owned bounded choice formation slice, not broad tactic synthesis. General resident-owned alternatives across commands, Git operations, browser actions or long-horizon goals remain incomplete.

### 2.11 Resident-derived append postcondition and write-variant safety

Final code/test SHA:

```text
04e95009a9b2277704d57bc3dd141748a91df772
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped on normal push
Publish commit statuses    success
run                         32648983622
```

Representative commits:

```text
1ca91c1c9937aad42e323b4dbcfbf8ee5d903922  feat: let resident carry derived action postconditions
dbb14b8291a7caab49f38069427e5a00c30e9099  feat: verify resident-derived text goals
275eebcc92f027d73572f09142d8393b381945ef  fix: separate text action variants in learning
32a147a4237540cb290cfa2a350f38add0236940  fix: preserve action variant in procedural tendency
a609f200f6e1380f2777febd4a271a03a1b33ec7  fix: gate procedural influence by write variant
2e33432204c39fe5486856381decc21f52a78e90  test: prove resident-derived append postconditions
91d94c1a6969b157e5749628eae7d63c2996c889  test: preserve legacy candidate fixtures while old records fail closed
04e95009a9b2277704d57bc3dd141748a91df772  test: enforce procedural write variants
```

The exact-text slice no longer requires the caller to supply the final `text_equals.expected_text` when the resident already has enough current evidence to compute it. The resident may derive one transient current-event postcondition only under this contract:

```text
current native movement == write_text append
+ append content is concrete and non-empty
+ Investigation has the complete, untruncated current file text
+ path evidence, when present, confirms an existing compatible file
→ derived exact final text = observed_current_text + current_append_content
→ NativeActionIntent carries that transient expected_outcome
→ resident may form [append A, exact-replace B]
```

The contract is deliberately fail-closed:

- missing file preview → no resident-derived exact final state;
- truncated file preview → no resident-derived exact final state;
- incompatible/missing observed file target → no derived alternative authority;
- an explicit task-level `expected_outcome` remains authoritative and is never overridden by resident derivation;
- derived postcondition state is current-event cognition, not learned procedure content;
- selected movement still requires independent `read_text` verification after Body returns success.

The learning boundary is also stricter. Exact-text L1 evidence now stores only a privacy-safe movement class, `action_variant = append | replace`. L1 grouping and L2 compatibility preserve that distinction. L3 checks the currently formed write variant before positive applicability: cross-variant evidence mismatches, and retained historical write evidence with no variant metadata becomes `untested` rather than silently gaining authority. Raw path/content remains excluded from learned procedure state.

New regression coverage proves both sides:

```text
no caller expected_outcome
→ current Investigation obtains complete file text
→ resident derives exact final state
→ append movement
→ independent read verifies exact final text
→ positive L1 episode marked append
```

and:

```text
append evidence != replace evidence at L2/L3
legacy write evidence without variant → untested
```

This is an ownership and safety hardening of the first exact-text tactic family. It is **not** the second genuinely different resident-owned tactic class, and it does not make general high-level postcondition derivation complete.

### 2.12 Resident-owned outbound channel media seam

Code/test SHA `018af2ec18abbac2a74e33f471101cb6a4308f36`, run `32645243684`, Python and Electron success.

`ResidentChannelSupervisor.nominate_outbound_media()` records a bounded JSON-safe media nomination only for an existing pending resident `channel_message` route. Delivery consumes this structured state; it never scans response text or inbound attachments for upload paths. Telegram authorizes nominated files against explicit resolved ZN-owned roots before any network request and currently transports them with `sendDocument`.

This is not yet autonomous artifact selection; Thought/Will/Investigation does not independently decide when to nominate an artifact.

## 3. Current core capability boundary

### Verified foundations

- persistent Self / zero-model resident life;
- durable event + `WorkingState` continuity;
- Situation / Thought / Will continuity;
- nervous memory, schemas and reality-gated reconsolidation;
- multi-pulse native Investigation with retained hypotheses/evidence/facts;
- native Action intents and Body action results;
- structured read-only Git repository sense;
- exact text and explicit independent command postcondition verification;
- narrow resident-derived exact append postcondition from complete current file observation;
- compact bounded current-event execution context;
- evidence-bound failed-action ledger and A → B → A replay suppression under unchanged reality;
- recovery across explicit or semantically proven resident-owned bounded choices after earlier choices are blocked;
- the first resident-owned exact-text alternative formation contract;
- blocked post-cognition movement cannot falsely complete;
- bounded restart-safe privacy-safe L1 `VerifiedExperience`;
- transparent L2 candidate tendencies with append/replace write variants kept distinct;
- L3 current-reality applicability with cross-variant write mismatch and legacy no-variant fail-closed behavior;
- bounded L3 bias among current choices for verified low-risk exact writes;
- verified learning from resident-formed recovery into later current-choice bias;
- contradiction revokes active event-local procedural influence and returns to Investigation;
- bounded external cognition returns as input to ZN rather than owning the resident loop;
- ZN-owned local process/terminal/PTTY and web search/extract paths;
- persistent work/thread/workspace/active-run state;
- resident-owned provider/settings/channel lifecycle;
- durable explicit outbound-media nomination plus policy-authorized Telegram document delivery.

### Still PARTIAL / MISSING

- a second genuinely different resident-owned structured alternative contract beyond exact-text file writing;
- broader resident-owned structured alternative formation from Will/Investigation beyond the exact-text proof slice;
- learned formation/recovery of genuinely different tactics across commands, Git, browser or long-horizon work;
- broad candidate influence over commands or arbitrary side effects;
- procedural replay of raw commands/paths/content;
- mature resident-owned skills and procedural fast paths;
- autonomous de-proceduralization beyond candidate inhibition + event-local route revocation;
- resident-owned reliable general high-level postcondition derivation beyond the narrow exact append proof;
- multi-step execution with genuinely different tactics over long horizons without a model-owned planner;
- durable completed-task verification/audit beyond current bounded learning evidence;
- safe Git mutation + diff/test/reality verification;
- GitHub repository/PR/CI resident-owned sense;
- clean browser Body/Senses seam;
- mature visual + mouse/keyboard application control;
- autonomous outbound artifact nomination from current Thought/Will/Investigation;
- Telegram photo/audio/video-specific outbound transports;
- learned engineering competence;
- learned computer-use competence;
- complex-task/learning-growth benchmarks;
- SM1+ self-maintenance implementation.

## 4. Product/runtime/release state

### Resident work loop

`ResidentWorkLedger` owns durable threads/messages, workspace association, active-work linkage/progress and bounded contextual file/diff/terminal artifacts beside kernel state. Renderer/localStorage is not authority.

Status: **M6 PARTIAL; core execution mainline active**.

### External cognition/settings

ZN-native OpenAI-compatible, Anthropic and Gemini resource adapters plus resident-owned provider/credential configuration remain active. Missing credentials degrade cognition rather than killing the resident.

Status: **M2 complete for active main provider families**.

### Local Body

Filesystem/process/terminal/PTTY paths are ZN-owned. Verification, failed-action anti-replay and L1/L2/L3 learning evidence are active. Exact-text current-state semantics can form one bounded resident-owned alternative pair. For append writes, complete current file evidence is now enough for the resident itself to derive the exact final-state verification contract; write learning keeps append and replace variants separate. General tactic formation and mature procedural competence remain incomplete.

### Web/world / visual sense

ZN-owned search/extract providers and URL/network safety are active. Resident-owned visual sensing foundations are tested. A clean browser automation seam and mature screen/mouse/keyboard control are not yet claimed.

### Communication

Resident-owned channel lifecycle and Telegram text/inbound media are active. The first outbound-media slice is active with durable nomination and path-policy authorization. Autonomous artifact selection and media-specific method selection remain pending.

### Desktop/UI

Independent ZN Electron main, preload, renderer/workbench and `zn://` are active. M4 is complete and M5/M6 are materially advanced. Pure UI polish remains paused during the core-first phase.

### M1 runtime ownership

Status: **COMPLETE for active packaged resident path**.

The independent `runtime/python` distribution is `znagent`, installed package `zn_agent`, entrypoint `zn-resident`. Packaged runtime rejects inherited `hermes_cli` and boots zero-model. `runtime/python/pyproject.toml` maps `zn_agent.core` directly to `../../agent/kernel`, so current kernel code is the packaged runtime source rather than a second copy.

Run `32648983622` installed the isolated runtime distribution, booted it without a model, compiled the resident kernel and ran full kernel unittest discovery successfully.

### M7 formal artifact ownership

Status: **ARTIFACT SHAPE VERIFIED** on exercised targets:

```text
Linux   x86_64   AppImage / deb / rpm
Windows x64      NSIS / MSI
macOS   arm64    DMG / ZIP
```

This does not imply signing/notarization or complete release readiness.

### M8 continuity evidence

Status: **IN PROGRESS / bounded release lane**.

Verified Linux clean install: run `32591603017`.

Verified installed Linux autostart: run `32593886026`.

Verified source-level N → N+1 continuity: run `32596442626`.

Real AppImage successor run `32645354818` reached a terminal **cancelled** result for the `Real AppImage N to N+1` job. Both `Build real N AppImage` and `Build real N+1 AppImage` succeeded, while `Run real installed AppImage updater continuity smoke` was cancelled. Diagnostic capture, artifact upload and status publication succeeded. Therefore installed AppImage N → N+1 updater continuity is **not verified** and this remains an M8/updater-lane investigation item.

Still separate release gates include successful installed application updater continuity, Windows/macOS clean-install/login continuity for the intended release matrix, and signing/notarization when operationally configured.

## 5. Milestone snapshot

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

## 6. Immediate next development sequence

1. keep `VerifiedExperience`, transparent candidate evidence and current independent Investigation facts as procedural-learning truth; current reality always outranks familiarity;
2. keep resident-owned exact-text postcondition derivation restricted to semantic proofs from complete current evidence rather than turning it into free-text goal synthesis;
3. find a **second semantically provable, genuinely different tactic class** from current Will/Investigation rather than another file-write representation;
4. prefer contracts with an independent current-world verifier; command/Git engineering work is a useful target only when equivalence and side-effect boundaries can be proven without guessing from command text;
5. do not let external model output or stored procedural memory own the choice set or supply raw action args;
6. preserve current influence gates, action-variant separation, evidence-bound anti-replay and mandatory independent verification;
7. add negative tests before each authority expansion: missing evidence, stale evidence, ambiguous goal equivalence, unsafe side effect and contradiction must fail closed;
8. use practical Git mutation + diff/test/reality verification and GitHub repo/PR/CI sense as the engineering-competence benchmark once the next choice contract is semantically defensible;
9. establish browser/visual/mouse/keyboard Body/Senses before claiming learned computer-use competence;
10. add growth benchmarks proving familiar tasks reduce external cognition dependence without lowering verification quality;
11. keep M8 updater/multi-OS/signing work explicit as bounded release debt until a real continuity/security/data-integrity need makes it the active lane.

The architecture driver remains:

> **The same persistent ZN Self must be able to finish hard work, prove from current reality that it is finished, and gradually internalize repeatedly verified competence so models become advisers for novelty rather than permanent owners of ability.**
