# ZN Product Capability Map

This map is capability-owned. Representative task stories are evidence, not architecture owners.

## Control plane

| Area | State | Contract |
| --- | --- | --- |
| Resident lifecycle | CONNECTED | one product Resident lineage owns execution |
| Work / Root completion | CONNECTED | durable Root Work is the only product completion truth |
| Action authority | CONNECTED | effects require current ZN-owned authority |
| Side-effect attempts | CONNECTED | replay-sensitive effects use durable dispatch identity and no-blind-replay |
| Fresh verification | CONNECTED | outside-world completion requires fresh postcondition evidence |

## Browser

| Area | State | Boundary |
| --- | --- | --- |
| Managed Browser adapter | CONNECTED | generic adapter contract exists; current implementation is Playwright-based |
| Managed Browser semantic target actions | VERIFIED NARROW | current observation and target identity must remain fresh |
| Browser pages/tabs/history | PARTIAL | reusable primitives exist; arbitrary browser complexity is not claimed |
| Browser file transfer | PARTIAL | strict causal transfer contracts remain provider-specific |
| USER Browser bridge | VERIFIED NARROW | explicit current-tab authorization and generation ownership |
| USER Browser semantic grounding | VERIFIED NARROW | fresh same-authorization observations; no silent authority transfer |
| User-presence boundaries | PARTIAL | security/credential interactions stay user-owned unless explicitly supported |

## Windows / desktop

| Area | State | Boundary |
| --- | --- | --- |
| Machine/application inventory | CONNECTED | fresh machine evidence owns application identity |
| Existing-window activation | VERIFIED NARROW | exact window/process binding; no arbitrary retarget |
| Pointer/keyboard/UIA | CONNECTED + VERIFIED NARROW | one Body and authority path |
| Safe modal recovery | VERIFIED NARROW | exact same-process bounded safe action only |
| Action Fabric / app competence | CONNECTED + PARTIAL | reusable action descriptions/recipes; no second execution authority |
| Audio / brightness / Wi-Fi sensing | PARTIAL | bounded native capabilities only |

## Files / Office

| Area | State | Boundary |
| --- | --- | --- |
| File identity / bounded discovery | CONNECTED | fresh path/identity evidence |
| Atomic overwrite | VERIFIED | staged commit + recovery + postcondition |
| DOCX primitives | PARTIAL | bounded document operations; not complete Word automation |
| XLSX primitives | PARTIAL | bounded workbook operations; not complete Excel automation |
| Presentation primitives | PARTIAL | bounded presentation operations |
| Office COM | PARTIAL | exact foreground/native object operations where supported |

## Research / cognition

| Area | State | Boundary |
| --- | --- | --- |
| Public Web resource | CONNECTED + PARTIAL | search/extract/evidence primitives |
| Cognitive routes | CONNECTED | ZN owns route policy and admission |
| Evidence grounding | PARTIAL | evidence must be explicit and fresh enough for the claimed result |
| External provider health | PARTIAL | health may affect routing but never transfers completion truth |

## Delegation / recovery

| Area | State | Boundary |
| --- | --- | --- |
| Worker isolation | CONNECTED | WorkerRun results are subordinate to Root Work |
| Progress projection | CONNECTED | durable progress is ZN-owned |
| Health-aware routing | PARTIAL | generic mechanism remains; fixed task phase orchestration is retired |
| Steering / stale-plan gating | PARTIAL | old-plan effects cannot silently become current truth |
| Restart recovery | CONNECTED + PARTIAL | recovery preserves durable effect identity and re-observes reality |

## Memory / learning

| Area | State | Boundary |
| --- | --- | --- |
| Verified experience | CONNECTED | learning requires verified evidence |
| Preferred working style | PARTIAL | preferences do not override authority/safety |
| Learned workflow reuse | PARTIAL | bounded reuse only; arbitrary procedure learning is not claimed |

## CI / release

Automatic gates are capability contracts, not task-story gates:

- Managed Browser Contract;
- Windows Interactive Desktop Contract;
- Work Recovery Contract;
- Atomic Overwrite Contract;
- ZN CI;
- Windows Clean Install.

Real-system capability tests live under `tests/zn_agent/integration`. Scenario-specific product routes and numbered acceptance catalogs are retired from the active architecture.
