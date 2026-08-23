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
- resident-owned exact-text choice formation: append versus direct exact-state replacement when current file evidence proves equivalent final text;
- caller-free narrow exact-text postcondition derivation for append writes when Investigation has a complete current file observation;
- a second genuinely different resident-owned semantic tactic family: bounded single-path Git staging via porcelain `git add` versus plumbing `git update-index --add`, formed only from a typed staging goal plus current Git/path evidence;
- recovery from a failed first Git tactic to the second under unchanged reality evidence;
- fresh structured `git_state` post-action verification for that Git goal;
- privacy-safe L1/L2 learning that keeps the two Git staging variants distinct without persisting raw path or command authority;
- native terminal resolution when the typed Git staging goal is already proven satisfied by current structured Git/path reality, with no mutation/model fallback;
- Git-specific L3 applicability that re-proves the current typed goal, root, target/path identity and exact resident-formed action variant before positive influence;
- active learned Git staging bias that can reorder only the current freshly re-formed `git_add` / `git update-index` choices and still requires fresh `git_state` verification;
- one canonical Git staging renderer shared by action formation and semantic proof, including quoted repository-relative paths;
- read-only Investigation applicability diagnostics aligned with active Git L3 current facts, causal domain contract and the complete freshly formed current choice set.

The current transition is therefore:

```text
verified lived experience
→ repeated compatible evidence
→ candidate resident-owned tendency
→ current Situation applicability test             VERIFIED WRITE + FIRST GIT SLICE
→ bounded reality-gated action influence            VERIFIED WRITE + FIRST GIT SLICE
→ consume bounded structured alternatives           VERIFIED
→ form resident-owned semantic choices              VERIFIED TWO TACTIC FAMILIES
→ learn from independently verified recovery        VERIFIED
→ already-satisfied Git goal terminal resolution    VERIFIED
→ Git-specific reality-gated learned choice bias    VERIFIED FIRST GIT SLICE
→ shared formation/diagnostic semantic contract     VERIFIED FIRST GIT SLICE
→ broader resident-owned engineering competence
→ familiar low-latency execution
→ prediction-error interrupt / relearning
```

The current tactic slices remain deliberately narrow. They are not a general planner, free-text tactic inference, stored-action replay, mature skill system, arbitrary command equivalence engine or general high-level postcondition synthesizer.

## 2. Verified core execution and learning spine

### 2.1 Structured read-only Git repository sense

Representative source:

```text
168579604157467bb2384f385849c621ca66cefe  feat: strengthen native Git repository sense
59957637a6840a6ce54e10b67ee5dc7bc0623867  test: isolate Git sense from resident sqlite files
```

Final first-slice CI: code/test SHA `47ccd5601462641c50c16ec76f2a05085a33f9f3`, run `32612456040`, Python and Electron success.

`NativeBody.git_state` returns structured root, branch, HEAD, upstream/ahead/behind, dirty state and bounded staged/unstaged/untracked/conflicted path evidence. The sense itself remains read-only; the newer bounded staging mutation contract is documented separately in 2.12 and does not make general Git mutation complete.

### 2.2 Reality-based postcondition verification

Representative source/test state:

```text
7a30baea6b4a2471479152e2843c50c0c7279997  feat: verify body postconditions before task completion
66f0fecc21b3cd7303c1f01b257095704f3454f4  feat: make post-action verification a resident thought stage
5cc0b1bccca976a8c635fbf3ddd7f95912a4cdc6  feat: verify explicit command postconditions
```

Exact non-append writes and explicit command postconditions are independently re-observed before completion. Verification survives restart; contradiction returns control to Investigation and records failure evidence. Command verification CI run `32621596489`: Python and Electron success.

The active runtime accepts explicit typed `text_equals` task postconditions and, in the narrow append slice described in 2.11, can also consume an exact-text postcondition derived by the resident from complete current file evidence. Neither path treats Body success as task proof; the final text is independently re-read. The Git staging slice in 2.12 likewise treats the primary command result only as movement evidence and requires a separate structured `git_state` observation before completion.

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

Initial code/test SHA `202b69e947db6c178d821c27e51fc1e61a90ce82`, run `32642408966`, Python and Electron success.

`procedural_applicability.py` returns only `supported`, `mismatch` or `untested`. Positive support requires a current independent stable reality anchor and no untested compared field. Request shape alone cannot create support. Applicability is reconstructed from L1/L2 plus current Investigation facts and is not written back into Investigation facts.

The current Git staging extension is also reality-gated. A Git candidate can only be evaluated for positive use after `git_semantics.py` re-proves that the exact current `resident_choice` command was freshly reconstructed from the same typed `git_path_staged` goal and current Git/path facts. It then requires the matching action variant plus privacy-safe target/root fingerprints to match independently observed current path and Git-root facts. Missing facts, cross-target reuse, path identity mismatch, corrupted commands and non-resident command sources fail closed.

Final first Git-L3 code/test SHA `f4d780d8af708c4136dd5b88c0f37eeb8b561a8e`, run `32652858740`, Python and Electron success.

The consistency cleanup is verified by code/test SHA `22e1abde5cd5e1bc228d19a7d09eff6d2f9c8cc8`, run `32654830857`, Python and Electron success. Active influence and read-only Investigation diagnostics now share one current Git applicability-domain helper. Diagnostics pass current facts into the same expected-outcome proof and inspect the complete current resident-formed choice set, so a mature B candidate is not falsely compared only against default A. This remains observational only; it does not select or execute an action.

### 2.8 L3 bounded low-risk action influence

Initial code/test SHA `aec75ec2b2a2e37eae57a4a26011f324c1a823ff`, run `32643849526`, Python and Electron success.

The active constructor returns `ProcedurallyInfluencedResidentRuntime`, which remains inside the full `WorldAwareTransferResidentRuntime` hierarchy.

Authority remains deliberately small:

- procedural evidence only reorders current resident-owned intents; it does not construct or mutate args;
- only supported/practiced, non-inhibited, reliability `>= 0.75`, currently `supported` candidates can positively influence;
- mismatch/untested/immature/inhibited/revoked candidates have zero positive authority;
- exact non-append `write_text` with `text_equals` remains the first positively influenced shape;
- the only command-side exception is the bounded current `resident_choice` `git_path_staged` family after the Git-specific current-reality proof succeeds;
- generic commands, append writes and direct `structured_event` actions still receive no positive procedural influence;
- Git procedural memory never supplies command/path/workdir/args or creates a new choice; it may only reorder the current `git_add` / `git update-index --add` intents already formed from current goal/evidence;
- evidence-bound anti-replay outranks familiarity;
- Body and independent verification ownership remain unchanged;
- failure/contradiction returns to Investigation and revokes the influenced route for the current event.

The first Git-L3 active learning loop is verified by run `32652858740`; the shared applicability/diagnostic consistency contract is re-verified by run `32654830857`. Neither widens authority to commit, push, reset, checkout, branch mutation or arbitrary shell commands.

### 2.9 Bounded native structured-choice recovery

Code/test SHA `2632bcb2a6738c79a250205374d45a0d34bbad36`, run `32645416634`, Python and Electron success; container smoke skipped on normal push; status publisher success.

Source/test commits:

```text
3d1d7ebdce9c02224d4e836ef6c4c4d6df2758f7  feat: recover across bounded native choices
2632bcb2a6738c79a250205374d45a0d34bbad36  test: cover bounded native choice recovery
```

For an already-formed bounded choice set, current evidence may block earlier A and let deliberation continue to the first later unblocked B. No alternative or args are inferred from memory, free text, model output or failed-action history. Single explicit actions do not enter this path; all blocked choices fail closed.

This same recovery mechanism now has an end-to-end Git proof: a synthetic Body failure on current porcelain staging A leaves the repository unchanged, evidence-bound anti-replay blocks A, resident action formation re-creates the same semantic choices, plumbing B remains admissible, real Body execution stages the path, and a fresh Git observation verifies the final index state.

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

This is the first verified resident-owned bounded choice formation slice, not broad tactic synthesis.

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

This is an ownership and safety hardening of the first exact-text tactic family.

### 2.12 Resident-owned bounded single-path Git staging tactics and first Git L3 competence

Initial tactic-family code/test SHA:

```text
7ec9725e9a2c9926adce36ec2d1ac8cfc9df926c
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped on normal push
Publish commit statuses    success
run                         32650706582
```

Representative initial commits:

```text
3df9fd78b7c41e38a36502e0ed429793e02f6b26  feat: define bounded git staging semantics
60e34a73890b13819e3777e9b4977a6b39a6ef1a  refactor: centralize bounded git stage commands
4cc04da8d8228991551e40366e8e3693b3824dab  feat: verify resident git staging choices
4e24fa7eac5e8e69a3a89ce676b8d24a23bb2963  feat: learn verified git staging variants
3a28a6aaa1310c53bb525df1ed0456e57cf474d4  test: prove resident git staging choices
da912358b98530c61d951e2098a64262bdf083b1  test: prove git staging tactic recovery
294f67100cd9d6a042873c8e0f854e7ec0c13110  fix: revalidate persisted git staging identity
7ec9725e9a2c9926adce36ec2d1ac8cfc9df926c  test: cover git staging identity contract
```

The second genuinely different resident-owned semantic tactic family is deliberately one narrow Git mutation goal:

```text
explicit typed expected_outcome(kind=git_path_staged, path)
+ current Investigation has structured Git root/status evidence
+ current path evidence confirms one existing regular file
+ target resolves lexically and physically inside the observed repo root
+ no symlink/path-identity ambiguity
+ target is unstaged or untracked
+ target is not conflicted
→ resident forms:
   A = porcelain  git add -- <current repo-relative path>
   B = plumbing   git update-index --add -- <current repo-relative path>
```

Important authority boundaries:

- free text, model output and procedural memory do not construct these choices or supply their path/command args;
- the command is a canonical rendering of the current resident-owned variant and current repository-relative target;
- persisted `root/path/relative_path` identity is revalidated before verification, so a corrupted or mismatched working-state contract fails closed;
- missing Git facts, missing path facts, outside-root targets, incompatible targets and conflicts do not create a mutation choice;
- this slice does not authorize commit, push, reset, checkout, branch mutation or arbitrary shell mutation;
- Body command success is not task completion.

Independent verification is:

```text
selected Git staging movement
→ Body command result
→ fresh Body git_state(root)
→ target must be staged
→ target must not remain unstaged
→ target must not be untracked
→ target must not be conflicted
→ only then complete / positive learning
```

Recovery is proven end to end. A failed porcelain A under unchanged current reality becomes an evidence-bound failed action; resident formation reconstructs the same current semantic choice set; A remains blocked by its stable `{kind,args}` signature; plumbing B remains admissible; B stages the file; fresh `git_state` verifies the postcondition.

L1 learning stores only privacy-safe target/root fingerprints, `action_variant = git_add | git_update_index`, and bounded structured verification booleans. Raw path and command are not persisted as learned authority. Existing L2 compatibility/grouping keeps the variants separate.

The next stage is now also verified by final code/test SHA:

```text
f4d780d8af708c4136dd5b88c0f37eeb8b561a8e
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped on normal push
Publish commit statuses    success
run                         32652858740
```

Stage commits:

```text
c9907cd0f255a15a23e08d46984e3291292a5aab  feat: prove current git staging intent semantics
acbe5ca90dcec7d29f4ccd81d53eca2294379d7a  fix: resolve already satisfied git staging goals
8fd6bfd6b192b690edcaf81e90743f768790af46  feat: gate git procedural applicability by current reality
6288dd5325feba6a7610e86dd513a2f0632b9c61  feat: allow bounded git procedural choice bias
ff441db284891e245e492a24b643631a68de3694  test: prove already satisfied git staging resolution
740eea462c005a545e521711a687c3b226932f31  test: prove reality gated git procedural influence
7191b94875ee7f733d014dc08ed8a06bbd4c56b0  test: prove active learned git variant bias
f4d780d8af708c4136dd5b88c0f37eeb8b561a8e  fix: align git procedural domain contract
```

Already-satisfied resolution now uses the same current semantic truth. If fresh structured evidence proves the target is exclusively staged, Investigation terminal-resolves the typed goal without forming a mutation, without calling a model and without manufacturing a positive learning episode. Staged+unstaged, conflict, missing Git evidence or missing path evidence do not qualify.

For positive Git L3 influence, `current_git_stage_intent_goal(...)` re-derives the current typed goal from current Git/path facts, revalidates root/path/relative identity, and requires the current `resident_choice` command/workdir to equal the canonical rendering for the carried variant. Only then may privacy-safe L2 target/root fingerprints and action variant be compared against current independently observed target/root reality.

Positive authority remains choice bias, not command replay. The active integration proof deliberately trains one path across three distinct events by making porcelain A fail without mutating the repository, recovering to plumbing B, verifying B through fresh Git state and accumulating three verified B episodes. On the fourth current event the resident re-observes reality, freshly re-forms `[A, B]`, and the supported B tendency reorders those current choices to B. It executes one real B command, verifies the final Git state and completes with zero model invocations. Memory never supplies the path, workdir or command.

One real intermediate CI failure was preserved as evidence: SHA `7191b94875ee7f733d014dc08ed8a06bbd4c56b0`, run `32652606569`, had Electron success and one Python failure because L1 stored the event `required_capabilities` contract while active L3 compared SelfModel-expanded parent domains. The fix keeps the stronger exact causal-domain contract by using the same typed current event capability representation for this Git family; it does not weaken target/root/reality matching. Final run `32652858740` is green.

A follow-up implementation-consistency stage is verified by code/test SHA:

```text
22e1abde5cd5e1bc228d19a7d09eff6d2f9c8cc8
ZN Kernel / Python          success
Electron / TypeScript      success
Container / Runtime Smoke  skipped on normal push
Publish commit statuses    success
run                         32654830857
```

Relevant commits in that code/test range:

```text
45625637c1b69201a0ff9241753ef6c8223da831  refactor: centralize git staging command formation
37284d441a1eabf6d20a358354501510a82fa2e1  refactor: share current procedural applicability context
88e89b0b0df31150eeeae58e64490c1c48cef709  refactor: reuse procedural applicability domains
094f21327a15c32dbbb4312993106ee39f663a15  fix: align procedural diagnostic with current choices
65972d38675481161e1212f2a4c675ddc4cce558  test: align git applicability diagnostics with active semantics
22e1abde5cd5e1bc228d19a7d09eff6d2f9c8cc8  fix: preserve vision luminance diagnostic
```

Action formation now calls the same `git_stage_command(...)` renderer trusted by semantic verification rather than duplicating shell quoting. The regression covers a repository-relative path containing a space and checks both current variants against the canonical renderer. Active L3 and the read-only Investigation evidence surface now share the same current applicability-domain helper; the diagnostic passes current facts into Git expected-outcome proof and evaluates a candidate across all current resident-formed choices rather than only default A. A parent domain added by SelfModel therefore does not create a false Git causal mismatch, while generic command authority remains unchanged. The temporary accidental omission of the unrelated visual `luminance` fact during this refactor was caught by diff review and restored before the final code/test SHA; final diff preserves the pre-existing vision contract.

### 2.13 Resident-owned outbound channel media seam

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
- resident-owned exact-text append/replace alternative formation;
- resident-owned single-path Git staging alternatives using two distinct Git mechanisms;
- already-satisfied typed Git staging goal terminal resolution from current structured reality;
- fresh structured Git post-action verification for the bounded staging goal;
- canonical Git staging command formation shared with current semantic proof;
- blocked post-cognition movement cannot falsely complete;
- bounded restart-safe privacy-safe L1 `VerifiedExperience`;
- transparent L2 candidate tendencies with write and Git action variants kept distinct;
- L3 current-reality applicability with write-variant safety and a Git-specific current typed-goal/root/target/variant reality gate;
- bounded L3 bias among current choices for verified low-risk exact writes and the first bounded resident-owned Git staging family;
- read-only procedural diagnostics aligned with the same current facts/domain semantics and complete current choice set used by Git L3;
- verified learning from resident-formed recovery;
- active four-event zero-model Git proof where mature B evidence reorders only freshly re-formed current A/B choices;
- contradiction revokes active event-local procedural influence and returns to Investigation;
- bounded external cognition returns as input to ZN rather than owning the resident loop;
- ZN-owned local process/terminal/PTTY and web search/extract paths;
- persistent work/thread/workspace/active-run state;
- resident-owned provider/settings/channel lifecycle;
- durable explicit outbound-media nomination plus policy-authorized Telegram document delivery.

### Still PARTIAL / MISSING

- broader resident-owned structured alternative formation beyond exact-text and single-path Git staging;
- learned formation/recovery of broader tactics across commands, browser or long-horizon work;
- broad candidate influence over commands or arbitrary side effects;
- procedural replay of raw commands/paths/content (intentionally prohibited rather than a target capability);
- mature resident-owned skills and general procedural fast paths;
- autonomous de-proceduralization beyond candidate inhibition + event-local route revocation;
- resident-owned reliable general high-level postcondition derivation beyond current narrow typed proofs;
- multi-step execution with genuinely different tactics over long horizons without a model-owned planner;
- durable completed-task verification/audit beyond current bounded learning evidence;
- practical broader Git mutation + diff/test/reality verification;
- Git commit/push/reset/checkout/branch mutation authority;
- GitHub repository/PR/CI resident-owned sense;
- clean browser Body/Senses seam;
- mature visual + mouse/keyboard application control;
- autonomous outbound artifact nomination from current Thought/Will/Investigation;
- Telegram photo/audio/video-specific outbound transports;
- mature learned engineering competence beyond the current staging tactic proof;
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

Filesystem/process/terminal/PTTY paths are ZN-owned. Verification, failed-action anti-replay and L1/L2/L3 learning evidence are active. Resident cognition can form two proven bounded tactic families: exact-text append/replace and single-path Git staging via porcelain/plumbing mechanisms. Git staging uses one canonical current renderer, can terminal-resolve an already-satisfied current goal, can consume the first Git-specific reality-gated learned choice bias, exposes aligned read-only applicability evidence, and still requires a fresh structured Git verifier. General tactic formation and mature engineering procedural competence remain incomplete.

### Web/world / visual sense

ZN-owned search/extract providers and URL/network safety are active. Resident-owned visual sensing foundations are tested. A clean browser automation seam and mature screen/mouse/keyboard control are not yet claimed.

### Communication

Resident-owned channel lifecycle and Telegram text/inbound media are active. The first outbound-media slice is active with durable nomination and path-policy authorization. Autonomous artifact selection and media-specific method selection remain pending.

### Desktop/UI

Independent ZN Electron main, preload, renderer/workbench and `zn://` are active. M4 is complete and M5/M6 are materially advanced. Pure UI polish remains paused during the core-first phase.

### M1 runtime ownership

Status: **COMPLETE for active packaged resident path**.

The independent `runtime/python` distribution is `znagent`, installed package `zn_agent`, entrypoint `zn-resident`. Packaged runtime rejects inherited `hermes_cli` and boots zero-model. `runtime/python/pyproject.toml` maps `zn_agent.core` directly to `../../agent/kernel`, so current kernel code is the packaged runtime source rather than a second copy.

Run `32654830857` installed the isolated runtime distribution, booted it without a model, compiled the resident kernel and ran full kernel unittest discovery successfully.

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
2. preserve the now-shared Git staging renderer/current applicability contracts, already-satisfied terminal resolution, current-goal/root/target/variant proof, current-only choice bias, fresh `git_state` verification, anti-replay and event-local revocation as hard invariants;
3. extend practical engineering competence toward one bounded Git mutation → diff/test/current-reality verification loop only where effect and verifier semantics are explicit; do not infer arbitrary shell-command equivalence from text;
4. add negative tests before every authority expansion: stale/missing evidence, ambiguous identity/equivalence, cross-target reuse, unsafe side effects and contradiction must fail closed;
5. keep generic command positive authority prohibited unless a future semantic family independently proves current authority and verification;
6. add GitHub repo/PR/CI resident-owned sense when it has a concrete current-world consumer; do not make GitHub another cognitive agent;
7. establish browser/visual/mouse/keyboard Body/Senses before claiming learned computer-use competence;
8. add growth benchmarks proving familiar tasks reduce external cognition dependence without lowering verification quality;
9. keep M8 updater/multi-OS/signing work explicit as bounded release debt until that lane is deliberately activated.

The architecture driver remains:

> **The same persistent ZN Self must be able to finish hard work, prove from current reality that it is finished, and gradually internalize repeatedly verified competence so models become advisers for novelty rather than permanent owners of ability.**