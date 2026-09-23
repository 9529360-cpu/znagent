# ZN Implementation Status

This is a current architecture/status snapshot. Real code, Git state and contract/integration evidence are authoritative.

## Product control plane

ZN has one product control plane:

- one Resident lineage;
- one durable Work/Root completion truth;
- one action-authority system;
- one Body/effect boundary;
- one replay/recovery discipline;
- one completion decision owned by ZN.

External model or tool success is evidence only.

## Capability status

| Capability | Current state | Boundary |
| --- | --- | --- |
| Durable Work / Root completion | CONNECTED | Root status is ZN-owned; child/tool success cannot independently complete the Root |
| Side-effect journaling / no-blind-replay | CONNECTED | replay-sensitive effects preserve durable dispatch identity and fail closed when outcome is uncertain |
| Work recovery / continuation | CONNECTED + VERIFIED NARROW | durable plan/progress/recovery are reusable; broader long-horizon UX remains open |
| Managed Browser | CONNECTED + VERIFIED NARROW | pinned Chrome DevTools MCP is the mature default where its declared capability fits; Playwright remains a fallback for contracts such as stricter file transfer |
| USER Browser bridge | CONNECTED + VERIFIED NARROW | explicit current-tab authorization/generation ownership; no silent attachment to arbitrary user tabs |
| Browser semantic grounding | CONNECTED + VERIFIED NARROW | provider-neutral fresh semantic actions pin page URL, re-resolve stale targets only after explicit pre-dispatch proof, and never replay dispatched/uncertain effects |
| Windows application awareness | CONNECTED | installed-app/process/window identity and bounded activation use fresh machine evidence |
| Windows interactive actions | CONNECTED + VERIFIED NARROW | pointer/keyboard/UIA movements remain Body-owned and authority-gated |
| Atomic file overwrite | CONNECTED + VERIFIED | staged write, identity checks, durable attempt tracking and recovery contracts |
| Document/presentation primitives | CONNECTED + PARTIAL | generic document/presentation behaviors remain; scenario-owned document completion paths were retired |
| Spreadsheet primitives | CONNECTED + PARTIAL | generic workbook operations remain; no task-specific browser-to-sheet product route owns the architecture |
| Public research primitives | CONNECTED + PARTIAL | search/extract/evidence mechanisms remain; no dedicated representative-task completion path owns the product |
| Delegated Work / routing | CONNECTED + PARTIAL | generic routing, progress, health and authority remain; fixed story phase orchestration was retired |
| Memory / learned behavior | PARTIAL | explicitly saved structured facts can enter bounded cognition context through exact saved-key/alias cues when `allow_memory` is enabled; automatic memory writing, semantic retrieval, and arbitrary workflow learning remain open |
| Packaging / clean install | CONNECTED | packaged runtime and clean-install verification remain release boundaries |

## Recently retired scenario-owned surfaces

The cleanup removes product code whose primary owner was a narrow representative task rather than a reusable capability contract, including:

- current-app cleanup story modules;
- local-service repair story modules;
- long-running terminal story behavior;
- local Office representative behavior;
- document-research-completion story behavior;
- managed-reference browser research story runtime;
- browser-result-to-file story route;
- fixed delegated-worker story orchestration;
- File-to-Desktop composite goal / semantic grounding route;
- task-specific desktop modal sensing/recovery stack;
- payment-date-specific DOCX inspection and mutation path.

Their removal does not revoke the generic Work, Body, authority, browser, file, research, Office, delegation or recovery mechanisms they previously composed.

## CI shape

Automatic gates are contract-first and use contract-named workflows. Real-system capability checks live under `tests/zn_agent/integration`; ordinary deterministic/unit contracts remain under `tests/zn_agent/core`.

The repository policy test prevents retired scenario namespaces and numbered story identifiers from becoming active architecture again.

## Current major gaps

1. Managed Browser breadth is still split by provider capability; Chrome DevTools MCP does not yet replace every stricter Playwright contract.
2. Generic semantic fresh-re-ground currently covers exact named text/button action paths; arbitrary web interaction remains open.
3. USER Browser support remains intentionally explicit and bounded.
4. Windows/application automation is not general RPA.
5. Document/spreadsheet capabilities are not complete Office automation.
6. Long-horizon autonomous Work, broader delegation and learning remain partial.

Browser expansion now proceeds from the cleaned capability-owned substrate rather than from retired representative-task stories.

