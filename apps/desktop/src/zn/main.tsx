import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ZnDesktopErrorBoundary } from './error-boundary'
import { initializeZnDesktopI18n } from './i18n'
import { ZnWorkbench } from './workbench'
import './styles.css'
import './liquid-performance.css'
import './chat-shell.css'
import './desktop-resilience.css'
import './settings-shell.css'
import './gpt-desktop.css'

document.title = 'ZN'

async function renderZnDesktop(): Promise<void> {
  await initializeZnDesktopI18n()
  const root = document.getElementById('root')
  if (!root) throw new Error('ZN renderer root is missing')

  createRoot(root).render(
    <StrictMode>
      <ZnDesktopErrorBoundary>
        <ZnWorkbench />
      </ZnDesktopErrorBoundary>
    </StrictMode>
  )
}

void renderZnDesktop()
