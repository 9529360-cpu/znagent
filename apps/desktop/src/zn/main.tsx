import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ZnWorkbench } from './workbench'
import './styles.css'
import './liquid-performance.css'

document.title = 'ZN'

const root = document.getElementById('root')
if (!root) throw new Error('ZN renderer root is missing')

createRoot(root).render(
  <StrictMode>
    <ZnWorkbench />
  </StrictMode>
)
