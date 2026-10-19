/**
 * ZN-owned CSS property augmentation for the vendored open-claude-ui components.
 *
 * Vendor's own `vendor/open-claude-ui/src/types.d.ts` declares the same
 * augmentation, but the shell does not import that file (it would also pull a
 * .d.ts into the esbuild bundle). This ZN-side copy keeps the vendor files
 * untouched while letting `ClaudeDesktopHeader`'s WebkitAppRegion styles
 * typecheck. If the vendor augmentation ever changes, mirror it here.
 */
import 'react'

declare module 'react' {
  interface CSSProperties {
    WebkitAppRegion?: 'drag' | 'no-drag'
  }
}
