# In Progress

## 2026-09-16 — Managed Browser Enter-submit form path

- Owner: ChatGPT / ZNagent development session
- Status: in progress
- Started: 2026-09-16
- Base: `main@dae21f547005a48034305247f9f8627c7eaed87e`
- Branch: `work/managed-browser-enter-submit`
- Goal: close one bounded ordinary MANAGED Browser form path where a freshly bound exact semantic textbox is filled and the form is submitted by a single `Enter` keypress, with an explicit same-origin expected URL and fresh verification.
- Expected write set:
  - `runtime/python/zn_agent/core/managed_browser.py` (minimal dispatch seam only)
  - `runtime/python/zn_agent/core/managed_browser_press.py` (new)
  - `runtime/python/zn_agent/core/browser_form_submit_body.py`
  - `runtime/python/zn_agent/core/browser_form_submit_resident.py`
  - focused managed-browser/body/resident tests
  - one real managed-browser E2E/workflow only if needed to prove the product route
- Explicitly excluded: USER Browser extension/privacy, E2E-25 routing, Windows Explorer selection PR #333, workspace exact-file Body PR #334, desktop renderer/tray/install/signing/updater/release work, recurring Will, provider health, partial-completion projection.
- Safety boundary: MANAGED Browser only; exact semantic textbox; exact single key `Enter` only; no arbitrary key combinations/shortcuts; no password/sensitive fields; same-origin explicit expected destination; fresh target revalidation immediately before press and fresh observed URL after dispatch; no blind replay after uncertain external mutation.

This claim is temporary coordination evidence and should be removed before the PR is merge-ready.
