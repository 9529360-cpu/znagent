#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'

export const PRODUCT_CONTRACT_WORKFLOWS = [
  '.github/workflows/zn-managed-browser-contract.yml',
  '.github/workflows/zn-windows-interactive-contract.yml',
  '.github/workflows/zn-work-recovery-contract.yml',
  '.github/workflows/zn-windows-clean-install.yml'
]

function stripYamlScalar(value) {
  const trimmed = value.trim()
  if (
    (trimmed.startsWith("'") && trimmed.endsWith("'")) ||
    (trimmed.startsWith('"') && trimmed.endsWith('"'))
  ) {
    return trimmed.slice(1, -1)
  }
  return trimmed
}

export function pullRequestPaths(workflowText) {
  const lines = workflowText.split(/\r?\n/)
  let inPullRequest = false
  let inPaths = false
  const patterns = []

  for (const line of lines) {
    if (/^  pull_request:\s*$/.test(line)) {
      inPullRequest = true
      inPaths = false
      continue
    }
    if (inPullRequest && /^  [A-Za-z0-9_-]+:\s*$/.test(line)) break
    if (!inPullRequest) continue

    if (/^    paths:\s*$/.test(line)) {
      inPaths = true
      continue
    }
    if (inPaths && /^    [A-Za-z0-9_-]+:\s*$/.test(line)) {
      inPaths = false
      continue
    }
    if (!inPaths) continue

    const match = line.match(/^      -\s+(.+?)\s*$/)
    if (match) patterns.push(stripYamlScalar(match[1]))
  }

  return patterns
}

function globRegex(pattern) {
  let source = '^'
  for (let i = 0; i < pattern.length; i += 1) {
    const char = pattern[i]
    if (char === '*') {
      if (pattern[i + 1] === '*') {
        i += 1
        source += '.*'
      } else {
        source += '[^/]*'
      }
      continue
    }
    if (char === '?') {
      source += '[^/]'
      continue
    }
    source += char.replace(/[|\\{}()[\]^$+?.]/g, '\\$&')
  }
  return new RegExp(`${source}$`)
}

export function matchesPathFilters(filePath, patterns) {
  let matched = false
  for (const raw of patterns) {
    const negative = raw.startsWith('!')
    const pattern = negative ? raw.slice(1) : raw
    if (!pattern || !globRegex(pattern).test(filePath)) continue
    matched = !negative
  }
  return matched
}

export function requiredProductContracts(changedFiles, workflowSources) {
  const required = []
  for (const workflowPath of PRODUCT_CONTRACT_WORKFLOWS) {
    const source = workflowSources[workflowPath]
    if (typeof source !== 'string') {
      throw new Error(`missing product contract workflow source: ${workflowPath}`)
    }
    const patterns = pullRequestPaths(source)
    if (patterns.length === 0) {
      throw new Error(`product contract workflow has no pull_request.paths: ${workflowPath}`)
    }
    if (changedFiles.some(file => matchesPathFilters(file, patterns))) {
      required.push(workflowPath)
    }
  }
  return required
}

async function githubJson(url, token) {
  const response = await fetch(url, {
    headers: {
      Accept: 'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'ZN-Product-Required-Gate/1'
    }
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`GitHub API ${response.status} for ${url}: ${body.slice(0, 500)}`)
  }
  return await response.json()
}

async function pullRequestFiles({ apiUrl, repository, pullNumber, token }) {
  const files = []
  for (let page = 1; ; page += 1) {
    const url = `${apiUrl}/repos/${repository}/pulls/${pullNumber}/files?per_page=100&page=${page}`
    const batch = await githubJson(url, token)
    for (const item of batch) {
      if (typeof item?.filename === 'string') files.push(item.filename)
    }
    if (batch.length < 100) break
  }
  return files
}

async function workflowRunsForHead({ apiUrl, repository, headSha, token }) {
  const params = new URLSearchParams({
    event: 'pull_request',
    head_sha: headSha,
    per_page: '100'
  })
  const url = `${apiUrl}/repos/${repository}/actions/runs?${params}`
  const payload = await githubJson(url, token)
  return Array.isArray(payload?.workflow_runs) ? payload.workflow_runs : []
}

function runForWorkflow(runs, workflowPath, pullNumber) {
  return runs
    .filter(run =>
      run?.path === workflowPath &&
      run?.head_sha &&
      Array.isArray(run?.pull_requests) &&
      run.pull_requests.some(item => Number(item?.number) === Number(pullNumber))
    )
    .sort((left, right) => Number(right.id || 0) - Number(left.id || 0))[0] || null
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function main() {
  const eventPath = process.env.GITHUB_EVENT_PATH
  const token = process.env.GITHUB_TOKEN
  const repository = process.env.GITHUB_REPOSITORY
  const apiUrl = process.env.GITHUB_API_URL || 'https://api.github.com'

  if (!eventPath || !token || !repository) {
    throw new Error('GITHUB_EVENT_PATH, GITHUB_TOKEN and GITHUB_REPOSITORY are required')
  }

  const event = JSON.parse(fs.readFileSync(eventPath, 'utf8'))
  if (!event?.pull_request) {
    console.log('product_gate.mode=non_pull_request')
    return
  }

  const pullNumber = Number(event.pull_request.number)
  const headSha = String(event.pull_request.head?.sha || '')
  if (!Number.isSafeInteger(pullNumber) || pullNumber <= 0 || !/^[0-9a-f]{40}$/i.test(headSha)) {
    throw new Error('pull request event is missing a valid number or head SHA')
  }

  const changedFiles = await pullRequestFiles({ apiUrl, repository, pullNumber, token })
  const workflowSources = Object.fromEntries(
    PRODUCT_CONTRACT_WORKFLOWS.map(workflowPath => [
      workflowPath,
      fs.readFileSync(path.resolve(workflowPath), 'utf8')
    ])
  )
  const required = requiredProductContracts(changedFiles, workflowSources)

  console.log(`product_gate.head_sha=${headSha}`)
  console.log(`product_gate.changed_files=${changedFiles.length}`)
  console.log(`product_gate.required=${required.length ? required.join(',') : 'none'}`)

  if (required.length === 0) return

  const deadline = Date.now() + 50 * 60 * 1000
  let lastSummary = ''

  while (Date.now() < deadline) {
    const runs = await workflowRunsForHead({ apiUrl, repository, headSha, token })
    const states = required.map(workflowPath => {
      const run = runForWorkflow(runs, workflowPath, pullNumber)
      return {
        workflowPath,
        id: run?.id || null,
        status: run?.status || 'missing',
        conclusion: run?.conclusion || null,
        htmlUrl: run?.html_url || null
      }
    })

    const summary = states
      .map(item => `${item.workflowPath}=${item.status}/${item.conclusion || '-'}`)
      .join(' | ')
    if (summary !== lastSummary) {
      console.log(`product_gate.state=${summary}`)
      lastSummary = summary
    }

    const failed = states.filter(item =>
      item.status === 'completed' && !['success', 'neutral', 'skipped'].includes(item.conclusion)
    )
    if (failed.length) {
      throw new Error(
        `required product contract failed: ${failed.map(item => `${item.workflowPath} (${item.htmlUrl || item.id})=${item.conclusion}`).join(', ')}`
      )
    }

    if (states.every(item => item.status === 'completed' && item.conclusion === 'success')) {
      console.log('product_gate.result=success')
      return
    }

    await sleep(30_000)
  }

  throw new Error(
    `timed out waiting for required product contracts for head ${headSha}; latest state: ${lastSummary}`
  )
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname.replace(/^\/(.:)/, '$1'))) {
  await main()
}
