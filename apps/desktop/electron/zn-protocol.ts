export type ZnDeepLink = {
  url: string
  route: string
  path: string
  params: Record<string, string>
}

const MAX_DEEP_LINK_LENGTH = 8_192

export function parseZnDeepLink(value: string): ZnDeepLink | null {
  const raw = String(value || '').trim()
  if (!raw || raw.length > MAX_DEEP_LINK_LENGTH) return null

  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    return null
  }
  if (parsed.protocol !== 'zn:') return null

  const params: Record<string, string> = {}
  for (const [key, item] of parsed.searchParams.entries()) {
    if (!(key in params)) params[key] = item
  }

  return {
    url: parsed.toString(),
    route: parsed.hostname.toLowerCase(),
    path: parsed.pathname,
    params
  }
}

export function znDeepLinksFromArgv(argv: readonly string[]): ZnDeepLink[] {
  const links: ZnDeepLink[] = []
  const seen = new Set<string>()
  for (const value of argv) {
    const parsed = parseZnDeepLink(value)
    if (!parsed || seen.has(parsed.url)) continue
    seen.add(parsed.url)
    links.push(parsed)
  }
  return links
}
