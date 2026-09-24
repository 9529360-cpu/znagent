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
| Memory / learned behavior | CONNECTED + VERIFIED NARROW | saved facts, explicit response preferences and same-Work conversation compose in bounded product cognition; automatic personal-memory writing, semantic search and arbitrary workflow learning remain open |
| Packaging / clean install | CONNECTED | packaged runtime and clean-install verification remain release boundaries |

## Saved memory in ordinary conversation

The active product path is Work route-policy binding -> anchored same-Work conversation -> `StructuredMemory.bind_cognition_context` -> existing CognitionRequest / Kernel / cognitive adapter. The existing `facts` table and `remember` / `forget` RPC remain the owners; no second memory database, identity migration or external agent runtime is introduced.

Saved keys and explicit aliases are matched conservatively, with Unicode normalization, most-specific-cue ranking and stable tie-breaking. Values are never searched for cues. A directly named topic takes precedence; otherwise the last two user messages from the existing bounded Work transcript may supply reference cues. Assistant claims, tools and other threads do not supply these cues. Records carry their saved key, update timestamp and match provenance; they are data, not execution authority or completion evidence.

Explicitly saved response language, style and verbosity are bounded default preferences. Examples of existing fact keys are `response language`, `response style`, `response verbosity`, and their supported Chinese reply-language/style equivalents. Values must be nonempty strings no longer than 200 characters. Other preferences require relevant cues; permission, credential and route-policy fields are not ambient preferences. Current user instructions take precedence over defaults. Saving/inference of preferences from arbitrary chat is not implemented by this projection.

The projection selects at most five facts, preserves whole values rather than generating lossy summaries, and caps the actual nested UTF-8 context at 8 KiB. Opt-out (`allow_memory` not exactly true when explicitly supplied) and explicit isolated cognition questions exclude both saved memory and conversation. New requests read current SQLite values without a projection cache; updates and deletions survive reconstruction. An already prepared durable cognition request remains its original snapshot across restart. Forgetting a fact does not erase earlier transcript disclosures or already prepared request snapshots.

Narrow executed evidence in `test_memory_conversation_product.py` exercises the real Product Resident, Work/RPC, Kernel, SQLite and cognitive adapter, including authenticated TCP disconnect/reconnect, two resident lifetimes, follow-up reference retrieval, update/forget, policy/isolation and pre-dispatch continuation without duplicated messages/calls. Provider responses are controlled test boundaries, not live-model quality evidence. Full installed daily-use acceptance and unified knowledge-graph/semantic retrieval remain open.

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
