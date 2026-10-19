/**
 * CSS property augmentations for the vendored open-claude-ui components.
 *
 * The vendored files are verbatim upstream code and must not be edited, but
 * they use two CSS extensions ZN's strict renderer typecheck does not know:
 *
 * - `WebkitAppRegion` (Electron drag regions, used by ClaudeDesktopHeader);
 * - `--cds-*` custom properties (CDS design tokens, used by
 *   ScrollFadeContainer's fade-mask style object).
 *
 * This ZN-owned augmentation declares both, program-wide, so the vendored
 * components typecheck without any modification to vendor/.
 */
import type * as React from 'react'

declare module 'react' {
  interface CSSProperties {
    WebkitAppRegion?: 'drag' | 'no-drag' | (string & {})
    [key: `--${string}`]: string | number | undefined
  }
}

export type { React }
