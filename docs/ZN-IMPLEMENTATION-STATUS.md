# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Source-extraction contract: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Current core-development direction: [`ZN-NEXT-PHASE.md`](ZN-NEXT-PHASE.md)
>
> This file records **what is actually implemented now**. Code remains authoritative over this ledger.
>
> Active development branch: `dev/zn-agent`. `main` remains untouched until the explicit promotion milestone in `ZN.md`.

## Core execution mainline checkpoint — 2026-08-23

Development priority is now **durable ZN Self + mature complex-task execution depth + reality verification**. UI/desktop polish is paused; release/M8 remains a bounded continuity/release lane.

### Verified structured Git repository sense

Verified source includes:

```text
168579604157467bb2384f385849c621ca66cefe  feat: strengthen native Git repository sense
59957637a6840a6ce54e10b67ee5dc7bc0623867  test: isolate Git sense from resident sqlite files
47ccd5601462641c50c16ec76f2a05085a33f9f3  test: require reality verification after native writes
```

Real CI for the final first-slice source state:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32612456040
```

The active embodied path now observes Git through `NativeBody.git_state`, with structured repository evidence including root, branch, full/short HEAD, detached state, upstream, ahead/behind, dirty state, unique changed paths, staged/unstaged/untracked/conflicted paths and bounded porcelain status. This remains read-only repository sense; it is **not** yet general Git mutation or GitHub maintenance capability.

### Verified action → reality verification

The same CI run `32612456040` proves the first resident-owned post-action verification contract for exact non-append text state:

```text
native investigation
→ NativeActionIntent(write_text)
→ Body write succeeds
→ event does NOT complete
→ durable native_verification stage
→ verify_action Thought
→ Body re-reads current reality
→ exact postcondition match
→ only then complete
```

The verification stage survives a resident restart. If current reality contradicts the requested text state, the resident records the failed postcondition, returns to investigation and blocks blind replay of the identical movement.

### Verified explicit command postconditions

Final source state for the next slice:

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

An event may now provide a structured `expected_outcome` command check. The primary command returning successfully is only action evidence. The resident persists the postcondition, forms a later `verify_action` Thought, runs an independent verification command through its own Body, compares observed exit code/output with the expected state and completes only when the postcondition is verified.

The verified contract includes:

- explicit expected verification command;
- expected exit code, default `0`;
- optional required output fragments;
- verification workdir/timeout/output bounds;
- restart continuity between primary action and verification;
- failed verification → durable failure evidence → native investigation;
- identical primary command is not blindly replayed after the failed postcondition;
- verification contradiction is surfaced directly in the next `CognitiveSituation` / Thought instead of remaining hidden only in `WorkingState`.

This does **not** mean arbitrary shell success now proves arbitrary high-level goals. Generic task-level postcondition derivation, multi-step goal/subgoal completion semantics and long-horizon recovery remain incomplete.

### Current core capability boundary

Verified foundations now include:

- persistent Self / resident life and zero-model continuity;
- durable event + `WorkingState` continuity across pulses/restarts;
- multi-pulse native Investigation with retained hypotheses/evidence/facts;
- native Body action intents and failed-action feedback;
- structured read-only Git repository sense;
- exact text state post-action verification;
- explicit independent command postcondition verification;
- immediate Situation/Thought awareness of a contradicted verification;
- bounded external cognition that returns as input to ZN rather than becoming the task owner.

Still PARTIAL / MISSING on the core mainline:

- reliable resident-owned derivation/maintenance of high-level task postconditions;
- multi-step goal/subgoal execution that can change tactics over many actions without becoming a model-owned planner;
- durable completed-task verification evidence as a first-class audit object rather than relying on the event outcome plus retained Body action history;
- broader failure recovery and alternative-action formation after verification contradiction;
- safe Git mutation + diff/test/reality verification;
- GitHub repository/PR/CI resident-owned read sense;
- browser body/sense;
- mature visual + mouse/keyboard application control;
- real complex-task benchmark suite;
- SM1+ self-maintenance implementation.

## Verified implementation baseline

M7 has real installer-content/runtime evidence on the three current intended OS families:

```text
Linux   x86_64   AppImage / deb / rpm
Windows x64      NSIS / MSI
macOS   arm64    DMG / ZIP
```

M8 has two deliberately scoped installed-Linux proofs plus source-level N → N+1 continuity regressions. The installed proofs cover fresh `.deb` installation and systemd user login/start-stop-start continuity. The N → N+1 regressions prove that versioned runtimes materialize side-by-side under the same ZN home, queued/claimed resident work keeps a runtime mismatch pending instead of idle, and an idle resident can gracefully retire N and start N+1 against the same durable self/work store.

This is not complete M8/release validation. A full desktop/application updater handoff gate, Windows/macOS clean-install/login coverage, signing/notarization and any additional release architectures remain separate gates.

### Linux M8 clean-install evidence

Verified source:

```text
6e980ac2fe46a0680751dd55711ac53749419a14  test: validate clean Linux ZN installation
```

CI:

```text
ZN Kernel / Python             success
Electron / TypeScript         success
ZN Linux Clean Install Smoke  success
clean-install run              32591603017
clean runner                   Ubuntu 24.04.4 LTS
```

The gate deliberately used separate build/install runners:

```text
build runner
→ locked npm workspace
→ stage self-contained portable CPython + znagent
→ zero-model staging smoke
→ build ZN desktop
→ electron-builder.zn.yml --linux deb
→ upload only ZN-0.17.0-linux-amd64.deb

fresh Ubuntu runner (no checkout)
→ download only built deb
→ apt-get install local deb
→ verify dpkg/system-installed ZN identity
→ verify installed desktop integration
→ locate /opt/ZN/resources/zn-runtime
→ boot resident with installed embedded Python and no external model
```

The clean-install build produced:

```text
ZN-0.17.0-linux-amd64.deb
sha256 52d291538bee80e56d580eea05487926841fb9aa6a93de29c4083bac6dc618f9
Package: zn-desktop
Version: 0.17.0
Architecture: amd64
```

The second runner proved an actual package installation:

```text
dpkg state       install ok installed
installed package zn-desktop 0.17.0 amd64
app root          /opt/ZN
system command    /usr/bin/ZN → /opt/ZN/ZN via update-alternatives
embedded Python   /opt/ZN/resources/zn-runtime/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11
embedded backend  /opt/ZN/resources/zn-runtime/python/cpython-3.11.15-linux-x86_64-gnu/lib/python3.11/site-packages
```

Installed desktop integration remained ZN-owned:

```text
Name=ZN
StartupWMClass=ai.zn.desktop
MimeType=x-scheme-handler/zn;
```

The gate also rejected inherited install-stamp/Hermes identity and packaged `hermes_cli`. The resident was constructed using the installed embedded Python under isolated mode and reported:

```text
clean installed resident pulse=1 mode=observing
external_brains == ()
```

The temporary clean-install workflow was removed after successful evidence in:

```text
1e5b2490a75eacfa5ec2c2e3240e6f9b1d015a05  test: finalize Linux clean-install validation
```

### Linux M8 installed autostart evidence

Verified source:

```text
6cc8becea3d97eea09c0887cd5c70612fc9ee573  fix: gracefully stop resident on SIGTERM
```

Normal CI:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32593886005
```

The kernel suite includes a real POSIX subprocess regression: it launches `agent.kernel.resident_server`, waits until both endpoint and SQLite resident lease exist, sends SIGTERM, then requires exit code `0`, endpoint retirement and deletion of the resident lease before process exit.

The scoped installed-package gate also succeeded:

```text
ZN Linux Autostart Smoke  success
run                        32593886026
fresh runner               Ubuntu 24.04.4 LTS
```

This proves the current Linux installed OS-login/start-stop-start continuity slice. It does not prove the complete N → N+1 desktop/application handoff, Windows/macOS login behavior, equivalent clean installation on those platforms, signing/notarization or a final release matrix.

### M8 N → N+1 continuity regression evidence

Verified source:

```text
eb1d1874f1d24dae9ceb74635886615368166ce1  fix: defer runtime handoff for queued resident work
1efa019222d215e077af1fae92b9cb564c4f89d0  test: cover resident runtime handoff state in CI
f0a829b618d931f6f5e40bf314fda592783db6c9  test: prove packaged runtimes coexist across upgrades
91a6b500274e0cc0f64be54839e51f5c377a1c16  test: prove idle resident runtime continuity
b79c94c67f5ef19af8c0a8e4ba0d9e9877a400f3  test: align runtime continuity with work snapshot contract
```

Normal CI for the final source state:

```text
ZN Kernel / Python      success
Electron / TypeScript  success
run                     32596442626
```

The active desktop call chain is exercised around the runtime-state boundary. Resident `status()` reports durable SQLite-backed `queue_depth`; `describeZnResidentRuntime` treats a nonzero durable queue as busy before transient working/situation state. Claimed/processing work remains covered by `working_state.current_event_id`.

The packaged-runtime regression proves N and N+1 can coexist under the same ZN home, and the kernel subprocess regression proves an idle N can retire cleanly before N+1 starts while living-self identity fields and durable work history persist.

This is still not the final installed desktop/updater gate.

### macOS M7 evidence

Verified source:

```text
518d233eafa39b2d12f2de5835a8c8c1ab7529ab  test: make macOS installer extraction runner-compatible
```

CI:

```text
ZN Kernel / Python          success
Electron / TypeScript      success
ZN macOS Installer Smoke   success
macOS smoke run             32591343670
runner                      macos-26-arm64
```

Real DMG/ZIP payloads preserved `ai.zn.desktop`, ZN app identity, only `zn://`, self-contained `zn_agent` runtime and zero-model resident boot. The build was unsigned and notarization was skipped because Apple credentials were not configured; signing/notarization is not claimed.

### Windows M7 evidence

Verified source:

```text
2e3cdb0ac893feca86325e19a058c455c906bfd7  test: make MSI extraction deterministic
```

Validation:

```text
ZN Kernel / Python            success
Electron / TypeScript        success
ZN Windows Installer Smoke   success
Windows smoke run             32590239803
```

Real NSIS/MSI payloads preserved ZN PE/package identity and self-contained zero-model resident boot.

### Linux M7 evidence

Verified source points:

```text
6219eaa61f6c444feb96864e149f886752b00ffe  real AppImage/deb/rpm installer payload validation
46685b66ff1381cb0b41b1e0564cc62ca5e34467  corrected AppImage desktop integration validation
```

Real AppImage/deb/rpm payloads preserved ZN identity, `zn://`, embedded ZN runtime and zero-model resident boot.

## Current development checkpoint

The active product boundary is ZN-owned across resident runtime, cognition resources, local terminal/PTTY, web sensing, communication lifecycle, Electron main/preload/protocol, React workbench and formal desktop package/build identity.

M5/M6 currently has resident-backed durable work/thread/workspace/progress plus contextual file/diff/terminal artifacts and resident-owned provider/settings lifecycle. M7 artifact/package shape is verified on Linux x86_64, Windows x64 and macOS arm64. M8 has installed-Linux proofs plus source-level busy/idle N → N+1 continuity regressions.

The active development mainline is no longer release breadth. It is the resident execution spine described in `ZN-NEXT-PHASE.md`. M8 remains explicit bounded release debt.

## M5/M6 product loop

`ResidentWorkLedger` owns durable threads/messages, workspace association, active work linkage/progress and bounded contextual file/diff/terminal artifacts beside kernel state. Provider settings/credential references remain resident-owned. Renderer progress/localStorage do not become resident authority.

## Browser and outbound-media investigation result

A browser contextual surface is **not** claimed yet. The mature inherited browser implementation remains coupled to inherited configuration/plugin/session/provider ownership plus Node/Chromium/`agent-browser`. The independent resident runtime has no clean ZN-owned browser action seam yet.

Telegram outbound media remains intentionally pending. `OutboundMediaPathPolicy` provides ZN local-file authorization, but resident delivery still lacks explicit structured resident-owned artifact/path nomination for egress.

## Current subsystem ledger

### Resident organism / kernel

Status: **ZN-native resident organism active; execution verification spine materially strengthened but long-horizon task completion remains partial**.

Persistent life, Situation/Thought/Will, nervous memory, native investigation/action/learning, sensing and bounded external cognition remain resident-owned. Zero-model operation is a hard contract. Current verified execution semantics now include durable post-action verification for exact text state and explicit command postconditions, with contradiction returned immediately into Situation/Thought.

### Work/thread/workspace/artifacts

Status: **resident-backed durable work + active progress + workspace + contextual file/diff/terminal artifacts active; M6 still partial**.

### External cognition/settings

Status: **ZN-native resource layer plus resident-owned provider/credential editor active**.

### Local terminal/body

Status: **ZN local terminal/PTTY active; explicit command postcondition verification is now CI-verified**.

### Git repository sense

Status: **structured read-only ZN Body sense CI-verified; general mutation/verification loop still pending**.

### Web/world sense

Status: **ZN-owned search/extract providers and network safety active; browser automation not yet owned**.

### Communication channels

Status: **resident-owned channel framework and Telegram text/inbound media active; outbound attachment transport pending explicit resident egress nomination**.

### Python/runtime package ownership

Status: **M1 complete for the active packaged resident path**.

The independent `runtime/python` `znagent` distribution boots through `zn_agent.resident` / `zn-resident`, rejects inherited `hermes_cli`, and has real extraction/boot evidence inside Linux/Windows/macOS artifacts plus installed Linux proofs.

### Desktop/UI ownership

Status: **M4 complete; M5/M6 materially advanced; pure UI polish paused for the core-first phase**.

### Packaging/release ownership

Status: **M7 artifact ownership verified for current Linux x86_64, Windows x64 and macOS arm64 targets; M8 has installed-Linux proofs plus source-level N → N+1 continuity regressions**.

Still pending:

- full installed Electron updater/application N → N+1 handoff evidence;
- Windows/macOS clean-install and login-autostart coverage for intended release matrix;
- signing/notarization when operationally configured;
- any additional release architectures;
- eventual inactive inherited-source cleanup without regressing active ownership.

## Ownership/behavior tests protecting the active path

The suite and scoped artifact/install runs protect, among other behavior:

```text
agent/kernel must not import hermes_cli or run_agent
runtime distribution must identify as znagent
packaged runtime must reject hermes_cli
zero-model resident boot must succeed
provider secrets/settings remain resident-owned and sanitized
resident accepted work persists before completion
completed detached work finalizes after reconstruction
one thread rejects parallel active resident work
progress comes from resident state, not renderer/localStorage
workspace/artifacts remain resident-backed and bounded
NativeBody Git sense returns structured repository state
changed-path answers come from active embodied Git Body evidence
successful write movement does not imply task completion
write postconditions survive restart and are independently re-observed
contradicted write postconditions return to investigation without blind replay
explicit command expected_outcome is independently verified
command verification survives restart without replaying the primary command
failed command verification becomes immediate Situation/Thought evidence
ZN desktop main/preload/renderer do not delegate to inherited control planes
ZN deep links reject hermes://
formal package metadata identifies ZN
formal builder registers only zn://
real packaged zn-runtime boots zero-model after Linux/Windows/macOS packaging
fresh-runner Linux deb installation preserves ZN identity and boots embedded resident
SIGTERM retires endpoint and durable lease before resident exit
fresh-installed Linux systemd user autostart starts/stops/returns packaged resident
queued resident work prevents false-idle runtime handoff
N and N+1 packaged runtimes coexist under one ZN home
idle N → N+1 restart preserves living-self identity and durable work history
```

## Milestone status snapshot

```text
M0  blueprint/reset ownership contract                     COMPLETE
M1  independently packageable ZN Python resident runtime   COMPLETE for active packaged path
M2  ZN-native bounded provider cognition                   COMPLETE for active main provider families
M3  ZN-owned terminal + web body/sense paths               COMPLETE for active local/web paths
M4  independent Electron main + preload + zn://            COMPLETE
M5  independent content-first ZN workbench                 IN PROGRESS; pure polish paused
M6  resident work/artifact/workspace end-to-end loop       PARTIAL; core execution mainline active
M7  formal packaging around owned product                  ARTIFACT SHAPE VERIFIED on Linux x86_64 / Windows x64 / macOS arm64
M8  clean-machine/continuity multi-OS validation           IN PROGRESS; bounded release lane
M9  product completeness/hardening                         LATER
M10 repository migration / formal main promotion           LATER; main untouched
```

## Immediate next development sequence

1. keep the core mainline on durable complex-task execution; do not return to cosmetic UI or broad release work;
2. strengthen task-level state so the same event retains an explicit current goal, current gap, expected outcome and verification result without becoming an ever-growing planner database;
3. make verification evidence and failed attempts increasingly first-class durable evidence that can guide later actions and survive completion/restart where useful;
4. extend failure recovery so a contradicted postcondition can lead to a genuinely different investigation/action rather than only truthful failure;
5. then build practical Git repository action + diff/test/reality verification with conservative mutation boundaries;
6. add GitHub repository/PR/CI read-only resident sense before any remote write capability;
7. establish browser interaction only through a clean resident-owned Body/Senses seam;
8. drive breadth using real benchmark tasks such as unfamiliar repo + failing CI → diagnosis → repair → tests → diff/state verification → evidence;
9. keep remaining M8 updater/multi-OS/signing work explicit as bounded release debt and fix it only when it exposes a real continuity/security/data-integrity problem.

The architecture driver is now: **the same persistent ZN Self must be able to finish hard work and prove from current reality that it is finished.**
