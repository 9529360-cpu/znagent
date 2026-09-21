# ZN Transfer Map from HONOR YOYO PC Static Analysis

Updated: 2026-09-21

This note records product mechanisms observed through quarantined **static analysis** of the official HONOR YOYO PC package. It is a transfer map for ZN, not a source-code port.

No HONOR executable, DLL, installer, extracted Python module, or service was executed to produce the evidence summarized here. Proprietary implementation, branding, icons, models, binaries, action traces, and source code are not copied into ZN.

## 1. Evidence boundary

Observed package:

- HONOR HNMagicAI / YOYO PC 9.0.2.52 SP2
- official package provenance recorded in the quarantine research workspace
- outer package SHA-256: `c52e6fc3ae4f429d001667b16079d06251f0182c22e1272f66092e4ce22aa036`
- installer Authenticode observed as valid for Honor Device Co., Ltd.
- analysis mode: archive/config/resource/static-string inspection only

The value of this evidence is architectural. It shows which mature product mechanisms exist in a shipping Windows assistant and helps ZN decide what to build with its own implementation.

## 2. Resident shell is a state machine, not one chat window

Static product names and resources expose several presentation states and transitions:

- resident tray/taskbar integration
- floating-ball style entry
- small assistant window
- full assistant window
- small/full window transitions
- docking / auto-pin-to-side behavior
- global hotkey entry
- voice entry
- unread/task-progress presentation
- agent execution view and vertical-page switching

This is materially different from treating the desktop product as a permanent chat page.

### ZN transfer

ZN should keep **one Resident and one Electron application**, but allow several presentation states over that same subject:

```text
hidden / tray resident
        ↓
compact invocation surface
        ↓
full Work surface
        ↓
background Work continues
        ↓
progress / unread notification
```

Optional edge docking is a presentation policy only. It must not create a second Resident, second Work owner, second task queue, or second execution plane.

### Current ZN status

Already connected narrowly:

- Windows notification-area lifetime
- hide-on-close / restore / focus behavior
- compact renderer breakpoint
- first resident home/quick-start surface
- a best-effort global invocation change is in flight
- Work itself is durable outside the window lifetime

Still open:

- explicit compact/full presentation state owned by the resident shell
- edge docking / auto-hide policy
- task-progress and unread state visible outside the full Work surface
- small resident status surface that does not become a second chat/runtime
- voice surface

## 3. Intent and slots precede general cognition

The package exposes a broad typed intent catalog. Static configuration contains 158 planned intents across system and domain functions.

For routine system controls, the dispatch configuration frequently does **not** require the original free text once the intent is known. Representative toggle targets for WLAN, Bluetooth, airplane mode and related system settings declare no text payload requirement.

Value-bearing controls use semantic slots instead of raw prompt execution.

Examples observed in the brightness family:

- `SET_LUMINANCE`
- `CHECK_LUMINANCE`
- `TURN_UP_LUMINANCE`
- `TURN_DOWN_LUMINANCE`
- `SET_AUTO_LUMINANCE`
- `TURN_ON_AUTO_LUMINANCE`
- `TURN_OFF_AUTO_LUMINANCE`

The absolute luminance intent includes value concepts such as number, percent, fraction and level. Auto-brightness is represented separately rather than being guessed from an ordinary absolute-brightness command.

Volume shows the same family pattern: absolute value, relative up/down and current-state query are distinct semantic intents.

### ZN transfer

The transferable mechanism is:

```text
user language
→ deterministic intent
→ semantic slots
→ typed ActionDescriptor
→ current authority / availability check
→ existing Action Executor
→ existing Body
→ fresh independent verification
```

Raw natural language is not execution authority.

### Current ZN status

Connected and verified narrowly:

- Deterministic Reflex / Intent Registry
- explicit semantic slots
- Action Fabric descriptors
- existing Action Executor / Body / side-effect journal
- application-open grounding before stable `application_id` authority
- Windows audio intent recognition
- Windows audio zero-model execution is in flight
- Windows brightness Action Fabric substrate is in flight
- Windows brightness intent recognition is in flight

Important boundary:

- relative brightness and auto-brightness remain separate future intents
- ambiguous requests must continue through normal Situation / Thought / Work paths
- no model receives direct execution authority

## 4. Capability runtime is explicit and queryable

YOYO's capability runtime statically exposes service registration, health/queryability and service lifecycle concepts. Several microservices are resident while others are disabled until needed.

The transferable mechanism is not YOYO's service layout. It is the separation of:

- capability identity
- health
- current queryability
- lifecycle mode
- lazy activation
- execution authority

### Current ZN status

This mechanism is already substantially present in ZN Provider Runtime:

- provider registration
- `resident / lazy / external` lifecycle modes
- health probes
- queryability
- optional activation hooks
- Windows provider health
- local-inference provider health

Do **not** introduce a second capability scheduler or service registry to imitate YOYO. Extend the existing Provider Runtime when a real ZN provider needs lifecycle ownership.

## 5. Native execution remains separate from cognition

Static architecture separates deterministic Windows execution from the Python cognition/agent layer.

The native executor owns concrete OS effects such as system controls, window/process operations and UI Automation. The agent layer can plan or reason, but it does not become the primitive Windows actuator.

### ZN transfer

This directly supports the existing ZN rule:

- GPT / Gemini / Claude / local models are cognition resources
- ZN Resident owns Work
- Action Fabric owns typed semantic actions
- Body owns concrete machine movement
- current-world evidence is reacquired before authority-sensitive effects
- completion requires fresh verification

### Current ZN status

This boundary is already the main architecture and must not be weakened while adding more convenience fast paths.

## 6. Local inference is a resource broker problem

YOYO's local inference stack statically contains several specialized model families and hardware backends rather than one giant on-device model.

Observed classes/plugins cover LLM, NLU, OCR, CV, CLIP and ASR, with OpenVINO / ONNX Runtime / DirectML and Intel CPU/GPU/NPU support.

Resource-balancing evidence includes power state and machine load/thermal style signals.

### ZN transfer

Local inference should remain a **replaceable cognition resource tier**, selected from fresh runtime and hardware evidence.

### Current ZN status

Connected narrowly:

- discovery for loopback Ollama / LM Studio / vLLM
- exact configured model presence
- RAM / GPU / AC power / battery-saver evidence
- hard eligibility filtering when runtime/model evidence is absent

Still open:

- product-verified local model execution on a real endpoint
- specialized OCR/vision/ASR local resource classes where justified by real Work
- bounded resource-pressure admission beyond the current discovery facts

Do not download multi-GB models merely to claim closure.

## 7. Vertical surfaces share one substrate

Static web/resource names show multiple product surfaces, including search, reading, workstation, mind-map and small/large assistant views.

The lesson is not to clone those pages. It is that mature assistants present task-specific surfaces over common identity, capability and Work infrastructure.

### ZN transfer

Future ZN surfaces may include:

- search/research result surface
- document/read surface
- coding/engineering surface
- local file/workspace surface
- compact system-command surface
- evidence/progress surface

All must remain views of the same ZN Resident and Durable Work.

## 8. App competence is versioned data, not a second Agent

Static UI-agent resources include per-application competence/configuration for many desktop apps and staged action knowledge.

ZN should borrow the data-oriented idea, not copy proprietary traces.

### ZN transfer

A future app-competence pack should describe, for a specific application/version where appropriate:

- stable application identity
- known semantic surfaces
- reliable UIA roles/names
- safe read-only probes
- known modal states
- candidate recovery observations
- verification hints

It must not become:

- a second planner
- a second desktop dispatcher
- a replay script with stale coordinates
- persistent current-world authority

Current UI Automation evidence must still be freshly reacquired before use.

## 9. What ZN should transfer next

The static evidence strengthens the following already-planned ZN work. The sequence should be driven by safe, verifiable closures rather than feature count.

### Resident shell

Build on the existing Electron resident surface:

- compact/full presentation state
- background Work progress outside the full window
- unread/completion indication
- optional edge-dock / auto-hide behavior
- invocation always returns to the same Resident

### Deterministic system controls

Continue extending the existing Action Fabric only where Windows offers a stable semantic API and ZN can verify the result:

- brightness absolute read/set
- read-only power state views over existing context
- Wi-Fi/Bluetooth state before mutation authority
- media control only after a stable Windows media-session authority path is proven

Avoid using keyboard simulation or generic RPA as the substrate for ordinary system settings.

### Direct read-only Reflex views

High-confidence queries such as battery/power state should select and format current evidence from existing ZN context rather than call a model or duplicate the underlying Windows probe.

### App competence

Add versioned competence data only after real tasks reveal repeated app-specific structure worth compiling.

## 10. Non-transfer list

The following are explicitly **not** transfer targets:

- HONOR source code
- proprietary binaries or DLL logic
- HONOR branding, icons or visual assets
- proprietary model weights
- copied action traces / coordinate scripts
- YOYO's Agent loop, planner, router, memory system or scheduler
- stale device facts persisted as future execution authority

ZN remains the only subject.

## 11. Product test for every transferred mechanism

A YOYO-inspired mechanism is not complete because ZN has a similar class name or UI.

For each transferred mechanism, require:

1. one owner in ZN architecture;
2. fresh current-machine evidence where relevant;
3. explicit authority boundary;
4. fail-closed behavior when evidence is missing/ambiguous;
5. side-effect replay protection where relevant;
6. independent result verification;
7. real-machine acceptance when safe;
8. no hidden model call for a deterministic fast path;
9. no duplicate Router/Body/Work/Store/Agent loop.

This is the standard for turning black-box product evidence into ZN product capability.
