import { group, split } from '@/components/pane-shell/tree/model'
import { declareDefaultTree } from '@/components/pane-shell/tree/store'
import { registry } from '@/contrib/registry'

import { ContribController } from './contrib'
import { ZnResidentStatus } from './zn/resident-status'

/**
 * ZN's default desktop posture is a workbench, not an IDE.
 *
 * The mature Hermes shell remains underneath as reusable infrastructure, but a
 * fresh ZN install opens with only conversations/navigation and the main work
 * surface. Files, review and terminal stay available through the existing pane
 * system and layout presets instead of occupying the default screen.
 */
export const ZN_WORKBENCH_TREE = split(
  'row',
  [group(['sessions'], { id: 'zn-grp-sessions' }), group(['workspace'], { id: 'zn-grp-main' })],
  [1, 4.8],
  'zn-spl-root'
)

// Core layout registration happens while ContribController is imported. ZN is
// intentionally the later writer: same contribution id means the normal layout
// picker/reset flow now resolves "default" to the product workbench.
registry.register({
  id: 'default',
  area: 'layouts',
  source: 'core',
  title: 'Workbench',
  order: 0,
  data: ZN_WORKBENCH_TREE
})

declareDefaultTree(ZN_WORKBENCH_TREE)

registry.register({
  id: 'zn.resident',
  area: 'statusBar.left',
  source: 'core',
  order: -100,
  render: () => <ZnResidentStatus />
})

export default function ZnWorkbench() {
  return <ContribController />
}
