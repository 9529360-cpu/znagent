import { app } from 'electron'

import { checkZnResidentApplicationUpdateReadiness } from './zn-resident-update-readiness'

export type ZnReleaseApplicationGateResult = {
  ok: boolean
  message?: string
  error?: string
}

export async function applyZnReleaseInstallerWithResidentGate({
  version,
  handoff
}: {
  version: string
  handoff: () => Promise<void>
}): Promise<ZnReleaseApplicationGateResult> {
  const readiness = await checkZnResidentApplicationUpdateReadiness()

  if (!readiness.ready) {
    return {
      ok: false,
      error: readiness.reason === 'busy' ? 'resident-busy' : 'resident-unavailable',
      message: readiness.message
    }
  }

  await handoff()
  setTimeout(() => app.quit(), 100)
  return { ok: true, message: `installing ZN ${version}` }
}
