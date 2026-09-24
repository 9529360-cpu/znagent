importScripts('research-background.js')

const baseSensitiveTextboxKind = sensitiveTextboxKind
const RECOVERY_CODE_MARKERS = [
  'recovery code',
  'recovery codes',
  'backup code',
  'backup codes',
  'emergency code',
  'emergency codes'
]

function normalizedSensitiveFieldMarker(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function hasSensitiveFieldPhrase(value, phrase) {
  const normalized = normalizedSensitiveFieldMarker(value)
  return normalized !== '' && ` ${normalized} `.includes(` ${phrase} `)
}

function hasRecoveryCodeMarker(attributes) {
  const values = [
    attributes?.id,
    attributes?.name,
    attributes?.placeholder,
    attributes?.['aria-label'],
    attributes?.title
  ]
  return values.some(value =>
    RECOVERY_CODE_MARKERS.some(marker => hasSensitiveFieldPhrase(value, marker))
  )
}

sensitiveTextboxKind = function (attributes) {
  const baseKind = baseSensitiveTextboxKind(attributes)
  if (baseKind) return baseKind

  // HTML has no recovery-code autocomplete token. Explicit structural recovery /
  // backup / emergency-code markers therefore join the already-verified
  // user-presence authentication-code class before any textbox value is read.
  if (hasRecoveryCodeMarker(attributes)) return 'one_time_code'
  return ''
}
