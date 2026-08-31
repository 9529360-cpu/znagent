import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ZnMaintenanceReportControls } from './maintenance-report-controls'
import { ZnWorkbench } from './workbench'
import './styles.css'

document.title = 'ZN'

const root = document.getElementById('root')
if (!root) throw new Error('ZN renderer root is missing')

createRoot(root).render(
  <StrictMode>
    <ZnWorkbench />
    <ZnMaintenanceReportControls />
  </StrictMode>
)