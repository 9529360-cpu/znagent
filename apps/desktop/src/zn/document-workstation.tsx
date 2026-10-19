import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { ZnArtifact } from './state'

export type ZnDocumentSection = {
  id: string
  heading: string
  paragraphs: string[]
  bullets: string[]
}

export type ZnDocumentSpec = {
  version: 1
  documentId: string
  title: string
  subtitle: string
  sections: ZnDocumentSection[]
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function stringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null
  if (value.some(item => typeof item !== 'string' || !item.trim())) return null
  return value.map(item => item.trim())
}

export function parseDocumentArtifact(artifact: ZnArtifact): ZnDocumentSpec | null {
  if (artifact.kind !== 'document' || !artifact.content) return null
  try {
    const raw = record(JSON.parse(artifact.content))
    if (!raw || raw.version !== 1) return null
    if (
      typeof raw.document_id !== 'string' ||
      typeof raw.title !== 'string' ||
      typeof raw.subtitle !== 'string' ||
      !Array.isArray(raw.sections)
    ) return null
    const sections: ZnDocumentSection[] = []
    for (let index = 0; index < raw.sections.length; index += 1) {
      const item = record(raw.sections[index])
      if (
        !item ||
        item.id !== `section-${index + 1}` ||
        typeof item.heading !== 'string'
      ) return null
      const paragraphs = stringList(item.paragraphs)
      const bullets = stringList(item.bullets)
      if (!paragraphs || !bullets || (!paragraphs.length && !bullets.length)) return null
      sections.push({
        id: item.id as string,
        heading: item.heading.trim(),
        paragraphs,
        bullets
      })
    }
    if (!sections.length || sections.length > 12) return null
    return {
      version: 1,
      documentId: raw.document_id,
      title: raw.title.trim(),
      subtitle: raw.subtitle.trim(),
      sections
    }
  } catch {
    return null
  }
}

type Props = {
  artifact: ZnArtifact
}

export function ZnDocumentWorkstation({ artifact }: Props) {
  const { t } = useTranslation()
  const spec = useMemo(() => parseDocumentArtifact(artifact), [artifact.content, artifact.id])
  const selectedFromArtifact = typeof artifact.metadata?.selected_section_id === 'string'
    ? artifact.metadata.selected_section_id
    : ''
  const [selectedSectionId, setSelectedSectionId] = useState(selectedFromArtifact)
  const paperRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!spec) return
    const next = spec.sections.some(section => section.id === selectedFromArtifact)
      ? selectedFromArtifact
      : spec.sections[0].id
    setSelectedSectionId(next)
  }, [artifact.content, selectedFromArtifact, spec])

  if (!spec) {
    return (
      <main className="flex flex-col gap-1 p-4">
        <strong>{t('workstation.documentUnavailable')}</strong>
        <span>{t('workstation.documentInvalid')}</span>
      </main>
    )
  }

  const selectedIndex = Math.max(
    0,
    spec.sections.findIndex(section => section.id === selectedSectionId)
  )

  const selectSection = (sectionId: string) => {
    setSelectedSectionId(sectionId)
    requestAnimationFrame(() => {
      paperRef.current
        ?.querySelector<HTMLElement>(`[data-document-section="${sectionId}"]`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  return (
    <main className="flex gap-3" aria-label={t('workstation.documentWorkspace')}>
      <aside className="flex w-44 shrink-0 flex-col gap-2" aria-label={t('workstation.documentOutline')}>
        <div className="flex flex-col gap-0.5 border-b border-[var(--cds-border)] pb-2">
          <span>{t('workstation.document')}</span>
          <strong title={spec.title}>{spec.title}</strong>
          <small>{t('workstation.sectionCount', { count: spec.sections.length })}</small>
        </div>
        <div className="flex flex-col gap-1">
          {spec.sections.map((section, index) => (
            <button
              type="button"
              key={section.id}
              className={'flex items-start gap-2 rounded-lg px-2 py-1.5 text-left text-sm ' + (section.id === selectedSectionId ? 'bg-[var(--cds-fill-ghost-selected)] text-[var(--cds-text-primary)]' : 'text-[var(--cds-text-secondary)] hover:bg-[var(--cds-fill-ghost-hover)]')}
              aria-label={t('workstation.sectionLabel', { index: index + 1, heading: section.heading })}
              onClick={() => selectSection(section.id)}
            >
              <span>{index + 1}</span>
              <strong>{section.heading}</strong>
            </button>
          ))}
        </div>
      </aside>

      <section className="min-w-0 flex-1">
        <header className="mb-2 flex items-baseline justify-between gap-2">
          <div>
            <span>{t('workstation.nativeDocument')}</span>
            <strong>{spec.sections[selectedIndex]?.heading || spec.title}</strong>
          </div>
          <small>{t('workstation.documentVersion')}</small>
        </header>
        <div className="max-h-[60vh] overflow-y-auto pr-1">
          <article className="rounded-xl bg-[var(--cds-surface-2)] px-6 py-5 shadow-[var(--cds-shadow-sm)]" ref={paperRef}>
            <header className="mb-4 border-b border-[var(--cds-border)] pb-3">
              <h1 className="text-xl font-semibold text-[var(--cds-text-primary)]">{spec.title}</h1>
              {spec.subtitle ? <p className="mt-1 text-sm text-[var(--cds-text-secondary)]">{spec.subtitle}</p> : null}
            </header>
            {spec.sections.map(section => (
              <section
                className={'mb-4 ' + (section.id === selectedSectionId ? '' : '')}
                data-document-section={section.id}
                key={section.id}
              >
                <h2 className="mb-1 mt-2 text-base font-semibold text-[var(--cds-text-primary)]">{section.heading}</h2>
                {section.paragraphs.map((paragraph, index) => (
                  <p key={`${section.id}-p-${index}`} className="mb-2 text-sm leading-relaxed text-[var(--cds-text-primary)]">{paragraph}</p>
                ))}
                {section.bullets.length ? (
                  <ul className="mb-2 list-disc pl-5 text-sm text-[var(--cds-text-primary)]">
                    {section.bullets.map((bullet, index) => (
                      <li key={`${section.id}-b-${index}`}>{bullet}</li>
                    ))}
                  </ul>
                ) : null}
              </section>
            ))}
          </article>
        </div>
      </section>
    </main>
  )
}
