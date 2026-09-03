# ZN Desktop Action Reference

This is a design reference for ZN-owned desktop computer use. It records
mechanisms learned from public implementations; it does not make any external
project a ZN runtime dependency.

## Reference projects inspected

- Hermes Windows `computer_use` backend / Cua Driver integration
- `trycua/cua` Windows driver
- `yassiEmp/agent-win`
- `licat2023/desktop-touch-mcp`
- `Git-Uzair/CU_MCP`
- `amitse/uiacli`
- `pywinauto/pywinauto`
- `microsoft/UFO`
- `shanselman/FlaUI-MCP`
- `ikoskela/precision-desktop`

## ZN decision

ZN remains the product subject and owns its Body, Senses, Action, authority,
verification and recovery. External projects are mechanism references only.

The desktop action ladder should be:

```text
fresh desktop observation
-> semantic target identity / short-lived binding
-> re-resolve the live target immediately before action
-> UIA pattern action when supported
   - InvokePattern / LegacyIAccessible default action for buttons
   - ValuePattern / SelectionItem / RangeValue for values
-> UIA bounds + SendInput fallback for controls without usable patterns
-> independent post-action observation / semantic diff
-> Investigation or recovery when the expected effect is not proven
```

## Non-negotiable invariants

- Never treat a cached UIA COM pointer as durable truth.
- RuntimeId, AutomationId, structural path, name and bounds are scoped
  evidence; re-sense before mutation.
- Window identity must include process/window evidence and detect replacement.
- UIA and screenshot/mouse coordinates must declare their coordinate space.
- A successful dispatch is not completion; return observed effect evidence.
- A stale target must cause re-discovery, not blind retry.
- Password, credential and unsafe fields remain blocked.
- A started non-replayable mutation remains uncertain until independently
  reconciled; do not replay it from a model suggestion.
- UIA worker COM initialization and timeout isolation are required on Windows.

## Current ZN gap

`automation_named_control_sense.py` currently returns a read-only cached
observation. `goal_resident.py` then converts the observation into normalized
screen coordinates and the Body uses pointer movement/click. This is valid as a
fallback but is not yet the preferred semantic action path.

The next implementation slice is a ZN-owned semantic action adapter that
re-finds the exact named control on the UIA worker and attempts the applicable
pattern in the same bounded call. It must return an action result containing
method (`invoke`, `value`, or `synthetic_input`), target identity, and an
independent postcondition observation. The existing pointer lifecycle remains
as the guarded fallback until the semantic path is proven.

## Coordinate/DPI reference

Windows implementations disagree when they mix logical screenshot coordinates,
physical `SetCursorPos` coordinates, UIA rectangles and multi-monitor origins.
ZN must latch/query a declared coordinate space and reject or convert mismatched
spaces. A short wait after ZN's own `SetCursorPos` may handle publication delay,
but it is not a substitute for DPI/monitor calibration.

## Token/cost rule

The model may select or describe a semantic goal. ZN should return compact
structured observations and semantic diffs rather than sending a screenshot or
full UI tree after every ordinary local action. Models remain available for
novel interpretation, ambiguity and recovery reasoning.
