import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ZnProviderOnboarding } from './provider-onboarding'
import './styles.css'

document.title = 'ZN'

const root = document.getElementById('root')
if (!root) throw new Error('ZN renderer root is missing')

// ZnProviderOnboarding hands off to ZnWorkbench after Resident readiness is known.
createRoot(root).render(
  <StrictMode>
    <ZnProviderOnboarding />
  </StrictMode>
)
