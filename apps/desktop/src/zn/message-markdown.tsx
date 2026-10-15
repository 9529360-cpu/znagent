import { Fragment, type ReactNode } from 'react'

const TICK = String.fromCharCode(96)
const MAX_RENDER_CHARS = 150_000

function safeExternalLink(value: string): string | null {
  try {
    const url = new URL(value)
    // Model/user Markdown is untrusted. Electron's main process separately
    // validates external navigation; never hand it an executable URL scheme.
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
  } catch {
    return null
  }
}

function Inline({ value }: { value: string }) {
  const output: ReactNode[] = []
  let plain = ''
  let index = 0
  const flush = () => {
    if (plain) {
      output.push(plain)
      plain = ''
    }
  }

  while (index < value.length) {
    const char = value[index]
    if (char === TICK) {
      const end = value.indexOf(TICK, index + 1)
      if (end > index + 1) {
        flush()
        output.push(<code key={index}>{value.slice(index + 1, end)}</code>)
        index = end + 1
        continue
      }
    }
    if (value.startsWith('**', index)) {
      const end = value.indexOf('**', index + 2)
      if (end > index + 2) {
        flush()
        output.push(<strong key={index}>{value.slice(index + 2, end)}</strong>)
        index = end + 2
        continue
      }
    }
    if (char === '*' && value[index + 1] !== '*') {
      const end = value.indexOf('*', index + 1)
      if (end > index + 1) {
        flush()
        output.push(<em key={index}>{value.slice(index + 1, end)}</em>)
        index = end + 1
        continue
      }
    }
    if (char === '[') {
      const separator = value.indexOf('](', index + 1)
      const end = separator >= 0 ? value.indexOf(')', separator + 2) : -1
      if (separator > index + 1 && end > separator + 2) {
        const label = value.slice(index + 1, separator)
        const destination = value.slice(separator + 2, end)
        const safe = safeExternalLink(destination)
        flush()
        output.push(safe
          ? <a key={index} href={safe} target="_blank" rel="noopener noreferrer">{label}</a>
          : <span key={index}>{label} ({destination})</span>)
        index = end + 1
        continue
      }
    }
    if (char === '$' && value[index + 1] !== '$') {
      const end = value.indexOf('$', index + 1)
      if (end > index + 1) {
        flush()
        // TeX is displayed as text until a reviewed offline math renderer
        // is added. Never compile arbitrary model-provided TeX into HTML.
        output.push(<code className="zn-md-math-inline" key={index}>{value.slice(index + 1, end)}</code>)
        index = end + 1
        continue
      }
    }
    plain += char
    index += 1
  }
  flush()
  return <>{output}</>
}

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim())
}

function isTableDivider(line: string): boolean {
  const columns = cells(line)
  return columns.length > 0 && columns.every(column => /^:?-{3,}:?$/.test(column))
}

function isSpecialLine(line: string): boolean {
  const trimmed = line.trim()
  return trimmed.startsWith(TICK.repeat(3)) ||
    trimmed.startsWith('~~~') ||
    trimmed.startsWith('$$') ||
    /^#{1,6}\s/.test(trimmed) ||
    /^>\s?/.test(trimmed) ||
    /^[-*+]\s+/.test(trimmed) ||
    /^\d+\.\s+/.test(trimmed) ||
    /^(-{3,}|\*{3,})$/.test(trimmed)
}

function blocks(source: string): ReactNode[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const output: ReactNode[] = []
  let line = 0
  while (line < lines.length) {
    const trimmed = lines[line].trim()
    if (!trimmed) {
      line += 1
      continue
    }
    const fence = trimmed.startsWith(TICK.repeat(3))
      ? TICK.repeat(3) : trimmed.startsWith('~~~') ? '~~~' : null
    if (fence) {
      const language = trimmed.slice(3).split(/\s/)[0].replace(/[^a-zA-Z0-9_+#-]/g, '').slice(0, 32)
      const body: string[] = []
      line += 1
      while (line < lines.length && !lines[line].trim().startsWith(fence)) {
        body.push(lines[line])
        line += 1
      }
      if (line < lines.length) line += 1
      output.push(<pre key={output.length} className="zn-md-code"><code data-language={language || undefined}>{body.join('\n')}</code></pre>)
      continue
    }
    if (trimmed.startsWith('$$')) {
      const formula = [trimmed.slice(2)]
      line += 1
      while (line < lines.length && !lines[line].trim().endsWith('$$')) {
        formula.push(lines[line])
        line += 1
      }
      if (line < lines.length) {
        formula.push(lines[line].trim().slice(0, -2))
        line += 1
      }
      output.push(<pre key={output.length} className="zn-md-math"><code>{formula.join('\n').trim()}</code></pre>)
      continue
    }
    const heading = /^(#{1,6})\s+(.+)$/.exec(trimmed)
    if (heading) {
      const level = heading[1].length
      const tag = ('h' + level) as 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6'
      output.push(<Fragment key={output.length}>{(() => {
        const Tag = tag
        return <Tag><Inline value={heading[2]} /></Tag>
      })()}</Fragment>)
      line += 1
      continue
    }
    if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
      output.push(<hr key={output.length} />)
      line += 1
      continue
    }
    if (line + 1 < lines.length && lines[line].includes('|') && isTableDivider(lines[line + 1])) {
      const header = cells(lines[line])
      const rows: string[][] = []
      line += 2
      while (line < lines.length && lines[line].trim() && lines[line].includes('|')) {
        rows.push(cells(lines[line]))
        line += 1
      }
      output.push(
        <div className="zn-md-table-scroll" key={output.length}>
          <table>
            <thead><tr>{header.map((cell, index) => <th key={index} scope="col"><Inline value={cell} /></th>)}</tr></thead>
            <tbody>{rows.map((row, rowIndex) =>
              <tr key={rowIndex}>{header.map((_, cellIndex) =>
                <td key={cellIndex}><Inline value={row[cellIndex] || ''} /></td>)}</tr>)}</tbody>
          </table>
        </div>
      )
      continue
    }
    if (/^[-*+]\s+/.test(trimmed) || /^\d+\.\s+/.test(trimmed)) {
      const ordered = /^\d+\.\s+/.test(trimmed)
      const entries: string[] = []
      while (line < lines.length) {
        const item = lines[line].trim()
        const matched = ordered ? /^\d+\.\s+(.+)$/.exec(item) : /^[-*+]\s+(.+)$/.exec(item)
        if (!matched) break
        entries.push(matched[1])
        line += 1
      }
      const items = entries.map((item, index) => <li key={index}><Inline value={item} /></li>)
      output.push(ordered ? <ol key={output.length}>{items}</ol> : <ul key={output.length}>{items}</ul>)
      continue
    }
    if (/^>\s?/.test(trimmed)) {
      const quotes: string[] = []
      while (line < lines.length && /^>\s?/.test(lines[line].trim())) {
        quotes.push(lines[line].trim().replace(/^>\s?/, ''))
        line += 1
      }
      output.push(<blockquote key={output.length}><Inline value={quotes.join(' ')} /></blockquote>)
      continue
    }
    const paragraph: string[] = []
    while (line < lines.length && lines[line].trim() && (paragraph.length === 0 || !isSpecialLine(lines[line]))) {
      if (paragraph.length > 0 && line + 1 < lines.length && lines[line].includes('|') && isTableDivider(lines[line + 1])) break
      paragraph.push(lines[line].trim())
      line += 1
    }
    output.push(<p key={output.length}><Inline value={paragraph.join(' ')} /></p>)
  }
  return output
}

export function ZnMessageMarkdown({ source }: { source: string }) {
  // Bounded rendering prevents a hostile tool result from exhausting the
  // renderer; full text remains in Resident Work and in the copy/export paths.
  const bounded = source.slice(0, MAX_RENDER_CHARS)
  return (
    <div className="zn-markdown">
      {blocks(bounded)}
      {source.length > MAX_RENDER_CHARS ? <p className="zn-md-truncated">Message preview truncated. Copy or export for the full text.</p> : null}
    </div>
  )
}
