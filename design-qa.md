# Design QA — ZN Resident Shell v2

## Result

**passed**

> This earlier result documents the R4 resident-shell validation below. It does not certify the newer three-column workbench changes.

The resident shell now matches the intended product pattern from the YOYO black-box reference: compact-first invocation, a calm assistant surface, and progressive expansion into work/history/details instead of a permanent three-column admin console.

## Source of visual truth

- Source: `C:\Users\Public\yoyo-static-evidence\small-large.png`
- Source pixels: **2240 × 1172**
- Source state: YOYO small/large resident assistant shell comparison.
- Additional black-box references reviewed: `work-progress.png`, `workstation.png`, `cross-search.png`, and `fast-read.png`.
- Comparison board: `C:\Users\Public\zn-design-qa\resident-shell-v2\yoyo-vs-zn-r4.png`

## Implementation captures

- Compact: `C:\Users\Public\zn-design-qa\resident-shell-v2\zn-compact-r4.png`
- Captured pixels: **494 × 629**
- Intended Electron content size: **480 × 620**
- Windows DPI: **144 (150%)**
- State: clean first-run profile, Resident ready, no workspace attached, cognition not configured.

- Expanded: `C:\Users\Public\zn-design-qa\resident-shell-v2\zn-expanded-r4.png`
- Captured pixels: **1134 × 767**
- Intended Electron content size: **1120 × 760**
- Windows DPI: **144 (150%)**
- State: same clean first-run work, expanded history/workspace shell.
## Full-view comparison

The R4 comparison board was reviewed with the YOYO source and both real Electron states in the same image. The important structural match is present:

- compact invocation is one assistant surface, not a shrunk three-column desktop app;
- expanded mode reveals history/workspace/navigation only when requested;
- the message composer remains the primary action in both modes;
- assistant identity/readiness is visible without exposing model/runtime internals as the main hierarchy;
- technical work evidence, restore points, and artifacts are available through progressive disclosure rather than permanent panels;
- native Windows controls and ZN controls have separate safe areas.

## Three-column workbench follow-up

### Result

**final result: blocked**

The selected light three-column concept was assembled and visually inspected in [Figma](https://www.figma.com/design/3EYdorATddYYe21JiCDuF6?node-id=1-2). It shows the conversation remaining visible while the artifact preview opens to the right. The source changes also pass the desktop TypeScript check.

The running Electron implementation could not be captured for visual comparison. The repository's `npm run dev` setup reinstalled the locked workspace dependencies, then failed its Electron/esbuild readiness check after npm blocked their lifecycle scripts. No Electron screenshot was produced, so the live desktop layout, small-window drawer, and visual fit remain unverified.

The source uses a light/pale system palette while ZN intentionally keeps its dark navy/Mica visual language. This is a brand/token deviation, not a structural mismatch. Copy and icons are also ZN-native rather than cloned from YOYO.

## Iteration history

### R1 — P1: desktop/developer chrome

The first real Electron pass still exposed the native `File / Edit / View / Window` menu and conventional title chrome. It made the shell read like a development desktop application rather than a resident assistant.

Fix: switched to Electron hidden title bar + Windows title-bar overlay, removed the application menu with `window.setMenu(null)`, enabled Mica, and kept rounded Windows corners.

Verification: UI Automation reports `File`, `Edit`, `View`, and `Window` as absent while Windows minimize/maximize/close controls remain available.

### R2 — P1: global invocation did not always return to compact

When the expanded window was minimized, Windows could ignore the resize request because resize happened before the native window was restored.

Fix: `showPrimaryWindow()` now restores/shows the resident surface before applying compact/expanded bounds.

Verification: from expanded + minimized, `Ctrl+Alt+Space` restores foreground ZN, hides expanded sidebar content, exposes `Expand ZN`, and focuses `Message ZN`.
### R3 — P2: provider warning dominated the assistant home

The expanded empty state initially opened with a large “No model configured” notice. That recreated an admin/settings-first hierarchy and competed with “What do you want to do?”.

Fix: removed the large home notice. Provider readiness is now a quiet readiness item (`Cognition setup needed`) and provider explanation remains in Settings. Local deterministic paths stay available.

### R3 — P2: custom controls competed with Windows controls

The custom top-bar buttons did not reserve a Windows Window Controls Overlay safe area.

Fix: the v2 top bar reserves 152 px on the right, is a draggable app region, and marks custom action buttons as no-drag.

### R4 — final clean-state pass

The app was relaunched with a clean Electron user-data directory so cached work did not contaminate the comparison. Compact and expanded screenshots were recaptured from the same first-run state and compared against the YOYO source.

No unresolved P0, P1, or P2 visual mismatch remains in the resident-shell scope.

## Functional/visual checks

- Root desktop TypeScript typecheck: pass.
- Desktop ownership contract tests: 17/17 pass after the final shell changes.
- Real Electron Resident connection: pass.
- Compact/expanded transition: pass.
- Global invocation from minimized expanded state: pass.
- Foreground restoration: pass.
- Composer keyboard focus after invocation: pass.
- Native menu removal: pass.
- Windows system controls retained: pass.
- Custom/system title-bar control overlap: not observed.
- Reduced-motion rule remains present.
- Existing delegated progress, execution evidence, artifact, and restore-point UI contracts remain represented.

## Final severity status

- P0: 0
- P1: 0
- P2: 0
- P3: intentional palette/content differences only.

result: passed


## Codex-inspired workbench follow-up — 2026-09-23

The prior R4 pass above covers the resident shell and is historical; it does not establish fidelity to the selected Codex-style conversation/workbench reference.

### Corrected Leopard capture

- Captured the actual ZN Electron window on Leopard from the isolated `ZNagent-workbench-preview` checkout, at 2560×1600 with the window maximized.
- The isolated profile is a clean first-run state: it contains no conversation messages and no document/presentation artifact. Therefore this capture does not exercise or prove the side-by-side artifact workbench.
- The first screenshot was not a valid reference comparison. It included the non-maximized ZN window and unrelated Windows notification cards; the earlier mistaken Chrome/Hermes identification is withdrawn.

### Confirmed implementation mismatches and fixes

- The light ZN surface still used dark native window controls. `zn-main.ts` now aligns the native title-bar overlay and initial window background with the light UI.
- The composer wrapper still painted a dark full-width strip. `styles.css` now uses a light fade under the floating composer and readable caption text.
- After a clean source-app restart, the title bar and composer region render light. The isolated first-run home still differs substantially from the selected active-conversation reference, and no artifact side-by-side screenshot has been captured.

### Remaining review boundary

A real conversation with a document or slide artifact is required to compare the selected behavior: persistent chat at left and a usable workbench preview at right. Do not report the Codex-inspired design as visually passed until that state is captured and reviewed.

result: blocked (artifact-bearing conversation unavailable in the isolated profile)
