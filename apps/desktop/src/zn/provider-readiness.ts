export type ZnProviderReadinessKind =
  | 'checking'
  | 'ready'
  | 'not_configured'
  | 'unavailable'

export type ZnProviderReadinessSettings = {
  provider: string
  model: string
  cognitionAvailable: boolean
  configurationError?: string
  activeRoutes: Array<{ id: string; provider: string; model: string }>
}

export type ZnProviderReadiness = {
  kind: ZnProviderReadinessKind
  ready: boolean
  headline: string
  detail: string
}

export function describeZnProviderReadiness(
  settings: ZnProviderReadinessSettings | null
): ZnProviderReadiness {
  if (!settings) {
    return {
      kind: 'checking',
      ready: false,
      headline: 'Checking model connection',
      detail: 'ZN is checking whether a model is available for open-ended reasoning.'
    }
  }

  if (settings.cognitionAvailable) {
    const active = settings.activeRoutes[0]
    const route = active
      ? `${active.provider} · ${active.model}`
      : [settings.provider, settings.model].filter(Boolean).join(' · ')
    return {
      kind: 'ready',
      ready: true,
      headline: 'Model connection ready',
      detail: route || 'A model is available for open-ended reasoning.'
    }
  }

  const configurationError = settings.configurationError?.trim()
  if (configurationError) {
    return {
      kind: 'unavailable',
      ready: false,
      headline: 'Model setup needs attention',
      detail: configurationError
    }
  }

  if (!settings.model.trim()) {
    return {
      kind: 'not_configured',
      ready: false,
      headline: 'No model configured yet',
      detail:
        'ZN can still handle local and deterministic tasks, but open-ended reasoning needs a configured provider and model.'
    }
  }

  return {
    kind: 'unavailable',
    ready: false,
    headline: 'Model connection is not available',
    detail:
      'The saved provider and model are not currently available. Check the provider, model, endpoint and credential.'
  }
}

export function providerUpdateNotice(settings: ZnProviderReadinessSettings): string {
  const readiness = describeZnProviderReadiness(settings)
  if (readiness.ready) return `Model ready. ${readiness.detail}`
  return `Settings saved, but the model connection is not ready. ${readiness.detail}`
}
