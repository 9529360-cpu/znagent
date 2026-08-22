type ZnResidentBridge = {
  start: () => Promise<unknown>
  status: () => Promise<unknown>
  self: () => Promise<unknown>
  submit: (payload: Record<string, unknown>) => Promise<unknown>
}

type ZnDesktopBridge = {
  resident: ZnResidentBridge
}

const bridge = (window as Window & { znDesktop?: ZnDesktopBridge }).znDesktop
const statusDot = document.getElementById('status-dot')
const statusLabel = document.getElementById('status-label')
const residentState = document.getElementById('resident-state')
const taskResult = document.getElementById('task-result')
const form = document.getElementById('task-form') as HTMLFormElement | null
const taskInput = document.getElementById('task-input') as HTMLTextAreaElement | null
const submitButton = document.getElementById('submit-button') as HTMLButtonElement | null
const refreshButton = document.getElementById('refresh-button') as HTMLButtonElement | null

function renderValue(value: unknown): string {
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function setHealth(state: 'connecting' | 'live' | 'offline', detail?: string): void {
  if (statusDot) statusDot.className = `dot${state === 'live' ? ' live' : state === 'offline' ? ' error' : ''}`
  if (statusLabel) statusLabel.textContent = detail || state
}

function setState(value: unknown, error = false): void {
  if (!residentState) return
  residentState.textContent = renderValue(value)
  residentState.classList.toggle('error-text', error)
}

async function refreshResident(): Promise<void> {
  if (!bridge?.resident) {
    setHealth('offline', 'desktop bridge unavailable')
    setState('window.znDesktop was not exposed by the ZN preload.', true)
    return
  }

  setHealth('connecting')
  try {
    let status: unknown
    try {
      status = await bridge.resident.status()
    } catch {
      status = await bridge.resident.start()
    }
    const [freshStatus, self] = await Promise.all([
      bridge.resident.status().catch(() => status),
      bridge.resident.self().catch(() => null)
    ])
    setHealth('live', 'resident live')
    setState({ status: freshStatus, self })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    setHealth('offline', 'resident offline')
    setState(message, true)
  }
}

form?.addEventListener('submit', event => {
  event.preventDefault()
  const task = taskInput?.value.trim() || ''
  if (!task || !bridge?.resident || !submitButton) return

  submitButton.disabled = true
  if (taskResult) {
    taskResult.textContent = 'Submitting event to the resident…'
    taskResult.classList.remove('error-text')
  }

  void bridge.resident
    .submit({ task, kind: 'desktop_user_event', priority: 0 })
    .then(result => {
      if (taskResult) taskResult.textContent = renderValue(result)
      return refreshResident()
    })
    .catch(error => {
      if (!taskResult) return
      taskResult.textContent = error instanceof Error ? error.message : String(error)
      taskResult.classList.add('error-text')
    })
    .finally(() => {
      submitButton.disabled = false
    })
})

refreshButton?.addEventListener('click', () => {
  void refreshResident()
})

void refreshResident()
