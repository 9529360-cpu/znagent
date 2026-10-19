# Vendored open-claude-ui

This directory is a pinned snapshot of
[`Caho1/open-claude-ui`](https://github.com/Caho1/open-claude-ui.git)
(`VENDOR.json` records the exact upstream commit: `4045ce7`,
`package.json` version `1.0.0`). It is the UI kit the ZN desktop shell
is restored from.

## License / attribution

MIT License, Copyright (c) 2026 Caho1. The full upstream license is
kept verbatim in `LICENSE` in this directory, as the MIT license
requires. Nothing in this directory is ZN-owned code.

## Iron rule: verbatim restoration, no redesign

The user’s standing instruction for this restoration is: **we could not
design a good desktop ourselves, so we do not redesign, do not add our
own taste, and do not “improve” anything.** The shell stage does exactly
two things:

1. **Assemble** — compose the vendored components and tokens into the
   desktop shell, exactly as shipped.
2. **Wire ZN backend** — connect those components to ZN’s real
   conversation / Work / approval / routine data sources.

That is all. In particular:

- **Do not edit any file under `vendor/open-claude-ui/` to change how
  something looks.** No token value tweaks, no restyling, no
  “adaptation” edits to a component’s visuals, no stripping Tailwind
  classes or framer-motion usage to fit ZN’s old look.
- **Do not fork a vendored component to make it prettier.** If ZN needs
  different behaviour around a component, wrap it from outside
  (`apps/desktop/src/zn/...`); the vendored file stays untouched.
- **ZN-specific code lives outside `vendor/`.** Bridging, data wiring,
  IPC, and ZN state belong in ZN-owned files, never in a vendored file.
- **Updates are re-vendoring, not hand edits.** Re-copy from a pinned
  upstream commit, update `VENDOR.json`, and re-verify with
  `diff -r` + the TypeScript check below.

Upstream prose files were renamed (`README.md` →
`UPSTREAM-README.md`, etc.) so they cannot be mistaken for ZN’s own
README; their contents are byte-identical. `src/`, `code-examples/`,
`docs/`, and `scripts/` are byte-identical to upstream (`diff -r`
clean). Upstream agent-instruction files (`AGENTS.md`, `CLAUDE.md`,
`.cursorrules`) were deliberately **not** vendored: they are the
upstream repo’s agent guidance, not ZN’s.

## What this is — and is not

`open-claude-ui` is a **component library + motion engine**, not a
complete runnable app. It has no app entry point, no routing, no data
layer, and no ZN backend wiring. The shell stage supplies all of that
by assembling these pieces around ZN’s existing desktop host
(`apps/desktop`, Electron main / preload stay ZN-owned).

## Inventory (counted from the vendored files)

### Entry point

| File | What it is |
| --- | --- |
| `src/index.ts` | Barrel: 33 `export *` lines re-exporting every module below |
| `src/types.d.ts` | React `CSSProperties` augmentation: `WebkitAppRegion` (`drag` / `no-drag`) + `` `--${string}` `` custom properties, so CDS tokens type-check in inline styles |

### `code-examples/` — 36 files: 33 TS/TSX modules + 2 stylesheets + Tailwind config

**A. Foundational atoms & controls (5)**

| File | Main export | Notes |
| --- | --- | --- |
| `CdsButton.tsx` | `CdsButton` (+ `ButtonVariant`, `ButtonSize`) | Variants primary/secondary/ghost/danger/brand/onContent/outline; sizes xxs–lg + icon |
| `SegmentedControl.tsx` | `SegmentedControl` | Framer Motion `layoutId` sliding capsule; imports `framer-motion` |
| `StatusIndicators.tsx` | `StatusDot`, `ClayBreatheDot`, `PulseRunningDot`, `QuietDotsWave`, `SkeletonSweep` | 6px status dots, breathing / pulse / wave / skeleton sweep |
| `ConfirmationDialog.tsx` | `ConfirmationDialog` | Modal, AnimatePresence; imports `framer-motion` |
| `AttachmentCard.tsx` | `AttachmentCard` (+ `FileCategory`) | File tile / inline capsule |

**B. Chat stream & composer engine (6)**

| File | Main export | Notes |
| --- | --- | --- |
| `ChatComposer.tsx` | `ChatComposer` (+ `CLAUDE_MODELS`, `AttachmentItem`) | Main composer |
| `ChatMessageBubbles.tsx` | `UserMessageBubble`, `AssistantMessageBubble` | Message bubbles, attachment / artifact previews |
| `ThinkingAccordion.tsx` | `ThinkingAccordion` | Thinking-process state machine fold |
| `RichComposerWithMentions.tsx` | `RichComposerWithMentions` | Slash commands + mentions; CJK IME composition guard |
| `ModelSwitcherWithTokenGauge.tsx` | `ModelSwitcherWithTokenGauge` | Model tiers + token gauge |
| `McpToolDecisionCard.tsx` | `McpToolDecisionCard` (+ `ToolExecutionStatus`, `SettleReason`) | Tool-call approval card — the closest analogue to ZN’s approval card |

**C. Motion physics, shaders & ambience (3)**

| File | Main export | Notes |
| --- | --- | --- |
| `ClaudeMotionPresets.ts` | `SPRING_BOUNCY/SNAPPY/GENTLE/HEAVY_SNAP`, `CDS_EASING`, `motionMessageFadeUp`, `motionUserBubbleEnter`, `motionPopover`, `motionModalDialog`, `motionGraphemeReveal`, `calcDampedHarmonicOscillator` | Spring presets + damped-harmonic-oscillator solver; imports `framer-motion` types |
| `ReasoningAmbientGlow.tsx` | `ReasoningAmbientGlow`, `ShimmerText`, `ThreePhasePulseDots`, `LinearSweepProgress` | Ambient glow / shimmer / pulse |
| `ScrollFadeContainer.tsx` | `ScrollFadeContainer` | Scroll-edge fade wrapper (`data-cds-scroll-fade`) |

**D. Audiovisual & artifacts (8)**

| File | Main export | Notes |
| --- | --- | --- |
| `ClaudeAudioPlayer.ts` | `ClaudeAudioPlayer` (singleton) | Web Audio `OscillatorNode` synthetic SFX — **zero audio files**, no `.mp3` |
| `LiveMicActivityBars.tsx` | `LiveMicActivityBars` (+ `VoiceMode`) | Mic activity bars; imports `framer-motion` |
| `MediaLightboxViewer.tsx` | `MediaLightboxViewer` | Gallery with cursor-anchored Pan/Zoom |
| `useClaudeSharedElementTransition.ts` | `useClaudeSharedElementTransition` | Shared-element transition hook |
| `ArtifactsSplitPaneResizer.tsx` | `ArtifactsSplitPaneResizer` | Split pane: 4px dead zone, double-click 50/50 snap, iframe shield |
| `EpitaxyIframeBridge.tsx` | `EpitaxyIframeBridge` (+ `EpitaxyMimeType`) | Sandboxed artifact preview bridge |
| `StreamingDiffViewer.tsx` | `StreamingDiffViewer`, `parseGitDiff` | Streaming diff, Shadow-DOM isolated highlighting |
| `CodeBlock.tsx` | `CodeBlock` | Code block |

**E. Desktop host & multi-agent topology (8)**

| File | Main export | Notes |
| --- | --- | --- |
| `createClaudeMainWindow.ts` | `createClaudeMainWindow()` | **Reference only.** Imports `electron`, macOS traffic-light geometry compensation. ZN’s Electron main stays ZN-owned; do not swap it for this. |
| `ClaudeDesktopHeader.tsx` | `ClaudeDesktopHeader` | macOS immersive header |
| `DraggableSessionList.tsx` | `DraggableSessionList` (+ `SidebarSession`) | Draggable session list |
| `CoworkAgentCanvas.tsx` | `CoworkAgentCanvas` (+ `AgentStatus`, `CoworkAgent`, `SharedArtifact`) | Multi-agent canvas |
| `useClaudeScrollPinning.ts` | `useClaudeScrollPinning` | 150ms cooldown + 40px tolerance scroll pinning |
| `ContainerResponsiveBar.tsx` | `ContainerResponsiveBar` | Container-responsive bar |
| `useClaudeRovingFocus.ts` | `useClaudeRovingFocus` | Roving-focus keyboard nav |
| `useRateLimitBackoff.ts` | `useRateLimitBackoff` | Rate-limit backoff hook |

**F. CDS 2.0 / reasoning controls (3)**

| File | Main export | Notes |
| --- | --- | --- |
| `ModelSelectorEffort.tsx` | `ModelSelectorEffort` (+ `EffortLevel`, `EFFORT_META`) | Effort low/medium/high/xhigh/max |
| `ChatComposerChin.tsx` | `ChatComposerChin` | Composer “chin” bar |
| `CdsMotionEngine.tsx` | `CdsMotionEngine` | Motion-engine demo component |

Count note: upstream prose says “30 modules”; the files actually
contain **33 TS/TSX modules** (26 `.tsx` + 7 `.ts`), and `src/index.ts`
has 33 re-exports. This README reports the counted 33.

### Styles / tokens — the directly reusable layer

| File | What it is | Shell use |
| --- | --- | --- |
| `code-examples/cds-theme.css` (933 lines) | Full CDS theme: **183 defined `--cds-*` design tokens** (verified by upstream `scripts/check-tokens.mjs`: “定义: 183 个 token”), keyframes, utility classes, dark mode, retina hairline compensation, `@property` scroll-fade | **Import as-is.** This is the primary portable layer — no React needed |
| `code-examples/cds-pure.css` | `@import "./cds-theme.css"` + zero-JS / zero-React distribution layer: Chromium 115+ native CSS scroll-driven fade masks, pure-CSS animations | **Import as-is** for non-React / Electron-shell surfaces |
| `code-examples/tailwind.config.js` | Tailwind theme mapping tokens → `clay` / `surface` colors, font stacks, radii, shadows, animations | Reference for Tailwind hosts; token values come from `cds-theme.css` |

Token families in `cds-theme.css` (§0–§15): optical rem scale
(`--cds-rem-scale: calc(16/17)`), brand / clay, 35-step grayscale ramp,
35-step orange/clay ramp, surfaces (light + dark), alpha / border,
dual-ring popover, elevation + composer shadows, focus glow,
interaction fills / text steps, precision radii, chat layout metrics,
scroll-fade (28px), full physics Bézier set, font stacks (system
fallback + CJK chains), semantic component aliases + backward-compat
aliases. Non-`--cds-*` vars also exist (`--brand`, `--radius-*`,
`--font-*`, `--df-radius-pill`, …) and ship with the file — do not
strip them.

### The 8 interaction-physics algorithms (from `UPSTREAM-README.md`)

1. 7-stop non-linear fade mask (`y ≈ x^1.5` power-law alpha steps).
2. Mic 8% noise-floor gating + Web Audio oscillator synthetic SFX.
3. CJK IME composition double-interlock guard
   (`!(isComposing || keyCode === 229)`).
4. 150ms cooldown timestamp + 40px tolerance scroll-pinning.
5. Cursor-as-fixed-point affine Pan/Zoom equation (+ 4px dead zone,
   viewport overflow damping `y = 0.7`).
6. Mic 6-band non-linear Gamma (`0.7` power) energy compression.
7. Shadow DOM isolation + CSS Grid row-height hard lock for diff view.
8. Iframe event anti-swallow shield + double-click 50/50 snap.

### Docs & reference (`docs/`)

- `docs/v1/` — 8 chapters (design philosophy + tokens; atoms; session
  flow; motion physics; audiovisual/artifacts; desktop architecture;
  engineering config + module inventory; AI-agent UI guide) + combined
  `Claude Design System (CDS).full.md`.
- `docs/v2/` — 6 chapters on Claude Desktop 2.0 + combined
  `Claude-Desktop-2.0-全量分析.full.md`.
- `docs/claude-components-storybook.html` — single-file offline
  Storybook preview (open in a browser; preview only, not a shell).
- `docs/README.md` — docs index.
- `scripts/check-tokens.mjs` — upstream token gate: asserts every
  `` `--cds-*` `` referenced in upstream `AGENTS.md` is defined in
  `cds-theme.css`. Note: upstream `AGENTS.md` itself was intentionally
  **not** vendored (see `VENDOR.json`), so this script’s documented
  input is absent here; the token claim was verified against the
  upstream checkout instead (183 defined, all references resolved).

## What the shell can use directly vs. what needs wiring

| Tier | Pieces | Shell action |
| --- | --- | --- |
| Direct import, no JS | `cds-theme.css`, `cds-pure.css` | Import verbatim into the shell stylesheet |
| Pure logic, no React | `ClaudeAudioPlayer`, `ClaudeMotionPresets`, hooks (`useClaudeScrollPinning`, `useClaudeRovingFocus`, `useRateLimitBackoff`, `useClaudeSharedElementTransition`) | Import + call with ZN data |
| React components, no extra deps beyond React | Most `.tsx` components | Render with ZN data; **do not restyle** |
| React components needing `framer-motion` | `SegmentedControl`, `ConfirmationDialog`, `LiveMicActivityBars`, `ClaudeMotionPresets` (types) | Shell must provide the `framer-motion` peer dep — **do not** rewrite these to drop the dependency |
| Reference only, not ZN code | `createClaudeMainWindow.ts` (imports `electron`, macOS-only geometry) | Read for window-geometry reference; ZN Electron main stays ZN-owned |
| Declared but unused peer | `lucide-react` (`>=0.280.0` in upstream `peerDependencies`; no import found in vendored code) | Shell does not need it unless a future component uses it |

Constraints the shell must respect (no visual “adaptation”):

- ZN desktop currently pins `react` 19.2.7; upstream peers say
  `react >= 18`. Verify at shell build time; do not fork components
  to paper over a version gap.
- ZN desktop has no Tailwind and no `framer-motion` today, and 26
  `.tsx` files use Tailwind `className`s. The shell must supply the
  styling runtime the components were written against (Tailwind
  config is vendored as `tailwind.config.js`) — **not** strip or
  rewrite classes to match ZN’s old look.
- `createClaudeMainWindow.ts` is macOS traffic-light geometry for
  Claude’s window; ZN’s own window-bounds / shell HTML code is
  authoritative for ZN’s window.

## Proprietary assets: none introduced

Upstream’s stated policy (its `assets/README.md`, not vendored) is
that it distributes **no** proprietary binary assets: no commercial
variable fonts (`.ttf`), no voice-mode recordings (`.mp3`), no
official commercial marks. Verified for this snapshot:

- `find vendor/open-claude-ui -type f -exec file` → all text / HTML /
  CSS / JSON, **zero binary files**; no `.ttf`, `.mp3`, `.woff`,
  `.png`, `.icns`, or other binary assets.
- Fonts are system fallback stacks only (San Francisco / Segoe UI /
  Roboto; New York / Georgia / Cambria serif; SF Mono / Menlo /
  Consolas mono) — see `cds-theme.css` §13 and
  `tailwind.config.js` `fontFamily`.
- Sound is the `OscillatorNode` synthetic engine in
  `ClaudeAudioPlayer.ts` — zero external audio files.
- `assets/` (upstream logo + compliance README) was excluded from
  vendoring; see `VENDOR.json`.

## Verification

TypeScript verification is run against an exact copy of this directory
in `/tmp` (so no `node_modules` / `dist` ever lands in the repo):

```sh
cp -r vendor/open-claude-ui /tmp/ocu-verify
cp /tmp/open-claude-ui/package-lock.json /tmp/ocu-verify/package-lock.json
cd /tmp/ocu-verify && npm ci
npx tsc --noEmit            # upstream typecheck (strict: false, its own tsconfig)
npm run build               # tsc -p tsconfig.build.json, emits dist/ in /tmp only
```

Upstream’s own `check:tokens` was run against the upstream checkout:
`定义: 183 个 token`, all 36 referenced tokens resolved, exit 0.
The vendored `cds-theme.css` is byte-identical to upstream
(`diff -r` clean), so the token claim carries over verbatim.

`vendor/open-claude-ui/` is intentionally **not** in
`apps/desktop/tsconfig.json`’s `include` (which covers only
`src/zn` + `localization/`), so vendoring cannot change ZN desktop’s
own typecheck. ZN-owned shell wiring code lives under
`apps/desktop/src/zn/` and is type-checked under ZN’s `strict: true`
config.
