/**
 * ZN desktop Tailwind configuration.
 *
 * The utility layer is the vendored open-claude-ui Tailwind config, verbatim:
 * theme tokens (CDS colors, radii, shadows, animations) come from upstream.
 * Only `content` is overridden so Tailwind scans the vendored components
 * (whose classNames are the styling contract) plus the thin ZN wrappers
 * under src/zn that compose them.
 */
const upstream = require('../../vendor/open-claude-ui/code-examples/tailwind.config.js')

module.exports = {
  ...upstream,
  content: [
    '../../vendor/open-claude-ui/code-examples/**/*.{js,ts,jsx,tsx}',
    './src/zn/**/*.{ts,tsx}'
  ]
}
