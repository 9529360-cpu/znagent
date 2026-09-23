export function isZnResidentConnectionError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return /Error invoking remote method ['"]zn:resident:|resident service did not become reachable|resident-endpoint\.json/i.test(message)
}
