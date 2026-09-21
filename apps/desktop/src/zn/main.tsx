import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { initializeZnDesktopI18n } from './i18n'
import { ZnWorkbench } from './workbench'
import './styles.css'
import './liquid-performance.css'

document.title = 'ZN'

async function renderZnDesktop(): Promise<void> {
  await initializeZnDesktopI18n()
  const root = document.getElementById('root')
  if (!root) throw new Error('ZN renderer root is missing')

  createRoot(root).render(
    <StrictMode>
      <ZnWorkbench />
    </StrictMode>
  )
}

void renderZnDesktop()
