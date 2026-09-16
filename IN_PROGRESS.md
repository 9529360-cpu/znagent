# In Progress

## 2026-09-16 — Windows Explorer selected-file context

- Owner: ChatGPT / ZNagent development session
- Status: in progress
- Started: 2026-09-16T21:56+02:00
- Base: `main@9d4facbbc30784f437e0e8ccc1362f839020e053`
- Branch: `work/windows-explorer-selected-file-context`
- Goal: let the existing Product Resident answer a bounded natural-language request about the single local file currently selected in the exact foreground Windows File Explorer window, using Shell COM selection truth and existing Body path inspection with fresh revalidation.
- Expected write set:
  - `runtime/python/zn_agent/core/windows_explorer_selection.py` (new)
  - `runtime/python/zn_agent/core/explorer_selected_file_behavior.py` (new)
  - `runtime/python/zn_agent/core/device_capability_graph.py`
  - `runtime/python/zn_agent/core/research_information_product_resident.py`
  - focused core/E2E tests for the new slice
  - `.github/workflows/zn-windows-interactive-e2e.yml` only if needed to execute the real Windows acceptance
- Explicitly excluded: desktop renderer/copy/visuals, tray/resident-surface work, installer/signing/updater/release trust, provider health/readiness, recurring Will, E2E-25, sensitive-field work, partial-completion projection.
- Safety boundary: read-only; exact foreground `explorer.exe`; exactly one local regular file; no UNC/network path, directory, multi-selection, clipboard, OCR, shell mutation, or broad filesystem authority. Selection must be freshly revalidated before completion.

This claim file is temporary coordination evidence and should be removed before the PR is merged; the open PR/branch then remains the durable work record.
