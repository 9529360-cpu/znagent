import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ZnDesktopErrorBoundary } from './error-boundary'
import { ZnDesktopRoot } from './zn-claude-shell'
// Vendor 令牌（cds-theme.css）+ vendor Tailwind 类名的机械映射胶水。
// 旧工作台的 CSS（styles.css 等）不再由入口引入；workbench.tsx 文件
// 保留在原地，供接线工人对照 resident-client 调用实现真实数据钩子。
import '../../../../vendor/open-claude-ui/code-examples/cds-theme.css'
import './zn-vendor-compat.css'
import './zn-claude-shell.css'

document.title = 'ZN'

const root = document.getElementById('root')
if (!root) throw new Error('ZN renderer root is missing')

createRoot(root).render(
  <StrictMode>
    <ZnDesktopErrorBoundary>
      <ZnDesktopRoot />
    </ZnDesktopErrorBoundary>
  </StrictMode>
)
