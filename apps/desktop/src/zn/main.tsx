import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ZnProviderOnboarding } from './provider-onboarding'
import './styles.css'

document.title = 'ZN'

const root = document.getElementById('root')
if (!root) throw new Error('ZN renderer root is missing')

createRoot(root).render(
  <StrictMode>
    <ZnProviderOnboarding />
  </StrictMode>
)
