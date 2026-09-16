export type ZnProviderReadinessSettings = {
  provider: string
  model: string
  cognitionAvailable: boolean
  configurationError?: string
  activeRoutes: Array<{ id: string; provider: string; model: string }>
}

export type ZnProviderReadinessKind =
  | 'checking'
  | 'ready'
  | 'not_configured'
  | 'unavailable'

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
      headline: 'Checking model resources',
      detail: 'ZN is asking the resident for its current cognitive-resource state.'
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
      headline: 'Model resources ready',
      detail: route || 'The resident has an available cognitive route.'
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
      headline: 'No external model configured yet',
      detail:
        'ZN can still run resident and deterministic local paths, but model-backed work needs a provider and model.'
    }
  }

  return {
    kind: 'unavailable',
    ready: false,
    headline: 'Model route is not available',
    detail:
      'The saved provider and model do not currently produce an available cognitive route. Check the provider, model, endpoint and credential.'
  }
}

export function providerUpdateNotice(settings: ZnProviderReadinessSettings): string {
  const readiness = describeZnProviderReadiness(settings)
  if (readiness.ready) return `Model ready. ${readiness.detail}`
  return `Settings saved, but model-backed cognition is not ready. ${readiness.detail}`
}
